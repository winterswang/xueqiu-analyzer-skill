# 雪球股票分析 Skill

> 输入股票代码，自动爬取雪球社区数据 → 多源财务数据 → AI 深度分析 → 生成结构化投资报告。

**版本**: v2.2.1 ｜ **分析模型**: GLM-5 ｜ **爬虫引擎**: Playwright

---

## 1. 项目概述

### 一句话定位

基于雪球社区数据的全自动股票投资分析工具，覆盖 A 股 / 港股 / 美股。

### 核心价值

| 能力 | 说明 |
|------|------|
| **社区舆情挖掘** | 爬取讨论/资讯/公告/文章，提取散户和机构观点 |
| **多维财务数据** | 雪球 API（PE/PB/ROE）+ AkShare（利润率/增速）+ 多年 ROIC |
| **智能迭代评估** | 每轮爬取后用 LLM 评估信息充分性，不足自动补充，最多 10 轮 |
| **结构化报告** | 8 大主题分析（估值/商业模式/财务/竞争/管理层/风险/用户/前景） |
| **自动分发** | Gist 上传 + 飞书通知，一键触达 |

### 适用场景

- "帮我分析下 TCOM 在雪球上的舆论和基本面"
- "看看 00700 最近的讨论都在说什么"
- "生成一份 PD 的投资分析报告"

---

## 2. 架构设计

### 整体架构

```
                          ┌──────────────────────┐
                          │   用户输入股票代码     │
                          │   如: TCOM, 00700    │
                          └──────────┬───────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
             ┌──────────┐    ┌────────────┐    ┌──────────┐
             │ 全流程分析 │    │ 智能迭代分析 │    │  单独爬取  │
             │run_analysis│   │smart_crawler│   │  crawler  │
             └─────┬─────┘    └──────┬──────┘    └─────┬────┘
                   │                │                  │
                   └────────┬───────┘                  │
                            ▼                          │
                   ┌─────────────────┐                 │
                   │ stock_crawler_v2 │ ◄───────────────┘
                   │  Playwright 爬虫  │
                   └────────┬────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
       ┌──────────┐  ┌──────────┐  ┌──────────────┐
       │ 讨论 Tab  │  │ 资讯 Tab  │  │ 公告 + 文章   │
       └──────────┘  └──────────┘  └──────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
       ┌──────────┐  ┌──────────┐  ┌──────────────┐
       │financial  │  │  data    │  │  llm_client  │
       │_fetcher   │  │_quality  │  │  统一 LLM     │
       └─────┬─────┘  └────┬─────┘  └──────┬───────┘
             │             │                │
             └──────┬──────┘                │
                    ▼                       ▼
             ┌──────────────────────────────────┐
             │         report_generator          │
             │  Prompt 1 评估 + Prompt 2 分析     │
             └──────────────┬───────────────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │   输出 + 分发     │
                   │ 本地文件 / Gist   │
                   │ / 飞书通知        │
                   └─────────────────┘
```

### 两条执行路径

#### 路径 A：全流程分析 (`run_analysis.py`)

```
run_analysis.py TCOM
  ├── 步骤 1: stock_crawler_v2 → 爬取讨论/资讯/公告/文章
  ├── 步骤 2: financial_fetcher → 财务数据（雪球API + AkShare）
  ├── 步骤 3: report_generator → GLM-5 生成报告
  └── 步骤 4: 保存 JSON 原始数据 + Markdown 报告
```

**特点**: 单次爬取、一次性分析，适合快速查看。

#### 路径 B：智能迭代分析 (`smart_crawler_v2.py`)

```
smart_crawler_v2.py TCOM
  ┌─────────────────────────────────────────┐
  │  第 N 轮迭代 (N = 1..10)                 │
  │  ├── crawl_round() → 爬取本轮数据        │
  │  ├── 合并去重（按类型 + link 去重）        │
  │  ├── build_evaluation_prompt() → 构建评估 │
  │  ├── call_llm() → Prompt 1 评估信息充分性  │
  │  └── 判断: 评分 >= 150?                  │
  │       ├── 是 → 进入分析                   │
  │       └── 否 → 继续下一轮（N < 10）        │
  ├─────────────────────────────────────────┤
  │  财务数据获取（第 1 轮之后）               │
  ├─────────────────────────────────────────┤
  │  Prompt 2 → 深度分析（8主题 + 投资建议）    │
  ├─────────────────────────────────────────┤
  │  输出: evaluation.md + report.md          │
  │  分发: Gist 上传 + 飞书通知               │
  └─────────────────────────────────────────┘
```

