# xueqiu-analyzer V3 — 技术方案

> 版本：3.0 | 日期：2026-05-20

---

## 一、架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                     CLI (xueqiu)                            │
│  analyze | crawl | evaluate | cookies                      │
└──────────┬──────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────┐
│   Orchestrator      │  编排器：爬取→评估→补充→分析循环
│   (orchestrator.py) │  只管流程，不含业务逻辑
└──┬──────┬───────┬───┘
   │      │       │
   ▼      ▼       ▼
┌──────┐┌──────┐┌──────┐
│Crawl ││Evalu ││Analy │    三大核心模块，互不依赖
│  er  ││  ator││  zer │    输入/输出都是标准 JSON
└──┬───┘└──┬───┘└──┬───┘
   │       │       │
   ▼       ▼       ▼
┌──────────────────────────┐
│      Shared Layer        │
│  llm_client / config /   │
│  prompts / models /      │
│  financial_fetcher       │
└──────────────────────────┘
```

**核心设计原则：数据解耦**

```
Crawler ──→ JSON 文件 ──→ Evaluator ──→ JSON 文件 ──→ Analyzer
                                  │                        │
                                  └── 可独立运行 ──────────┘
```

每个模块从文件读取输入、向文件写入输出。模块之间零直接调用。

---

## 二、目录结构

```
xueqiu-analyzer/
├── cli.py                    # 统一 CLI 入口
├── orchestrator.py           # 编排器（迭代循环）
├── crawler.py                # 雪球爬虫
├── evaluator.py              # 信息充分性评估
├── analyzer.py               # 深度分析
├── financial_fetcher.py      # 财务数据获取
├── llm_client.py             # LLM 调用客户端
├── config.py                 # 配置加载
├── models.py                 # 数据模型 (dataclass)
├── cookie_manager.py         # Cookie 管理
├── notifier.py               # Gist + 飞书通知
├── prompts/                  # Prompt 模板目录
│   ├── evaluation.md         # Prompt 1: 信息充分性评估
│   └── analysis.md           # Prompt 2: 深度分析
├── config/
│   └── config.yaml           # 主配置文件
├── tests/
│   ├── test_evaluator.py     # 评估逻辑测试
│   ├── test_analyzer.py      # 分析逻辑测试
│   ├── test_models.py        # 数据模型测试
│   └── fixtures/             # 测试数据
│       └── sample_data.json
├── .gitignore                # 排除 cookies/data/credentials
├── requirements.txt
├── REQUIREMENTS.md           # 需求文档
├── TECHNICAL.md              # 本文件
└── README.md
```

---

## 三、模块详细设计

### 3.1 models.py — 数据模型

统一的数据模型，所有模块共用：

```python
@dataclass
class Discussion:
    author: str
    content: str
    time: str
    link: str = ""
    comments: List[str] = field(default_factory=list)

@dataclass
class News:
    title: str
    content: str
    time: str
    source: str = ""
    link: str = ""

@dataclass
class Notice:
    title: str
    link: str
    time: str = ""
    content: str = ""
    pdf_link: str = ""

@dataclass
class Article:
    title: str
    author: str
    content: str
    time: str
    link: str = ""

@dataclass
class FinancialData:
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

@dataclass
class CrawlResult:
    """爬虫输出 — 标准数据格式"""
    symbol: str
    name: str = ""
    price: str = ""
    change: str = ""
    discussions: List[Discussion] = field(default_factory=list)
    news: List[News] = field(default_factory=list)
    notices: List[Notice] = field(default_factory=list)
    articles: List[Article] = field(default_factory=list)
    financial_data: Optional[FinancialData] = None
    crawled_at: str = ""  # ISO 时间戳

@dataclass
class EvaluationResult:
    """评估输出"""
    total_score: int
    scores: Dict[str, Dict]  # {主题: {score, reason, evidence}}
    sufficiency: str  # "充分" | "基本充分" | "不足"
    need_more_crawl: bool
    crawl_suggestions: Dict
    quality_assessment: Dict
    financial_bonus: int = 0
    token_stats: Dict = field(default_factory=dict)

@dataclass
class AnalysisResult:
    """分析输出"""
    symbol: str
    report: str  # Markdown 报告
    evaluation: Optional[EvaluationResult] = None
