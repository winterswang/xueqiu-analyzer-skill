"""
xueqiu-analyzer V4 — 深度舆情分析器

单股票深度分析：爬取 → 本地存储 → DeepSeek 4.0-flash 分析 → 结构化报告 + 原文索引
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from .crawler import XueqiuCrawler
from .llm_client import LLMClient
from .models import CrawlResult

logger = logging.getLogger(__name__)

DEFAULT_STORAGE_DIR = Path('~/.xueqiu_stocks').expanduser()

class StockAnalyzer:
    """单股票深度舆情分析器"""

    def __init__(self, crawler: XueqiuCrawler = None,
                 llm_client: LLMClient = None,
                 storage_dir: Path = None):
        self.crawler = crawler or XueqiuCrawler()
        self.llm = llm_client or LLMClient()
        self.storage_dir = storage_dir or DEFAULT_STORAGE_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def analyze(self, symbol: str,
                max_pages: int = 10,
                days: int = 0,
                max_articles: int = 10) -> dict:
        """
        完整分析流程：爬取 → 存储 → LLM 分析 → 返回报告

        Args:
            symbol: 股票代码（如 SH600519）
            max_pages: 最大分页数（10页×20条=200条，0=只用days过滤）
            days: 时间过滤（0=不限，N=只看最近 N 天）
            max_articles: 最大文章详情数

        Returns:
            dict: {
                'symbol': str,
                'crawl_result': CrawlResult,
                'raw_data': dict,  # 带 index 的原始数据
                'analysis': dict,   # LLM 分析结果（JSON dict）
                'report_md': str,   # Markdown 报告
                'raw_file': str,    # 原始数据文件路径
                'report_file': str, # 报告文件路径
            }
        """
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        stock_dir = self.storage_dir / symbol / ts
        stock_dir.mkdir(parents=True, exist_ok=True)

        # Phase 1: 爬取
        logger.info(f"[{symbol}] 开始爬取... max_pages={max_pages}, days={days}")
        crawl_result = self.crawler.crawl(
            symbol, max_pages=max_pages, max_articles=max_articles, days=days
        )

        # Phase 2: 组装带 index 的原始数据
        raw_data = self._build_raw_data(crawl_result)
        raw_file = stock_dir / 'raw.json'
        with open(raw_file, 'w', encoding='utf-8') as f:
            json.dump(raw_data, f, ensure_ascii=False, indent=2)
        logger.info(f"[{symbol}] 原始数据已存储: {raw_file}")

        # Phase 3: LLM 分析
        logger.info(f"[{symbol}] 调用 DeepSeek 4.0-flash 分析...")
        analysis = self._analyze_with_llm(raw_data, symbol)
        analysis_file = stock_dir / 'analysis.json'
        with open(analysis_file, 'w', encoding='utf-8') as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
        logger.info(f"[{symbol}] 分析结果已存储: {analysis_file}")

        # Phase 4: 生成 Markdown 报告
        report_md = self._build_report_md(symbol, raw_data, analysis, crawl_result)
        report_file = stock_dir / 'report.md'
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report_md)
        logger.info(f"[{symbol}] 报告已生成: {report_file}")

        return {
            'symbol': symbol,
            'crawl_result': crawl_result,
            'raw_data': raw_data,
            'analysis': analysis,
            'report_md': report_md,
            'raw_file': str(raw_file),
            'report_file': str(report_file),
        }

    def _build_raw_data(self, result: CrawlResult) -> dict:
        """给每条数据分配全局 index，组装成原始数据字典"""
        discussions = []
        idx = 1

        # 讨论（按时间倒序）
        for disc in sorted(result.discussions, key=lambda x: x.time, reverse=True):
            discussions.append({
                'index': idx,
                'type': 'discussion',
                'author': disc.author,
                'content': disc.content,
                'time': disc.time,
                'link': disc.link,
                'is_column': disc.is_column,
            })
            idx += 1

        # 专栏文章
        columns = []
        for art in sorted(result.articles, key=lambda x: x.time, reverse=True):
            columns.append({
                'index': idx,
                'type': 'column',
                'author': art.author,
                'title': art.title,
                'content': art.content,
                'time': art.time,
                'link': art.link,
            })
            idx += 1

        # 资讯
        news_list = []
        for n in sorted(result.news, key=lambda x: x.time, reverse=True):
            news_list.append({
                'index': idx,
                'type': 'news',
                'title': n.title,
                'content': n.content,
                'time': n.time,
                'link': n.link,
            })
            idx += 1

        # 公告
        notices = []
        for nt in sorted(result.notices, key=lambda x: x.time, reverse=True):
            notices.append({
                'index': idx,
                'type': 'notice',
                'title': nt.title,
                'content': nt.content,
                'time': nt.time,
                'link': nt.link,
            })
            idx += 1

        return {
            'discussions': discussions,
            'columns': columns,
            'news': news_list,
            'notices': notices,
            'meta': {
                'total_discussions': len(discussions),
                'total_columns': len(columns),
                'total_news': len(news_list),
                'total_notices': len(notices),
            }
        }

    def _build_prompt(self, raw_data: dict, symbol: str) -> str:
        """构建发给 LLM 的 prompt"""
        # 序列化原文数据（截断超长内容）
        def truncate(obj, max_len=600):
            if isinstance(obj, dict):
                return {k: truncate(v, max_len) for k, v in obj.items()}
            if isinstance(obj, str) and len(obj) > max_len:
                return obj[:max_len] + '...[内容已截断]'
            return obj

        truncated = truncate(json.loads(json.dumps(raw_data)))
        data_str = json.dumps(truncated, ensure_ascii=False, indent=2)

        prompt = f"""你是一位专业、严谨的价值投资研究助手。