**特点**: 多轮迭代、信息充分性驱动、评分终止机制，分析质量更高。

### 模块角色

| 模块 | 文件 | 行数 | 角色 |
|------|------|------|------|
| **爬虫引擎** | `stock_crawler_v2.py` | ~1375 | Playwright 浏览器自动化：登录、Tab 切换、滚动加载、内容解析、去重 |
| **智能迭代** | `smart_crawler_v2.py` | ~1021 | 多轮评估驱动爬取、评分 ≥150 终止、Prompt 构建、Gist/飞书分发 |
| **LLM 客户端** | `llm_client.py` | ~168 | 统一 API Key 回退链、base_url 发现、异常链保留 |
| **报告生成** | `report_generator.py` | ~338 | GLM-5 调用封装 + 报告模板渲染 |
| **报告模板** | `report_template.py` | ~382 | Markdown 模板：表格格式化、Prompt 构建 |
| **财务数据** | `financial_fetcher.py` | ~302 | 雪球 API + AkShare + 多年 ROIC |
| **数据质量** | `data_quality_checker.py` | ~223 | 内容清洗、低质量过滤、统计 |
| **全流程** | `run_analysis.py` | ~164 | V1 兼容的单次全流程编排 |
| **配置** | `config.py` | ~70 | 路径/日志/目录管理 |
| **登录** | `login_xueqiu.py` | ~110 | 独立登录脚本，保存 cookies |

---

## 3. 数据流

### 完整数据流图

```
                           输入: 股票代码 (symbol)
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                  ▼                  ▼
             ┌────────────┐    ┌────────────┐    ┌──────────────┐
             │ 讨论 Tab    │    │ 资讯 Tab    │    │  公告 Tab     │
             │ .discussion │    │ .news       │    │  .notice      │
             └─────┬──────┘    └─────┬──────┘    └──────┬───────┘
                   │                │                   │
                   │  每项: {title, content, author, time, link}  │
                   └────────────────┼───────────────────┘
                                    │
                              ┌─────▼──────┐
                              │  去重合并    │ (seen_links: set)
                              │  按类型存储  │
                              └─────┬──────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
             ┌────────────┐ ┌────────────┐ ┌──────────────┐
             │ 雪球 API    │ │  AkShare   │ │ akshare       │
             │ PE/PB/ROE   │ │ 利润率/增速 │ │ 多年 ROIC     │
             │ 市值/52周   │ │            │ │              │
             └─────┬──────┘ └─────┬──────┘ └──────┬───────┘
                   └──────────────┼───────────────┘
                                  │
                          ┌───────▼───────┐
                          │ financial_data │
                          │ {pe_ttm, pb,  │
                          │  roe, roic,   │
                          │  gross_margin,│
                          │  net_margin,  │
                          │  revenue_growth,│
                          │  profit_growth,│
                          │  market_cap,  │
                          │  high52w,     │
                          │  low52w}      │
                          └───────┬───────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
             ┌──────────┐  ┌──────────┐  ┌──────────┐
             │ Prompt 1  │  │ Prompt 2 │  │  输出     │
             │ 信息评估   │  │ 深度分析  │  │          │
             └─────┬────┘  └─────┬────┘  └─────┬────┘
                   │             │              │
                   ▼             ▼              ▼
            ┌───────────┐ ┌───────────┐ ┌────────────┐
            │Evaluation  │ │ Analysis  │ │   分发      │
            │  Result    │ │  Report   │ │            │
            │{total_score│ │(Markdown) │ │ Gist 上传   │
            │ scores,    │ │           │ │ 飞书通知    │
            │ need_more, │ │           │ │            │
            │ suggestions│ │           │ │            │
            │}           │ │           │ │            │
            └───────────┘ └───────────┘ └────────────┘
```

### 数据节点说明