```

### 3.2 config.py — 配置加载

```yaml
# config/config.yaml
llm:
  base_url: "https://ark.cn-beijing.volces.com/api/coding/v3"
  model: "doubao-seed-2.0-pro"
  api_key: "${ARK_API_KEY}"
  max_tokens: 8000
  temperature: 0.7

crawler:
  headless: true
  delay_min: 3
  delay_max: 8
  max_pages: 10
  timeout: 30000

evaluator:
  score_threshold: 150
  max_rounds: 10

analysis:
  max_discussions: 30
  max_news: 30
  max_articles: 10

storage:
  data_dir: "data"
  logs_dir: "logs"

notify:
  gist: true
  feishu: true
  feishu_target: "${FEISHU_TARGET_USER}"
```

加载逻辑：环境变量 > config.yaml > openclaw.json fallback

### 3.3 llm_client.py — LLM 客户端

```python
class LLMClient:
    """统一 LLM 调用客户端"""
    
    def __init__(self, config: dict = None):
        self.config = config or get_llm_config()
    
    def chat(self, messages: List[Dict], max_tokens: int = None, 
             temperature: float = None) -> str:
        """通用聊天接口"""
        ...
    
    def evaluate(self, prompt: str) -> str:
        """评估专用（使用 evaluation system prompt）"""
        ...
    
    def analyze(self, prompt: str) -> str:
        """分析专用（使用 analysis system prompt）"""
        ...
    
    def simple_chat(self, prompt: str, max_tokens: int = 4000) -> str:
        """简单对话（无 system prompt）"""
        ...
```

### 3.4 prompts/ — Prompt 模板

使用 Markdown 文件 + Jinja2 变量替换：

**prompts/evaluation.md**
```markdown
你是一位资深价值投资分析师，现在需要评估当前收集的信息是否足够支撑一份高质量的投资分析报告。

# 评估目标

作为价值投资者，我需要回答以下8个核心问题：

{% for topic, criteria in scoring_criteria %}
{{ loop.index }}. {{ topic }}
{% endfor %}

# 评分标准

{% for topic, criteria in scoring_criteria %}
## {{ topic }}
| 25分 | 15分 | 5分 | 0分 |
|------|------|-----|-----|
| {{ criteria["25"] }} | {{ criteria["15"] }} | {{ criteria["5"] }} | {{ criteria["0"] }} |
{% endfor %}

# 爬取内容

{{ content }}

# 输出格式

请以 JSON 格式输出...
```

**加载方式**：
```python
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader('prompts/'))

def load_prompt(name: str, **kwargs) -> str:
    template = env.get_template(f'{name}.md')
    return template.render(**kwargs)
```

### 3.5 crawler.py — 爬虫

从 V2 的 `stock_crawler_v2.py` 精简重构，职责单一：

```python
class XueqiuCrawler:
    """雪球数据爬虫 — 只管爬，输出标准 JSON"""
    
    def __init__(self, config: dict = None):
        ...
    
    def crawl(self, symbol: str, max_pages: int = 5, 
              max_articles: int = 10) -> CrawlResult:
        """爬取股票数据，返回标准 CrawlResult"""
        ...
    
    def save(self, result: CrawlResult, path: str):
        """保存为 JSON 文件"""
        ...
    
    @classmethod
    def load(cls, path: str) -> CrawlResult:
        """从 JSON 文件加载"""
        ...
```

**与 V2 的区别**：
- 去掉所有 LLM 调用代码
- 去掉评估/分析逻辑
- `crawl()` 返回 `CrawlResult` 而不是直接送 LLM
- 增加 `save()` / `load()` 序列化方法

### 3.6 evaluator.py — 评估器

```python
class Evaluator:
    """信息充分性评估器"""
    
    def __init__(self, llm: LLMClient = None, config: dict = None):
        self.llm = llm or LLMClient()
        self.config = config or get_config()
    
    def evaluate(self, data: CrawlResult) -> EvaluationResult:
        """评估数据充分性"""
        prompt = load_prompt('evaluation', 
            content=self._format_content(data),
            scoring_criteria=SCORING_CRITERIA,
            financial_data=data.financial_data)
        response = self.llm.evaluate(prompt)
        return self._parse_result(response)
    
    def _parse_result(self, response: str) -> EvaluationResult:
        """解析 LLM 返回的评估结果"""
        # 提取 JSON 块，反序列化，构建 EvaluationResult
        ...
    
    def _format_content(self, data: CrawlResult) -> str:
        """格式化爬取内容为 Prompt 输入"""
        ...
