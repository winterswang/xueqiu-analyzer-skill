"""
xueqiu-analyzer V3 — 数据质量检测器（Layer 1：硬指标）

在 LLM 评估之前，用纯代码检查数据完整性，不需要 LLM。
产出 ContentQualityReport，用于指导定向重爬和预警。
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
import logging

from .models import CrawlResult

logger = logging.getLogger(__name__)

# ── 质量阈值 ──
MIN_CONTENT_LENGTH = 20          # 正文至少 20 字符才算"有内容"
MIN_ARTICLE_LENGTH = 200         # 文章至少 200 字符
NEWS_MIN_RATIO = 0.5             # 资讯有内容率至少 50%
NOTICE_MIN_RATIO = 0.3           # 公告有内容率至少 30%
HEALTH_THRESHOLD = 70            # 爬取健康分低于此值触发重爬
FINANCIAL_WEIGHT = 15            # 财务数据占总分权重
CONTENT_WEIGHTS = {
    'news': 25,
    'notices': 25,
    'articles': 20,
    'discussions': 15,
}


@dataclass
class ContentQualityReport:
    """Layer 1 数据质量报告"""

    # 逐类统计
    news_count: int = 0
    news_with_content: int = 0
    notice_count: int = 0
    notice_with_content: int = 0
    article_count: int = 0
    article_with_content: int = 0
    discussion_count: int = 0
    discussion_with_content: int = 0

    # 财务数据完整性
    financial_fields_populated: List[str] = field(default_factory=list)
    financial_fields_missing: List[str] = field(default_factory=list)

    # 综合评分
    health_score: int = 0           # 0-100，爬取健康分
    is_healthy: bool = True         # 是否通过硬指标

    # 预警
    alerts: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    @property
    def news_ratio(self) -> float:
        return self.news_with_content / self.news_count if self.news_count else 0

    @property
    def notice_ratio(self) -> float:
        return self.notice_with_content / self.notice_count if self.notice_count else 0

    @property
    def article_ratio(self) -> float:
        return self.article_with_content / self.article_count if self.article_count else 0

    @property
    def discussion_ratio(self) -> float:
        return (self.discussion_with_content / self.discussion_count
                if self.discussion_count else 0)

    @property
    def financial_completeness(self) -> float:
        """财务数据字段填充率"""
        total = len(self.financial_fields_populated) + len(self.financial_fields_missing)
        return len(self.financial_fields_populated) / total if total else 0

    def to_dict(self) -> dict:
        return asdict(self)


class ContentQualityChecker:
    """数据质量硬指标检测器 —— 不依赖 LLM"""

    def check(self, result: CrawlResult) -> ContentQualityReport:
        """
        对爬取结果进行硬指标检测

        Returns:
            ContentQualityReport 包含逐类完整率、健康分、预警
        """
        report = ContentQualityReport()
        alerts = []
        suggestions = []

        # ── 1. 资讯检测 ──
        report.news_count = len(result.news)
        report.news_with_content = sum(
            1 for n in result.news
            if n.content and len(n.content.strip()) >= MIN_CONTENT_LENGTH
        )
        if report.news_count > 0 and report.news_ratio < NEWS_MIN_RATIO:
            alerts.append(
                f"⚠️ 资讯有内容率 {report.news_ratio:.0%} < {NEWS_MIN_RATIO:.0%}"
            )
            suggestions.append("新闻")

        # ── 2. 公告检测 ──
        report.notice_count = len(result.notices)
        report.notice_with_content = sum(
            1 for n in result.notices
            if n.content and len(n.content.strip()) >= MIN_CONTENT_LENGTH
        )
        if report.notice_count > 0 and report.notice_ratio < NOTICE_MIN_RATIO:
            alerts.append(
                f"⚠️ 公告有内容率 {report.notice_ratio:.0%} < {NOTICE_MIN_RATIO:.0%}"
            )
            if '新闻' not in suggestions:
                suggestions.append('公告')

        # ── 3. 文章检测 ──
        report.article_count = len(result.articles)
        report.article_with_content = sum(
            1 for a in result.articles
            if a.content and len(a.content.strip()) >= MIN_ARTICLE_LENGTH
        )
        if report.article_count == 0:
            alerts.append("⚠️ 无专栏文章，管理层/深度分析可能缺失")

        # ── 4. 讨论检测 ──
        report.discussion_count = len(result.discussions)
        report.discussion_with_content = sum(
            1 for d in result.discussions
            if d.content and len(d.content.strip()) >= MIN_CONTENT_LENGTH
        )

        # ── 5. 财务数据检测 ──
        fd = result.financial_data
        if fd:
            _check_field(report, fd.pe_ttm, 'pe_ttm', 'PE(TTM)')
            _check_field(report, fd.pb, 'pb', 'PB')
            _check_field(report, fd.roe, 'roe', 'ROE')
            _check_field(report, fd.gross_margin, 'gross_margin', '毛利率')
            _check_field(report, fd.net_margin, 'net_margin', '净利率')
            _check_field(report, fd.revenue_growth, 'revenue_growth', '营收增速')
            _check_field(report, fd.profit_growth, 'profit_growth', '利润增速')

            if report.financial_fields_missing:
                alerts.append(
                    f"⚠️ 财务缺 {len(report.financial_fields_missing)} 项: "
                    f"{', '.join(report.financial_fields_missing)}"
                )
        else:
            alerts.append("🔴 财务数据完全缺失")
            report.financial_fields_missing = [
                'PE', 'PB', 'ROE', '毛利率', '净利率', '营收增速', '利润增速'
            ]

        # ── 6. 计算健康分 ──
        report.health_score = self._calc_health_score(report)
        report.is_healthy = report.health_score >= HEALTH_THRESHOLD
        report.alerts = alerts

        # ── 7. 生成定向建议 ──
        if not report.is_healthy and suggestions:
            report.suggestions = suggestions
        elif report.article_count == 0:
            report.suggestions = ['文章']

        return report

    def _calc_health_score(self, r: ContentQualityReport) -> int:
        """计算爬取健康分 (0-100)"""
        score = 0

        # 资讯有内容率
        score += CONTENT_WEIGHTS['news'] * min(r.news_ratio / NEWS_MIN_RATIO, 1.0)

        # 公告有内容率
        score += CONTENT_WEIGHTS['notices'] * min(r.notice_ratio / NOTICE_MIN_RATIO, 1.0)

        # 文章有内容率+数量
        article_quality = r.article_ratio if r.article_count > 0 else 0
        article_bonus = min(r.article_count / 5, 1.0)
        score += CONTENT_WEIGHTS['articles'] * article_quality * article_bonus

        # 讨论（仅数量，不要求有"评论"内容）
        disc_bonus = min(r.discussion_count / 10, 1.0) if r.discussion_count > 0 else 0
        score += CONTENT_WEIGHTS['discussions'] * disc_bonus

        # 财务数据完整性
        score += FINANCIAL_WEIGHT * r.financial_completeness

        return int(score)

    @staticmethod
    def format_report(report: ContentQualityReport) -> str:
        """格式化质量报告为 Markdown"""
        lines = [
            "## 📊 爬取数据质量报告（硬指标）\n",
            f"**健康分**: {report.health_score}/100 "
            f"{'✅ 通过' if report.is_healthy else '🔴 不及格'}\n",
        ]

        # 内容完整率
        lines.append("### 内容完整率\n")
        lines.append(
            f"| 类别 | 总数 | 有内容 | 完整率 | 状态 |\n"
            f"|------|:---:|:---:|:---:|:---:|"
        )

        for label, count, has_c, ratio, min_r in [
            ('资讯', report.news_count, report.news_with_content,
             report.news_ratio, NEWS_MIN_RATIO),
            ('公告', report.notice_count, report.notice_with_content,
             report.notice_ratio, NOTICE_MIN_RATIO),
            ('文章', report.article_count, report.article_with_content,
             report.article_ratio, None),
            ('讨论', report.discussion_count, report.discussion_with_content,
             report.discussion_ratio, None),
        ]:
            if count == 0:
                status = '🟡 无数据'
            elif min_r and ratio < min_r:
                status = f'🔴 {ratio:.0%}'
            elif ratio == 1:
                status = f'✅ {ratio:.0%}'
            else:
                status = f'✅ {ratio:.0%}'
            lines.append(
                f"| {label} | {count} | {has_c} | {ratio:.0%} | {status} |"
            )
        lines.append("")

        # 财务数据
        lines.append("### 财务数据完整性\n")
        if report.financial_fields_populated:
            fields = ', '.join(report.financial_fields_populated)
            lines.append(f"✅ 已获取: {fields}\n")
        if report.financial_fields_missing:
            fields = ', '.join(report.financial_fields_missing)
            lines.append(f"❌ 缺失: {fields}\n")
        lines.append(f"完整率: {report.financial_completeness:.0%}\n")

        # 预警
        if report.alerts:
            lines.append("### ⚠️ 预警\n")
            for alert in report.alerts:
                lines.append(f"- {alert}")
            lines.append("")

        # 建议
        if report.suggestions:
            lines.append("### 🎯 重爬建议\n")
            types = ', '.join(report.suggestions)
            lines.append(f"建议优先补充: **{types}**\n")

        return '\n'.join(lines)


def _check_field(report: ContentQualityReport, value, key: str, label: str):
    """检查单个财务字段是否填充"""
    if value and value > 0:
        report.financial_fields_populated.append(label)
    else:
        report.financial_fields_missing.append(label)