| 节点 | 输入 | 输出 | 格式 |
|------|------|------|------|
| **爬虫** | symbol (股票代码) | CrawlResult {discussions, news, notices, articles} | Python dataclass |
| **去重** | 原始爬取列表 | 去重后的累积列表 | `seen_links: set[str]` |
| **财务** | symbol + cookies | FinancialData {pe_ttm, pb, roe, ...} | Python dataclass |
| **Prompt 1** | 累积内容 + 评分标准 + 财务数据 | EvaluationResult {total_score, scores, need_more, ...} | JSON → dataclass |
| **Prompt 2** | 累积内容 + 财务数据 | Analysis Report | Markdown |
| **分发** | Markdown 文件路径 | Gist URL + 飞书消息 | HTTP + Feishu API |

---

## 4. 执行流

### 4.1 全流程分析 (`run_analysis.py`)

```bash
# 基础用法
python scripts/run_analysis.py TCOM

# 完整参数
python scripts/run_analysis.py 00700 \
  --max-discussions 50 \
  --max-news 50 \
  --max-articles 20 \
  --max-pages 10 \
  --output /path/to/output
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `symbol` | 必填 | 股票代码（TCOM / 00700 / SH600519） |
| `--max-discussions` | 30 | 最大讨论数 |
| `--max-news` | 30 | 最大资讯数 |
| `--max-articles` | 10 | 最大文章数 |
| `--max-pages` | 5 | 最大翻页数 |
| `--output` | `data/reports/` | 输出目录 |

**内部步骤**:

1. **爬取**: `XueqiuStockCrawlerV2(headless=True).crawl(symbol, ...)` → `CrawlResult`
2. **财务**: `FinancialDataFetcher().fetch(symbol, cookies)` → `FinancialData`
3. **报告**: `ReportGenerator().generate(stock_data)` → Markdown
4. **保存**: JSON 原始数据 + Markdown 报告到 `data/reports/`

### 4.2 智能迭代分析 (`smart_crawler_v2.py`)

```bash
# 基础用法（推荐）
python scripts/smart_crawler_v2.py TCOM

# 限制轮次
# 修改 smart_crawler_v2.py 中 MAX_ROUNDS_DEFAULT = 5
```

**执行流程（伪代码）**:

```python
symbol = "TCOM"

# 初始化
crawler = SmartCrawlerV2(symbol)
crawler.fetch_financial_data()           # 获取财务数据

# 迭代循环（最多 10 轮）
for round in range(1, MAX_ROUNDS + 1):
    # 1. 爬取本轮数据
    new_items = crawler.crawl_round(max_pages=3, max_articles=10)
    if sum(new_items.values()) == 0:
        break  # 无新数据，退出循环

    # 2. 评估信息充分性
    prompt = crawler.build_evaluation_prompt()
    result = crawler.call_llm(prompt, max_tokens=2000)
    eval_result = crawler.parse_evaluation(result)

    # 3. 输出统计
    crawler.print_round_stats(round, eval_result)

    # 4. 判断终止条件
    if eval_result.total_score >= SCORE_THRESHOLD:  # 150
        break

