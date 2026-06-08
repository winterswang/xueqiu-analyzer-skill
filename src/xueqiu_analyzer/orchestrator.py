"""
xueqiu-analyzer V3 — 编排器

迭代爬取→评估→补充→分析的主循环。
只管流程编排，不含业务逻辑。
"""

import json
import os
import time
import logging
from pathlib import Path
from .models import CrawlResult, EvaluationResult, AnalysisResult
from .config import get_config, get_data_dir
from .evaluator import Evaluator
from .analyzer import Analyzer
from .financial_fetcher import FinancialFetcher
from .quality import ContentQualityChecker, ContentQualityReport, HEALTH_THRESHOLD
from .ima_publisher import publish_report, prepend_report_title

logger = logging.getLogger(__name__)


class Orchestrator:
    """迭代爬取编排器"""

    def __init__(self, config: dict = None):
        self.config = config or get_config()
        self.evaluator = Evaluator(config=self.config)
        self.analyzer = Analyzer(config=self.config)
        self.quality_checker = ContentQualityChecker(
            config=self.config.get('quality', {}))

    def run(self, symbol: str, max_rounds: int = None,
            data_path: str = None, template: str = 'analysis',
            crawl_fn=None, ima_folder: str = None,
            ima_folder_name: str = None) -> AnalysisResult:
        """
        完整流程：爬取→评估→补充→分析

        Args:
            symbol: 股票代码
            max_rounds: 最大爬取轮次
            data_path: 已有数据文件路径（跳过爬取）
            template: 分析模板名
            crawl_fn: 外部注入的爬取函数（用于解耦）
            ima_folder: IMA 笔记本 ID
            ima_folder_name: IMA 笔记本名称

        Returns:
            AnalysisResult
        """
        max_rounds = max_rounds or self.config['evaluator']['max_rounds']
        threshold = self.config['evaluator']['score_threshold']

        # 1. 加载或爬取数据
        if data_path:
            crawl_result = self._load_data(data_path)
            logger.info(f"从文件加载数据: {data_path} "
                        f"({crawl_result.total_items} 条)")
        else:
            crawl_result = self._iterative_crawl(
                symbol, max_rounds, threshold, crawl_fn)

        # 1.5 获取财务数据（如果还没拿到）
        if not crawl_result.financial_data or not crawl_result.financial_data.has_data:
            try:
                fetcher = FinancialFetcher()
                cookies = self._load_cookies()
                fd = fetcher.fetch(symbol, cookies)
                if fd:
                    crawl_result.financial_data = fd
                    logger.info(f"  财务数据: PE={fd.pe_ttm:.1f}, "
                                f"PB={fd.pb:.1f}, ROE={fd.roe:.1f}%")
            except Exception as e:
                logger.warning(f"  财务数据获取失败: {e}")

        # 1.6 内容分级 — LLM 驱动的高价值讨论筛选
        grader_config = self.config.get('grader', {})
        if grader_config.get('enabled', True) and crawl_result.discussions:
            try:
                from .content_grader import ContentGrader
                grader = ContentGrader(
                    config=self.config,
                    threshold=grader_config.get('threshold', 10)
                )
                grade_result = grader.grade(
                    discussions=self._dictify_discussions(crawl_result),
                    articles=self._dictify_articles(crawl_result),
                )
                logger.info(
                    f"  内容分级: {len(crawl_result.discussions)} 讨论 + "
                    f"{len(crawl_result.articles)} 专栏 → "
                    f"{grade_result.quality_count} 条高质量内容"
                )
                if grade_result.themes:
                    for t in grade_result.themes[:3]:
                        logger.info(f"  争议: {t.name}")
                # 将精选讨论 ID 注入 crawl_result 供 analyzer 使用
                crawl_result._grader_result = grade_result  # type: ignore
            except Exception as e:
                logger.warning(f"  内容分级失败, 使用全量数据: {e}")

        # 2. 评估
        evaluation = self.evaluator.evaluate(crawl_result)
        self._log_evaluation(evaluation)

        # 3. 分析
        self.analyzer.template = template
        report = self.analyzer.analyze(crawl_result, evaluation)

        # 4. 保存
        paths = self._save_results(
            symbol, crawl_result, evaluation, report,
            ima_folder=ima_folder, ima_folder_name=ima_folder_name,
        )

        # 5. 通知
        self._notify(symbol, evaluation, paths)

        return AnalysisResult(
            symbol=symbol,
            report=report,
            evaluation=evaluation,
            model=self.analyzer.llm.model,
            template=template,
        )

    def _iterative_crawl(self, symbol: str, max_rounds: int,
                         threshold: int, crawl_fn) -> CrawlResult:
        """迭代爬取循环 —— Layer 1 硬指标检测在 LLM 评估之前"""
        if crawl_fn is None:
            raise ValueError(
                "未提供 crawl_fn，请传入爬取函数或指定 data_path")

        quality_config = self.config.get('quality', {})
        health_threshold = quality_config.get('health_threshold', HEALTH_THRESHOLD)

        result = CrawlResult(symbol=symbol)
        last_quality_report = None

        for round_num in range(1, max_rounds + 1):
            logger.info(f"=== 第 {round_num}/{max_rounds} 轮 ===")

            # 定向爬取：根据上一轮质量报告的 suggestions 调整策略
            pages = min(5 + round_num, 10)
            articles = min(10 + round_num * 3, 30)

            if last_quality_report and last_quality_report.suggestions:
                suggestions = last_quality_report.suggestions
                logger.info(f"🎯 定向补充: {', '.join(suggestions)}")
                # 文章不足 → 多拉文章；资讯/公告不足 → 多翻页
                if '文章' in suggestions:
                    articles = min(articles + 10, 30)
                if '新闻' in suggestions or '公告' in suggestions:
                    pages = min(pages + 5, 15)

            new_data = crawl_fn(symbol, max_pages=pages,
                                max_articles=articles)
            result = result.merge(new_data)

            logger.info(f"累计: {len(result.discussions)} 讨论, "
                        f"{len(result.news)} 资讯, "
                        f"{len(result.notices)} 公告, "
                        f"{len(result.articles)} 文章")

            # ── Layer 1: 硬指标检查 ──
            last_quality_report = self.quality_checker.check(result)
            self._log_quality(last_quality_report)

            if not last_quality_report.is_healthy:
                if round_num >= max_rounds:
                    logger.warning("⚠️ 达到最大轮次，硬指标仍不及格，降级进入分析")
                    break
                logger.info(
                    f"🔴 数据质量不及格 "
                    f"({last_quality_report.health_score}/{health_threshold})，"
                    f"定向重爬..."
                )
                # 不等待直接进入下一轮
                continue

            # ── Layer 2: LLM 充分性评估 ──
            evaluation = self.evaluator.evaluate(result)
            self._log_evaluation(evaluation)

            if evaluation.effective_score >= threshold:
                logger.info(f"✅ 信息充分 "
                            f"({evaluation.effective_score}分 >= {threshold})")
                break
            elif round_num >= max_rounds:
                logger.warning("⚠️ 达到最大轮次，强制进入分析")
                break
            else:
                logger.info(f"🔄 信息不足 "
                            f"({evaluation.effective_score}/{threshold})，继续爬取")
                time.sleep(2)

        # 附加最后一轮质量报告到 result（供下游使用）
        result._quality_report = last_quality_report  # type: ignore
        return result

    def _load_cookies(self) -> list:
        """加载 cookies"""
        cookies_path = Path(os.path.expanduser('~/.xueqiu_crawler/cookies.json'))
        if cookies_path.exists():
            with open(cookies_path) as f:
                return json.load(f)
        return []

    def _dictify_discussions(self, crawl_result) -> list:
        """将 Discussion 对象转为 dict (供 ContentGrader 使用)"""
        return [
            {"author": d.author, "content": d.content, "time": d.time,
             "link": getattr(d, 'link', '')}
            for d in crawl_result.discussions
        ]

    def _dictify_articles(self, crawl_result) -> list:
        """将 Article 对象转为 dict (供 ContentGrader 使用)"""
        return [
            {"author": a.author, "content": a.content, "title": a.title,
             "time": a.time, "link": getattr(a, 'link', '')}
            for a in crawl_result.articles
        ]

    def _load_data(self, path: str) -> CrawlResult:
        """从 JSON 文件加载数据"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return CrawlResult.from_dict(data)

    def _log_evaluation(self, eval_result: EvaluationResult):
        """日志输出 LLM 评估结果"""
        logger.info(f"评分: {eval_result.effective_score}/"
                    f"{200 + eval_result.financial_bonus} "
                    f"| 充分性: {eval_result.sufficiency}")
        for topic, info in eval_result.scores.items():
            score = info.get('score', 0) if isinstance(info, dict) else 0
            bar = '█' * (score // 5)
            logger.info(f"  {topic}: {score:2d}分 {bar}")

    def _log_quality(self, qr: ContentQualityReport):
        """日志输出硬指标质量报告"""
        status = '✅' if qr.is_healthy else '🔴'
        logger.info(
            f"数据质量: {qr.health_score}/100 {status} "
            f"| 资讯{int(qr.news_ratio*100)}% "
            f"公告{int(qr.notice_ratio*100)}% "
            f"财务{int(qr.financial_completeness*100)}%"
        )
        for alert in qr.alerts:
            logger.info(f"  {alert}")

    def _save_results(self, symbol: str, crawl_result: CrawlResult,
                      evaluation: EvaluationResult,
                      report: str,
                      ima_folder: str = None,
                      ima_folder_name: str = None) -> dict:
        """保存结果文件"""
        data_dir = get_data_dir()
        timestamp = time.strftime('%Y%m%d_%H%M%S')

        paths = {}

        # 完整数据
        data_path = data_dir / f'{symbol}_data_{timestamp}.json'
        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump(crawl_result.to_dict(), f, ensure_ascii=False,
                      indent=2)
        paths['data'] = str(data_path)

        # 质量报告（Layer 1 硬指标）
        quality_report = getattr(crawl_result, '_quality_report', None)

        # 评估报告（Layer 2 LLM评分）
        eval_path = data_dir / f'{symbol}_evaluation_{timestamp}.md'
        eval_report = self._format_evaluation_report(
            symbol, evaluation, crawl_result, quality_report
        )
        eval_path.write_text(eval_report, encoding='utf-8')
        paths['evaluation'] = str(eval_path)

        # 分析报告 — 添加标题前缀
        stock_name = getattr(crawl_result, 'name', symbol) or symbol
        titled_report = prepend_report_title(report, symbol, stock_name)
        report_path = data_dir / f'{symbol}_report_{timestamp}.md'
        report_path.write_text(titled_report, encoding='utf-8')
        paths['report'] = str(report_path)

        logger.info(f"报告已保存: {paths['report']}")

        # 发布到 IMA 笔记
        pkwargs = {}
        if ima_folder:
            pkwargs['folder_id'] = ima_folder
        if ima_folder_name:
            pkwargs['folder_name'] = ima_folder_name
        note_id = publish_report(titled_report, **pkwargs)
        if note_id:
            paths['ima_note_id'] = note_id
            logger.info(f"IMA 笔记: note_id={note_id}")
        return paths

    def _format_evaluation_report(self, symbol: str,
                                  evaluation: EvaluationResult,
                                  data: CrawlResult,
                                  quality_report: ContentQualityReport = None
                                  ) -> str:
        """格式化评估报告"""
        lines = [f"# {symbol} 信息充分性评估报告\n"]

        # ── Layer 1: 数据质量硬指标 ──
        if quality_report:
            lines.append(ContentQualityChecker.format_report(quality_report))
            lines.append("\n---\n")

        lines.append("## Layer 2: LLM 信息充分性评分\n")
        lines.append(f"**总分**: {evaluation.effective_score}/"
                     f"{200 + evaluation.financial_bonus}\n")
        lines.append(f"**充分性**: {evaluation.sufficiency}\n\n")

        lines.append("## 各主题评分\n")
        for topic, info in evaluation.scores.items():
            if isinstance(info, dict):
                score = info.get('score', 0)
                reason = info.get('reason', '')
                evidence = info.get('evidence', '')
                bar = '█' * (score // 5)
                lines.append(f"### {topic} - {score}分 {bar}\n")
                lines.append(f"**理由**: {reason}\n")
                if evidence:
                    lines.append(f"**证据**: {evidence}\n")
                lines.append("")

        # Token 统计
        if evaluation.token_stats:
            lines.append("## Token 统计\n")
            for key, val in evaluation.token_stats.items():
                if isinstance(val, dict):
                    lines.append(
                        f"- {key}: {val.get('count', 0)}条, "
                        f"~{val.get('tokens', 0)} tokens")
            lines.append("")

        return '\n'.join(lines)

    def _notify(self, symbol: str, evaluation: EvaluationResult,
                paths: dict):
        """发送通知（Gist + 飞书）"""
        notify_config = self.config.get('notify', {})

        if notify_config.get('gist', True):
            self._upload_gist(paths)

        if notify_config.get('feishu', True):
            self._send_feishu(symbol, evaluation, paths)

    def _upload_gist(self, paths: dict):
        """上传报告到 GitHub Gist"""
        import subprocess
        import shutil

        if not shutil.which('gh'):
            logger.warning("gh CLI 未安装，跳过 Gist 上传")
            return

        for key in ['report', 'evaluation']:
            path = paths.get(key)
            if not path or not Path(path).exists():
                continue
            try:
                result = subprocess.run(
                    ['gh', 'gist', 'create', path],
                    capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    logger.info(f"Gist ({key}): {result.stdout.strip()}")
                else:
                    logger.warning(f"Gist 上传失败 ({key}): "
                                   f"{result.stderr}")
            except Exception as e:
                logger.warning(f"Gist 上传异常: {e}")

    def _send_feishu(self, symbol: str, evaluation: EvaluationResult,
                     paths: dict):
        """发送飞书通知"""
        import os

        target = os.environ.get(
            'FEISHU_TARGET_USER',
            self.config.get('notify', {}).get('feishu_target', ''))

        message = (
            f"📊 **{symbol} 雪球分析完成**\n\n"
            f"**评分**: {evaluation.effective_score}/"
            f"{200 + evaluation.financial_bonus}\n"
            f"**充分性**: {evaluation.sufficiency}\n"
        )

        # 使用 PID 避免并发运行时互相覆盖
        pid = os.getpid()
        pending_path = Path(f'/tmp/pending_feishu_xueqiu_analysis_{pid}.json')
        try:
            payload = {
                'channel': 'feishu',
                'target': target,
                'message': message,
            }
            pending_path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            logger.info(f"飞书通知已准备: {pending_path}")
        except Exception as e:
            logger.warning(f"飞书通知准备失败: {e}")
