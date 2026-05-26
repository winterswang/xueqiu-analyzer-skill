"""
xueqiu-analyzer V3 — 数据模型

所有模块共用的数据结构，与 LLM/爬虫/配置完全解耦。
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from datetime import datetime


@dataclass
class Discussion:
    """雪球讨论"""
    author: str
    content: str
    time: str
    link: str = ""
    is_column: bool = False  # 是否专栏文章
    comments: List[str] = field(default_factory=list)


@dataclass
class News:
    """雪球资讯"""
    title: str
    content: str
    time: str
    source: str = ""
    link: str = ""


@dataclass
class Notice:
    """雪球公告"""
    title: str
    link: str
    time: str = ""
    content: str = ""
    pdf_link: str = ""
    notice_type: str = ""  # 翌日披露/末期业绩/股息等


@dataclass
class Article:
    """雪球专栏文章"""
    title: str
    author: str
    content: str
    time: str
    link: str = ""
    article_id: str = ""
    is_column: bool = True  # 专栏文章标记


@dataclass
class FinancialData:
    """财务数据"""
    pe_ttm: float = 0
    pb: float = 0
    roe: float = 0
    market_cap: float = 0
    gross_margin: float = 0
    net_margin: float = 0
    revenue_growth: float = 0
    profit_growth: float = 0
    low52w: float = 0
    high52w: float = 0
    yearly_roic: List[Dict] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return self.pe_ttm > 0 or self.pb > 0 or self.roe > 0

    @property
    def has_roic(self) -> bool:
        return len(self.yearly_roic) > 0


@dataclass
class CrawlResult:
    """爬虫输出 — 标准数据格式，所有模块的通用输入"""
    symbol: str
    name: str = ""
    price: str = ""
    change: str = ""
    discussions: List[Discussion] = field(default_factory=list)
    news: List[News] = field(default_factory=list)
    notices: List[Notice] = field(default_factory=list)
    articles: List[Article] = field(default_factory=list)
    financial_data: Optional[FinancialData] = None
    crawled_at: str = ""

    def __post_init__(self):
        if not self.crawled_at:
            self.crawled_at = datetime.now().isoformat()

    @property
    def total_items(self) -> int:
        return (len(self.discussions) + len(self.news) +
                len(self.notices) + len(self.articles))

    def merge(self, other: 'CrawlResult') -> 'CrawlResult':
        """合并两个爬取结果（去重）"""
        seen_links = {d.link for d in self.discussions if d.link}
        seen_links |= {n.link for n in self.news if n.link}
        seen_links |= {a.link for a in self.articles if a.link}
        seen_links |= {nt.link for nt in self.notices if nt.link}

        new_discussions = [d for d in other.discussions
                           if d.link not in seen_links]
        new_news = [n for n in other.news if n.link not in seen_links]
        new_articles = [a for a in other.articles
                        if a.link not in seen_links]
        new_notices = [nt for nt in other.notices
                       if nt.link not in seen_links]

        return CrawlResult(
            symbol=self.symbol,
            name=other.name or self.name,
            price=other.price or self.price,
            change=other.change or self.change,
            discussions=self.discussions + new_discussions,
            news=self.news + new_news,
            notices=self.notices + new_notices,
            articles=self.articles + new_articles,
            financial_data=other.financial_data or self.financial_data,
            crawled_at=other.crawled_at,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'CrawlResult':
        """从字典反序列化，兼容各字段类型"""
        discussions = [
            Discussion(**d) if isinstance(d, dict) else d
            for d in data.get('discussions', [])
        ]
        news = [
            News(**n) if isinstance(n, dict) else n
            for n in data.get('news', [])
        ]
        notices = [
            Notice(**{k: v for k, v in nt.items()
                      if k in Notice.__dataclass_fields__})
            if isinstance(nt, dict) else nt
            for nt in data.get('notices', [])
        ]
        articles = [
            Article(**a) if isinstance(a, dict) else a
            for a in data.get('articles', [])
        ]
        fd = data.get('financial_data')
        financial_data = FinancialData(**fd) if isinstance(fd, dict) else fd

        return cls(
            symbol=data.get('symbol', ''),
            name=data.get('name', ''),
            price=data.get('price', ''),
            change=data.get('change', ''),
            discussions=discussions,
            news=news,
            notices=notices,
            articles=articles,
            financial_data=financial_data,
            crawled_at=data.get('crawled_at', ''),
        )


@dataclass
class EvaluationResult:
    """评估输出"""
    total_score: int = 0
    scores: Dict[str, Dict] = field(default_factory=dict)
    sufficiency: str = "不足"
    need_more_crawl: bool = True
    crawl_suggestions: Dict = field(default_factory=dict)
    quality_assessment: Dict = field(default_factory=dict)
    financial_bonus: int = 0
    token_stats: Dict = field(default_factory=dict)

    @property
    def effective_score(self) -> int:
        return self.total_score + self.financial_bonus

    @property
    def is_sufficient(self) -> bool:
        return self.effective_score >= 150

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'EvaluationResult':
        return cls(**{k: v for k, v in data.items()
                      if k in cls.__dataclass_fields__})


@dataclass
class AnalysisResult:
    """分析输出"""
    symbol: str
    report: str = ""
    evaluation: Optional[EvaluationResult] = None
    model: str = ""
    template: str = "analysis"
    analyzed_at: str = ""

    def __post_init__(self):
        if not self.analyzed_at:
            self.analyzed_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'AnalysisResult':
        eval_data = data.get('evaluation')
        evaluation = EvaluationResult.from_dict(eval_data) if eval_data else None
        return cls(
            symbol=data.get('symbol', ''),
            report=data.get('report', ''),
            evaluation=evaluation,
            model=data.get('model', ''),
            template=data.get('template', 'analysis'),
            analyzed_at=data.get('analyzed_at', ''),
        )


# 评分标准常量
SCORING_CRITERIA = {
    "估值分析": {
        "25": "有完整估值模型/DCF分析",
        "15": "有估值讨论（PE/PB对比等）",
        "5": "仅有PE/PB数据",
        "0": "无估值相关内容",
    },
    "商业模式": {
        "25": "深度护城河分析，讨论可持续性",
        "15": "讨论竞争优势和行业地位",
        "5": "仅提及行业地位",
        "0": "无商业模式相关内容",
    },
    "财务质量": {
        "25": "完整财务分析（现金流、ROE趋势等）",
        "15": "部分财务指标讨论",
        "5": "仅有财务数据",
        "0": "无财务相关内容",
    },
    "竞争格局": {
        "25": "深度竞争分析，讨论行业格局演变",
        "15": "提及主要竞争对手和威胁",
        "5": "仅提及竞争",
        "0": "无竞争相关内容",
    },
    "管理层": {
        "25": "深度管理层分析（履历、战略、配置）",
        "15": "提及管理层变动或治理",
        "5": "仅提高管姓名",
        "0": "无管理层相关内容",
    },
    "风险因素": {
        "25": "系统性风险分析，多维度评估",
        "15": "提及主要风险点",
        "5": "仅有负面情绪表达",
        "0": "无风险相关内容",
    },
    "用户价值": {
        "25": "真实用户深度反馈（体验、忠诚度）",
        "15": "有用户评论或反馈",
        "5": "仅提用户数量",
        "0": "无用户相关内容",
    },
    "未来前景": {
        "25": "清晰完整增长逻辑",
        "15": "有增长方向和催化剂",
        "5": "仅提及前景",
        "0": "无前景相关内容",
    },
}