# 生成最终报告
report = crawler.generate_final_report()
# 上传 Gist + 飞书通知
```

**终止条件**:

| 条件 | 说明 |
|------|------|
| `total_score >= 150` | 信息充分，提前终止 |
| `round >= MAX_ROUNDS` | 达到最大轮次（10） |
| 本轮无新增数据 | 已无更多数据可爬 |

### 4.3 单独爬取（不分析）

```bash
python scripts/stock_crawler_v2.py 00700
```

仅爬取数据，生成 `data/reports/{symbol}_crawl_result_*.json`。

---

## 5. 核心模块详解

### 5.1 `llm_client.py` — 统一 LLM 客户端

| 功能 | 说明 |
|------|------|
| **API Key 回退链** | `BAILIAN_API_KEY` → `DASHSCOPE_API_KEY` → `OPENAI_API_KEY` → `~/.openclaw/openclaw.json` |
| **base_url 自动发现** | 从 `openclaw.json` 的 `models.providers` 中读取 |
| **异常链保留** | `LLMError` 继承自 `Exception`，用 `from e` 保留原始 traceback |
| **默认模型** | `glm-5` |

```python
from llm_client import LLMClient
client = LLMClient()
result = client.chat("分析腾讯的商业模式", max_tokens=8000)
```

### 5.2 `stock_crawler_v2.py` — Playwright 爬虫

| 功能 | 实现 |
|------|------|
| **登录** | JavaScript 弹窗拦截 + cookies 复用 |
| **页面切换** | Tab 切换（讨论/资讯/公告）→ 滚动加载 → 内容提取 |
| **数据解析** | `_parse_discussions()` / `_parse_news()` / `_parse_articles()` |
| **去重** | 按 link 去重，防止翻页重复 |
| **反检测** | stealth 脚本注入、随机延迟、headless 模式 |

返回值: `CrawlResult` dataclass，包含 `discussions`, `news`, `notices`, `articles`, `name`, `price`.

### 5.3 `financial_fetcher.py` — 财务数据获取

| 数据源 | 获取指标 |
|--------|----------|
| **雪球 API** | PE(TTM), PB, ROE, 市值, 52周高低 |
| **AkShare** | 毛利率, 净利率, 营收增速, 利润增速 |
| **akshare_service** | 5 年 ROIC 趋势 |

降级策略: 任一数据源不可用时跳过，输出中标注缺失。

### 5.4 `smart_crawler_v2.py` — 智能迭代引擎

核心类: `SmartCrawlerV2`

| 方法 | 功能 |
|------|------|
| `crawl_round()` | 执行一轮爬取，合并去重 |
| `fetch_financial_data()` | 获取财务数据 |
| `build_evaluation_prompt()` | 构建 Prompt 1 |
| `build_analysis_prompt()` | 构建 Prompt 2 |
| `call_llm()` | 调用 GLM-5 |
| `print_round_stats()` | 输出本轮统计 |
| `generate_final_report()` | 生成最终报告 |
| `_upload_gist()` | 上传 Gist |
| `_send_feishu()` | 飞书通知 |

### 5.5 `report_generator.py` — 报告生成

```python
from report_generator import ReportGenerator

gen = ReportGenerator()
report_md = gen.generate(stock_data)
```

内部调用 `report_template.py` 中定义的模板函数：
- `format_articles_table()` — 文章列表表格
- `format_discussions_table()` — 讨论列表表格
- `format_financial_table()` — 财务数据表格
- `format_key_data_table()` — 关键数据表格
- `format_reference_summary()` — 引用汇总
- `build_analysis_prompt()` — 构建分析 Prompt

---

## 6. 配置说明

### 必需配置

**API Key**（至少设置一个）:
```bash
export BAILIAN_API_KEY="your-key-here"
# 或
export DASHSCOPE_API_KEY="your-key-here"
# 或
export OPENAI_API_KEY="your-key-here"
```

**雪球登录凭据**:
- `config/xueqiu_credentials.yaml` — 用户名/密码
- `config/xueqiu_cookies.json` — 登录后自动保存，下次复用

### 可选配置

**`config/config.yaml`**:
```yaml
crawler:
  headless: true          # 无头模式
  scroll_delay: 2         # 滚动间隔（秒）
  page_timeout: 30        # 页面超时（秒）

llm:
  model: "glm-5"          # 模型名
  timeout: 1800           # API 超时（秒）
  max_tokens_evaluation: 2000
  max_tokens_analysis: 8000

smart_crawler:
  max_rounds: 10          # 最大迭代轮次
  score_threshold: 150    # 评分终止阈值
```

### 环境变量

| 变量 | 用途 | 优先级 |
|------|------|--------|
| `BAILIAN_API_KEY` | 百炼 API Key | 最高 |
| `DASHSCOPE_API_KEY` | DashScope API Key | 次高 |
| `OPENAI_API_KEY` | OpenAI API Key | 第三 |
| `~/.openclaw/openclaw.json` | OpenClaw 配置 fallback | 最低 |

---

## 7. 快速开始

### 7.1 安装依赖

```bash
cd /root/code/xueqiu-analyzer-skill
pip install -r requirements.txt
playwright install chromium
```

### 7.2 登录雪球（首次使用）

```bash
# 填写 config/xueqiu_credentials.yaml 后再运行
python scripts/login_xueqiu.py
```

成功后在 `config/` 下生成 `xueqiu_cookies.json`，后续自动复用。

### 7.3 运行分析

```bash
# 推荐：智能迭代分析
python scripts/smart_crawler_v2.py TCOM