```

**关键改进**：`_parse_result()` 有完整单元测试，覆盖各种 LLM 输出格式（JSON块、Markdown代码块、纯文本等）。

### 3.7 analyzer.py — 分析器

```python
class Analyzer:
    """深度投资分析器"""
    
    def __init__(self, llm: LLMClient = None, config: dict = None,
                 template: str = 'analysis'):
        self.llm = llm or LLMClient()
        self.template = template
    
    def analyze(self, data: CrawlResult, 
                evaluation: EvaluationResult = None) -> str:
        """生成深度分析报告"""
        prompt = load_prompt(self.template,
            content=self._format_content(data),
            evaluation=evaluation,
            financial_data=data.financial_data)
        return self.llm.analyze(prompt)
```

**关键改进**：
- 支持换模板：`template='conservative'` 或 `template='growth'`
- 不依赖爬虫，直接输入 `CrawlResult`

### 3.8 orchestrator.py — 编排器

```python
class Orchestrator:
    """迭代爬取编排器 — 只管流程，不含业务逻辑"""
    
    def __init__(self, config: dict = None):
        self.config = config or get_config()
        self.crawler = XueqiuCrawler(self.config.get('crawler', {}))
        self.evaluator = Evaluator(config=self.config)
        self.analyzer = Analyzer(config=self.config)
        self.notifier = Notifier(self.config.get('notify', {}))
    
    def run(self, symbol: str, max_rounds: int = None,
            data_path: str = None) -> AnalysisResult:
        """完整流程：爬取→评估→补充→分析"""
        
        # 1. 加载或爬取数据
        if data_path:
            crawl_result = XueqiuCrawler.load(data_path)
        else:
            crawl_result = self._iterative_crawl(symbol, max_rounds)
        
        # 2. 评估
        evaluation = self.evaluator.evaluate(crawl_result)
        
        # 3. 分析
        report = self.analyzer.analyze(crawl_result, evaluation)
        
        # 4. 保存 + 通知
        self._save_results(symbol, crawl_result, evaluation, report)
        self.notifier.send(symbol, evaluation, report)
        
        return AnalysisResult(symbol=symbol, report=report, 
                              evaluation=evaluation)
    
    def _iterative_crawl(self, symbol: str, 
                         max_rounds: int) -> CrawlResult:
        """迭代爬取循环"""
        threshold = self.config['evaluator']['score_threshold']
        result = CrawlResult(symbol=symbol)
        
        for round_num in range(1, max_rounds + 1):
            pages = min(5 + round_num, 10)
            articles = min(10 + round_num * 3, 30)
            new = self.crawler.crawl(symbol, max_pages=pages,
                                     max_articles=articles)
            result = self._merge(result, new)
            
            eval_result = self.evaluator.evaluate(result)
            if eval_result.total_score + eval_result.financial_bonus >= threshold:
                break
        
        return result
```

**`run()` 不超过 50 行**，每步都是委托调用。

### 3.9 cli.py — 统一 CLI

```python
@click.group()
def cli():
    """雪球股票分析工具 V3"""
    pass

@cli.command()
@click.argument('symbol')
@click.option('--max-rounds', default=10)
@click.option('--data', help='已有数据文件路径（跳过爬取）')
@click.option('--template', default='analysis', help='分析模板')
def analyze(symbol, max_rounds, data, template):
    """完整分析流程"""
    ...

@cli.command()
@click.argument('symbol')
@click.option('--output', '-o', help='输出文件路径')
def crawl(symbol, output):
    """只爬取数据"""
    ...

@cli.command()
@click.option('--data', required=True, help='数据文件路径')
def evaluate(data):
    """只评估数据充分性"""
    ...

@cli.command()
@click.option('--import-file', help='导入 cookies JSON')
@click.option('--check', is_flag=True, help='检查 cookies 状态')
def cookies(import_file, check):
    """管理登录状态"""
    ...
```

---

## 四、数据流

### 4.1 完整分析流程

```
$ xueqiu analyze 00700