给定一只股票在雪球上的舆情数据，请进行深度分析，严格输出以下 JSON 格式：

{{
  "summary": "核心舆情摘要（50字以内）",
  "bull_points": ["看多点1", "看多点2", "看多点3"],
  "bear_points": ["风险点1", "风险点2"],
  "topics": [{{"name": "话题", "mentions": N, "sentiment": "正面/中性/负面", "key_views": ["观点1"]}}],
  "high_value_columns": [{{"index": N, "author": "作者", "title": "标题", "key_points": "核心要点"}}],
  "high_value_discussions": [{{"index": N, "author": "作者", "content": "摘要", "sentiment": "正面/中性/负面"}}],
  "key_notices": [{{"index": N, "title": "公告标题", "time": "日期", "key_info": "关键信息"}}],
  "actionable_insights": ["可执行洞见1", "可执行洞见2"],
  "concerns": ["需确认风险1"]
}}

【index 引用规则】
- 原文数据中每条记录有一个 index 字段（从1开始）
- high_value_columns / high_value_discussions / key_notices 中的 index 必须对应原文中的 index
- 只引用真正有价值的条目，不要罗列所有内容

【原文数据】
{data_str}

请严格输出 JSON，不要输出任何其他内容。"""
        return prompt

    def _analyze_with_llm(self, raw_data: dict, symbol: str) -> dict:
        """调用 DeepSeek 分析，返回 dict"""
        prompt = self._build_prompt(raw_data, symbol)
        try:
            messages = [
                {"role": "user", "content": prompt},
            ]
            result_text = self.llm.chat(messages, max_tokens=32000)
            result_text = result_text.strip()
            if result_text.startswith('```'):
                lines = result_text.split('\n')
                result_text = '\n'.join(lines[1:] if lines[0].startswith('```') else lines)
                result_text = result_text.rstrip('```')
            return json.loads(result_text)
        except json.JSONDecodeError as e:
            logger.warning(f"[{symbol}] LLM 返回非 JSON: {e}\n内容: {result_text[:200]}")
            return {
                'error': f'LLM 返回解析失败: {e}',
                'raw_response': result_text[:500]
            }

    def _build_report_md(self, symbol: str, raw_data: dict,
                          analysis: dict, crawl_result) -> str:
        """生成 Markdown 格式的最终报告"""
        meta = raw_data['meta']
        now = datetime.now().strftime('%Y-%m-%d %H:%M')

        lines = [
            f"# {crawl_result.name or symbol}（{symbol}）深度舆情分析",
            f"",
            f"**分析时间**: {now}",
            f"**数据规模**: {meta['total_discussions']} 条讨论 / "
            f"{meta['total_columns']} 篇专栏 / "
            f"{meta['total_news']} 条新闻 / "
            f"{meta['total_notices']} 条公告",
            f"",
            "---",
            "",
        ]

        # 摘要
        if 'summary' in analysis:
            lines += [
                "## 一、核心舆情摘要",
                "",
                analysis['summary'],
                "",
                "---",
                "",
            ]

        # 多空观点
        if analysis.get('bull_points'):
            lines += [
                "## 二、多方观点（看多理由）",
                "",
            ]
            for pt in analysis['bull_points']:
                lines.append(f"- {pt}")
            lines += ["", "---", ""]

        if analysis.get('bear_points'):
            lines += [
                "## 三、空方观点（风险因素）",
                "",
            ]
            for pt in analysis['bear_points']:
                lines.append(f"- {pt}")
            lines += ["", "---", ""]

        # 主题分布
        if analysis.get('topics'):
            lines += [
                "## 四、主题分布",
                "",
                "| 话题 | 提及次数 | 情绪 | 核心观点 |",
                "|------|---------|------|---------|"
            ]
            for t in analysis['topics']:
                key_views = '；'.join(t.get('key_views', [])[:2])
                lines.append(f"| {t['name']} | {t['mentions']} | {t['sentiment']} | {key_views} |")
            lines += ["", "---", ""]

        # 高价值专栏
        if analysis.get('high_value_columns'):
            lines += [
                "## 五、高价值专栏文章",
                "",
            ]
            for col in analysis['high_value_columns']:
                idx = col.get('index', '?')
                # 找到原文链接
                link = ''
                for c in raw_data.get('columns', []):
                    if c['index'] == idx:
                        link = c.get('link', '')
                        break
                link_str = f" [原文]({link})" if link else ""
                lines.append(f"- **[@index={idx}]** {col['author']}：{col['title']}{link_str}")
                if col.get('key_points'):
                    lines.append(f"  - 要点：{col['key_points']}")
            lines += ["", "---", ""]

        # 高价值讨论
        if analysis.get('high_value_discussions'):
            lines += [
                "## 六、高价值讨论",
                "",
            ]
            for disc in analysis['high_value_discussions']:
                idx = disc.get('index', '?')
                link = ''
                for d in raw_data.get('discussions', []):
                    if d['index'] == idx:
                        link = d.get('link', '')
                        break
                link_str = f" [原文]({link})" if link else ""
                sentiment = disc.get('sentiment', '中性')
                lines.append(f"- **[@index={idx}]** [{sentiment}] {disc['author']}：{disc['content']}{link_str}")
            lines += ["", "---", ""]

        # 关键公告
        if analysis.get('key_notices'):
            lines += [
                "## 七、关键公告",
                "",
            ]
            for notice in analysis['key_notices']:
                idx = notice.get('index', '?')
                link = ''
                for n in raw_data.get('notices', []):
                    if n['index'] == idx:
                        link = n.get('link', '')
                        break
                link_str = f" [PDF]({link})" if link else ""
                lines.append(f"- **[@index={idx}]** [{notice.get('time', '')}] {notice['title']}{link_str}")
                if notice.get('key_info'):
                    lines.append(f"  - {notice['key_info']}")
            lines += ["", "---", ""]

        # 可执行洞见
        if analysis.get('actionable_insights'):
            lines += [
                "## 八、可执行的投资洞见",
                "",
            ]
            for ins in analysis['actionable_insights']:
                lines.append(f"- {ins}")
            lines += ["", "---", ""]

        # 需进一步确认的风险
        if analysis.get('concerns'):
            lines += [
                "## 九、需进一步确认的风险",
                "",
            ]
            for c in analysis['concerns']:
                lines.append(f"- {c}")
            lines += ["", "---", ""]

        # 原文索引（附录）
        lines += [
            "## 附录：原文索引",
            "",
            "点击 index 可在本地 raw.json 中找到对应原文",
            "",
        ]
        for c in raw_data.get('columns', []):
            if c.get('link'):
                lines.append(f"- [@index={c['index']}] 专栏：{c['title']} — {c['link']}")
        for d in raw_data.get('discussions', []):
            if d.get('link') and len(d['content']) > 30:
                lines.append(f"- [@index={d['index']}] 讨论：{d['content'][:40]}... — {d['link']}")

        lines.append("")
        lines.append(f"_报告生成时间: {now}_")

        return '\n'.join(lines)