# 或：全流程分析
python scripts/run_analysis.py 00700
```

### 7.4 查看结果

```
data/reports/
├── TCOM_evaluation_20260524_120000.md     # 评估报告（Prompt 1）
├── TCOM_smart_v2_report_20260524_120000.md # 分析报告（Prompt 2）
└── TCOM_smart_v2_data_20260524_120000.json # 完整原始数据
```

---

## 8. 输出文件

### 目录结构

```
data/reports/
├── {symbol}_smart_v2_report_{timestamp}.md     # 投资分析报告（Markdown）
├── {symbol}_evaluation_{timestamp}.md          # 信息充分性评估
├── {symbol}_smart_v2_data_{timestamp}.json     # 完整爬取数据 + 评估结果
├── {symbol}_report_{timestamp}.md              # V1 全流程报告
└── {symbol}_data_{timestamp}.json              # V1 原始数据
```

### 报告内容

**评估报告 (Prompt 1)**:

- 8 个主题评分（满分 25 × 8 = 200）
- 每项评分理由 + 原文证据
- 信息来源可靠性
- 内容覆盖分析（优势/缺口领域）
- Token 分项统计
- 爬取建议

**分析报告 (Prompt 2)**:

- 执行摘要（估值判断/投资建议/核心逻辑/关键风险）
- 8 个主题深度分析（带原文引用）
- 投资决策（入场条件/跟踪指标/退出条件）

---

## 9. OpenClaw Agent 使用指引

> **这是专门写给 OpenClaw AI Agent 的参考手册。当用户在飞书或任何 IM 中对你说要分析某只股票时，参考本节执行。**

### 触发关键词

当用户消息中包含以下模式时，自动触发分析：

| 模式 | 示例 | 动作 |
|------|------|------|
| `分析 {symbol}` | "分析 TCOM"、"分析下00700" | 执行智能迭代分析 |
| `雪球分析 {symbol}` | "雪球分析 PD"、"帮我看看雪球上腾讯" | 同上 |
| `{symbol} 分析` | "TCOM 分析一下" | 同上 |
| `{symbol} 雪球` | "00700 雪球" | 同上 |

symbol 支持格式: `TCOM`, `PDD`, `00700`, `SH600519`, `SZ300760`

### 调用方式

```bash
# 推荐：智能迭代分析（多轮评估，质量更高）
cd /root/code/xueqiu-analyzer-skill && python scripts/smart_crawler_v2.py {symbol}

# 快速：全流程分析（单次爬取，速度更快）
cd /root/code/xueqiu-analyzer-skill && python scripts/run_analysis.py {symbol}

# 仅爬数据（不分析）
cd /root/code/xueqiu-analyzer-skill && python scripts/stock_crawler_v2.py {symbol}
```

### 前置条件检查

执行分析前确认：

- [ ] `config/xueqiu_cookies.json` 存在且未过期
- [ ] `BAILIAN_API_KEY` 或 `DASHSCOPE_API_KEY` 环境变量已设置
- [ ] `playwright` 和 `chromium` 已安装
- [ ] 网络可访问 `xueqiu.com` 和 `dashscope.aliyuncs.com`

### 典型使用场景

**场景 1: 用户要求分析一只股票**

```
用户: "帮我分析下 TCOM"

Agent 动作:
1. 确认 symbol 格式: TCOM, 00700, PDD 等
2. 执行: cd /root/code/xueqiu-analyzer-skill && python scripts/smart_crawler_v2.py TCOM
3. 等待完成（可能需要 2-5 分钟，取决于爬取轮次）
4. 读取生成的报告文件: data/reports/TCOM_smart_v2_report_*.md
5. 提取核心摘要回复用户，附上完整报告路径
```

**场景 2: 快速了解某只股票的雪球舆论**

```
用户: "00700 最近雪球上都在讨论什么"