cli.py → orchestrator.run("00700")
  │
  ├── crawler.crawl("00700")     → CrawlResult
  │   └── save: data/00700_20260520.json
  │
  ├── evaluator.evaluate(result) → EvaluationResult (score=90)
  │   └── score < 150, 继续爬取
  │
  ├── crawler.crawl("00700", more pages)  → merge to CrawlResult
  │   └── evaluator.evaluate(result)      → EvaluationResult (score=155)
  │       └── score >= 150, 进入分析
  │
  ├── analyzer.analyze(result, eval) → report.md
  │
  ├── save: data/00700_evaluation_20260520.md
  │       data/00700_report_20260520.md
  │
  └── notifier.send() → Gist + 飞书
```

### 4.2 独立爬取

```
$ xueqiu crawl 00700 -o data/00700.json

cli.py → crawler.crawl("00700") → save("data/00700.json")
```

### 4.3 用已有数据重新分析

```
$ xueqiu analyze --data data/00700.json --template conservative

cli.py → CrawlResult.load("data/00700.json")
       → evaluator.evaluate(result)
       → analyzer.analyze(result, eval, template="conservative")
```

---

## 五、测试策略

| 测试类型 | 覆盖范围 | 工具 |
|----------|----------|------|
| 单元测试 | `evaluator._parse_result()` | pytest |
| 单元测试 | `analyzer._format_content()` | pytest |
| 单元测试 | `models` 序列化/反序列化 | pytest |
| 单元测试 | `config` 加载和优先级 | pytest |
| 集成测试 | 完整流程（mock LLM） | pytest + fixtures |
| 集成测试 | LLM 调用（真实） | 手动触发 |

**核心测试用例**：

```python
# test_evaluator.py

def test_parse_evaluation_result_json_block():
    """LLM 返回 ```json ... ``` 格式"""
    ...

def test_parse_evaluation_result_plain_json():
    """LLM 返回纯 JSON"""
    ...

def test_parse_evaluation_result_malformed():
    """LLM 返回格式异常"""
    ...

def test_parse_evaluation_result_missing_field():
    """LLM 返回缺少字段"""
    ...

def test_evaluation_score_calculation():
    """评分计算逻辑"""
    ...

def test_sufficiency_threshold():
    """充分性判定"""
    ...
```

---

## 六、迁移计划

### 从 V2 迁移

| V2 文件 | V3 对应 | 处理 |
|---------|---------|------|
| stock_crawler_v2.py (1447行) | crawler.py | 精简重构，去掉 LLM/评估/分析代码 |
| smart_crawler_v2.py (1002行) | orchestrator.py + evaluator.py + analyzer.py | 拆分为3个模块 |
| financial_fetcher.py (301行) | financial_fetcher.py | 保留，小改接口 |
| llm_config.py (162行) | llm_client.py + config.py | 合并升级 |
| refresh_cookies.py (244行) | cookie_manager.py | 精简 |
| report_template.py (381行) | prompts/*.md | 外部化为 Markdown 模板 |
| report_generator.py (342行) | analyzer.py | 重写 |
| run_analysis.py (164行) | 删除 | 被 CLI 替代 |
| analyzer.py (149行) | 删除 | 被 CLI 替代 |
| data_quality_checker.py (222行) | crawler.py 内部 | 简化后内联 |
| archive/* | 删除 | 死代码 |

### 估计代码量

| 模块 | 预估行数 |
|------|----------|
| models.py | ~100 |
| config.py | ~80 |
| llm_client.py | ~120 |
| crawler.py | ~800 |
| evaluator.py | ~250 |
| analyzer.py | ~150 |
| orchestrator.py | ~120 |
| cli.py | ~100 |
| cookie_manager.py | ~150 |
| notifier.py | ~80 |
| financial_fetcher.py | ~250 |
| prompts/*.md | ~300 |
| tests/ | ~300 |
| **合计** | ~2,800 |

V2 是 4,781 行（含死代码），V3 约 2,800 行，**代码量减少 40%，但功能更强、架构更清晰。**

---

## 七、依赖

```
# requirements.txt
playwright>=1.40.0
pyyaml>=6.0
requests>=2.28.0
click>=8.0
jinja2>=3.0
```

新增 `click`（CLI）和 `jinja2`（Prompt 模板），去掉 `urllib.request` 直接调用（用 `requests` 统一）。