Agent 动作:
1. 执行爬虫: python scripts/stock_crawler_v2.py 00700
2. 读取 data/reports/00700_crawl_result_*.json
3. 从 discussions/ news 中提取热门主题
4. 以摘要形式回复
```

**场景 3: 批量分析多只股票**

```
用户: "帮我分析 TCOM PDD 00700 这三只"

Agent 动作:
1. 识别 3 个 symbol
2. 依次执行（注意爬虫浏览器需顺序执行，不能并发）
3. 汇总 3 份报告的核心发现
```

### 执行注意事项

1. **顺序执行**: `stock_crawler_v2.py` 使用 Playwright 浏览器，同一时间只能运行一个实例
2. **超时预期**: 智能迭代分析最长可能需要 5 分钟（10 轮 × 30s 爬虫等待 + LLM 调用）
3. **cookies 过期**: 若分析失败并提示登录，需执行 `python scripts/login_xueqiu.py` 刷新
4. **报告路径**: 分析完成后用 `data/reports/{symbol}_smart_v2_report_*` 找到最新报告
5. **不要重复分析**: 如果用户刚刚分析过同一只股票，直接引用已有报告，不要重新执行

### 错误处理

| 错误 | 原因 | 解决 |
|------|------|------|
| `LLMError: 未配置 API Key` | 环境变量缺失 | 提示设置 `BAILIAN_API_KEY` |
| `登录失败` | cookies 过期 | 执行 `login_xueqiu.py` |
| `Playwright: Executable doesn't exist` | Chromium 未安装 | 执行 `playwright install chromium` |
| 爬取数据为空 | 股票代码错误 | 确认 symbol 格式，A 股用 `SH/SZ` 前缀 |

---

## 10. 项目文件清单

```
xueqiu-analyzer-skill/
├── SKILL.md                       # Skill 元数据 + 触发规则
├── README.md                      # 本文档（架构 + 使用指南）
├── PROJECT_LOG.md                 # 项目跟踪日志（ADR / Bug / 技术债务）
├── CODE_REVIEW.md                 # 最近一次代码审查记录
├── requirements.txt               # Python 依赖
├── config/
│   ├── config.yaml                # 主配置文件
│   ├── target_users.yaml          # 飞书通知目标用户
│   ├── xueqiu_credentials.yaml    # 雪球登录凭据
│   └── xueqiu_cookies.json        # 登录 cookies（自动生成）
├── scripts/
│   ├── smart_crawler_v2.py        # ⭐ 智能迭代爬取主程序
│   ├── stock_crawler_v2.py        # Playwright 爬虫核心
│   ├── llm_client.py              # 统一 LLM 客户端
│   ├── report_generator.py        # 报告生成器
│   ├── report_template.py         # 报告 Markdown 模板
│   ├── financial_fetcher.py       # 财务数据获取
│   ├── data_quality_checker.py    # 数据质量检查
│   ├── run_analysis.py            # V1 全流程入口
│   ├── analyzer.py                # 独立分析器（V1 兼容）
│   ├── config.py                  # 配置管理
│   ├── login_xueqiu.py            # 雪球登录脚本（CLI 独立运行）
│   ├── debug_news_notices.py      # 调试工具（CLI 独立运行）
│   ├── get_username.py            # 用户信息查询（CLI 独立运行）
│   ├── refresh_cookies.py         # Cookies 刷新（CLI 独立运行）
│   ├── llm_config.py              # LLM 配置加载器（⚠️ 未被引用，待集成）
│   └── update_template.py         # 模板更新工具（CLI 独立运行）
└── data/
    └── reports/                   # 分析报告输出目录
```

## 版本历史

| 版本 | 日期 | 核心变更 |
|------|------|----------|
| v1.0.0 | 2026-03-05 | 基础爬虫 + GLM-5 分析 |
| v2.0.0 | 2026-03-06 | Playwright + 双 Prompt + 财务数据 |
| v2.1.0 | 2026-03-07 | 10 轮迭代 + 评分终止 + Token 统计 |
| v2.2.0 | 2026-03-08 | 多年 ROIC + 财务加分项 |
| v2.2.1 | 2026-05-24 | 代码审查修复：LLM 统一、废弃代码清理、异常链保留 |

## License

MIT
