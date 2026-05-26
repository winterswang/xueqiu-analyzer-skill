# 雪球公司分析 Skill V3

> 输入股票代码，自动爬取雪球社区数据 → 多源财务数据 → AI 深度分析 → 生成结构化投资报告。

**版本**: v3.1.0 ｜ **爬虫引擎**: Playwright ｜ **分析模型**: DeepSeek

---

## 1. 快速开始

### 安装

```bash
cd /root/code/xueqiu-analyzer-skill
pip install -r requirements.txt
playwright install chromium
```

### 新鲜 cookies（首次使用）

```bash
.venv/bin/python -m xueqiu_analyzer.cli cookies
```

### 爬取 + 分析

```bash
# 完整分析：爬取 → 质检 → LLM评估 → 深度分析报告
.venv/bin/python -m xueqiu_analyzer.cli analyze TCOM

# 只爬数据（时间维度自动停止）
.venv/bin/python -m xueqiu_analyzer.cli crawl TCOM

# 自定义翻页和富化
.venv/bin/python -m xueqiu_analyzer.cli crawl TCOM --max-pages 50 --max-articles 30 --timeout 1200

# 仅评估已有数据
.venv/bin/python -m xueqiu_analyzer.cli evaluate data/TCOM_data_20260526.json
```

### CLI 参数

| 参数 | 默认 | 说明 |
|------|:---:|------|
| `--max-pages` | 10 | 最大翻页数（兜底，实际由时间停止控制） |
| `--max-articles` | 20 | 详情富化上限（打开详情页补正文/评论） |
| `--timeout` | 1200 | 总超时秒数 |
| `--template` | analysis | 报告模板（analysis / conservative） |

---

## 2. 输出示例

```
爬取完成: 88 讨论, 11 专栏, 10 资讯, 10 公告

data/
├── AAPL_data_20260526_224432.json      # 完整原始数据
├── AAPL_evaluation_20260526_*.md       # 信息充分性评估
└── AAPL_report_20260526_*.md           # 投资分析报告
```

---

## 3. 架构设计

```
┌──────────────────────────────────────────────────────┐
│                   xueqiu-analyzer V3                  │
├──────────────────────────────────────────────────────┤
│                                                      │
│  CLI → Orchestrator                                  │
│          │                                           │
│          ├─ Crawler (Playwright)                     │
│          │    ├─ discussions · 时间停止               │
│          │    ├─ articles (专栏) · 自动分离 + 详情富化 │
│          │    ├─ news · 时间停止                      │
│          │    └─ notices · 首页 20 条                 │
│          │                                           │
│          ├─ FinancialFetcher                         │
│          │    ├─ 雪球 API → PE/PB/市值/52周           │
│          │    └─ financial-sdk → ROE/ROIC/利润率/增速  │
│          │                                           │
│          ├─ QualityChecker (Layer 1: 硬指标)          │
│          │    └─ 内容完整率 + 健康分 → <70 定向重爬    │
│          │                                           │
│          ├─ Evaluator (Layer 2: LLM 评分)            │
│          │    └─ 8维度 × 25分 → ≥150 进入分析         │
│          │                                           │
│          └─ Analyzer (LLM 深度分析)                   │
│               └─ 执行摘要 + 8主题 + 投资决策           │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### 核心模块

| 模块 | 路径 | 职责 |
|------|------|------|
| `crawler.py` | `src/xueqiu_analyzer/` | Playwright 爬虫：登录、Tab切换、分页、JS结构化提取 |
| `models.py` | 同上 | 数据模型：Discussion/Article/News/Notice/FinancialData |
| `quality.py` | 同上 | Layer 1 硬指标：内容完整率、健康分、定向重爬建议 |
| `evaluator.py` | 同上 | Layer 2 LLM 评分：8维度充分性评估 |
| `analyzer.py` | 同上 | LLM 深度分析：执行摘要 + 8主题 + 投资决策 |
| `financial_fetcher.py` | 同上 | 财务数据：雪球API + financial-sdk CLI |
| `cli.py` | 同上 | CLI 入口：analyze/crawl/evaluate/reanalyze/cookies |
| `orchestrator.py` | 同上 | 迭代编排：crawl→quality→evaluate→analyze |

---

## 4. 爬取机制（V3.1）

### 时间维度停止

不再按固定页数/条数停止，而是按**发布时间**判断：

1. 每页解析 `.timeline__item` 中的时间字段
2. 当一页出现 ≥3 条"昨天"或日期格式（`05-24` / `2026-05-24`）→ 停止翻页
3. 讨论 tab 固定「最新」排序，确保按时间线获取今天全部内容

### 翻页机制

- 雪球使用传统页码分页（`[1] [2] ... [下一页]`），非无限滚动
- 爬虫点击「下一页」逐页翻页，每页解析后立即存入（DOM 换页失效）
- 兜底：最多 `--max-pages` 页，或连续 3 页无新内容时停止

### 专栏文章分离

从讨论页自动分离专栏文章：

```
检测 h3 含「专栏」→  正文 ≥80字 & 不以「回复」开头 → articles[]
                     正文 <80字 或 以「回复」开头  → discussions[]（清理前缀）
```

### 详情富化

- 专栏文章优先：先 articles 后 discussions
- 打开详情页提取：完整正文（专栏 ≤5000字、讨论 ≤2000字）、评论列表（最多 30 条）

### 公告

仅取第一页 10-20 条，不翻页（公告格式与时间停止不兼容）。

### 解析方式

使用 `item.evaluate(JS)` 结构化提取，替代旧的 `inner_text() + regex`：

| 提取项 | 方法 |
|--------|------|
| Author | `<a>` 标签提取，过滤"收起/展开/$股票名/时间串/icon" |
| Time | 时间链接 regex |
| Content | 优先 `.article__bd__detail` → 回退 `innerText` 减 chrome |
| Comments | 详情页 `.comment-item` → `innerText` |
| 去重 | 正文前 50 字符签名 |

### 爬取性能

| 股票 | 讨论 | 专栏 | 资讯 | 公告 | 耗时 |
|------|:---:|:---:|:---:|:---:|:---:|
| 🍎 AAPL | ~90 | ~10 | ~10 | ~10 | ~4 min |
| 🐧 00700 | ~440 | ~20 | ~10 | ~10 | ~6 min |
| 🍶 茅台 | ~490 | ~13 | ~10 | ~10 | ~6 min |

---

## 5. 数据模型

### CrawlResult

| 字段 | 类型 | 说明 |
|------|------|------|
| symbol | str | 股票代码 |
| name | str | 雪球显示名 |
| price | str | 当前价 |
| discussions | list[Discussion] | 讨论帖 |
| articles | list[Article] | 专栏文章 |
| news | list[News] | 资讯 |
| notices | list[Notice] | 公告 |
| financial_data | FinancialData | 财务指标 |
| crawled_at | ISO timestamp | 爬取时间 |

### Discussion

| 字段 | 说明 |
|------|------|
| author | 作者（JS 结构化提取） |
| content | 正文（≤2000 字符） |
| time | 发布时间 |
| link | 详情页链接 |
| comments | list[str] · 评论区（≤30 条） |
| comment_count / forward_count / like_count | 互动数据 |

### Article

| 字段 | 说明 |
|------|------|
| title | 专栏标题（如「专栏腾讯的熵增困境...」） |
| author | 作者 |
| content | 全文（≤5000 字符，从详情页提取） |
| time | 发布时间 |
| link | 文章链接 |
| article_id | 雪球文章 ID |
| comments / comment_count / like_count | 互动数据 |

### News

| 字段 | 说明 |
|------|------|
| title | 标题（timeline 拆出） |
| content | 正文（详情页提取，≤5000 字符） |
| time | 发布时间 |
| source | 来源（新闻/公告/研报/媒体） |
| link | 外部链接 |

### Notice

| 字段 | 说明 |
|------|------|
| title | 公告标题 |
| content | SEC→结构化摘要；雪球内部→正文 |
| link | SEC EDGAR 或雪球详情页 |
| pdf_link | PDF 下载链接 |
| notice_type | 公告类型 |

### FinancialData

| 字段 | 来源 | 说明 |
|------|------|------|
| pe_ttm | 雪球 API | PE(TTM) |
| pb | 雪球 API | 市净率 |
| roe | financial-sdk (雪球 fallback) | ROE |
| gross_margin | financial-sdk | 毛利率 |
| net_margin | financial-sdk | 净利率 |
| revenue_growth | financial-sdk | 营收增速 YoY |
| profit_growth | financial-sdk | 利润增速 YoY |
| market_cap | 雪球 API | 总市值 |
| low52w / high52w | 雪球 API | 52周区间 |
| yearly_roic | (暂空) | 多年 ROIC 趋势 |

---

## 6. 迭代分析流程

```
Round 1
  ├─ crawl (pages=5, articles=10)
  ├─ QualityChecker → 健康分
  │   ├─ < 70 → 定向重爬
  │   └─ ≥ 70 → Evaluator (LLM 8维度评分)
  │       ├─ ≥ 150 → ✅ 进入分析
  │       ├─ < 150 & round < max → 🔄 继续
  │       └─ round = max → ⚠️ 强制进入
```

### 质量报告（Layer 1 硬指标）

```
📊 爬取数据质量报告
健康分: 91/100 ✅

内容完整率:
| 类别 | 总数 | 有内容 | 完整率 |
|------|:---:|:---:|:---:|
| 讨论 | 88  | 88  | 100% ✅
| 专栏 | 11  | 11  | 100% ✅
| 资讯 | 10  | 10  | 100% ✅
| 公告 | 10  | 10  | 100% ✅

财务数据: 7/7 100% ✅
```

### LLM 评分（Layer 2）

| 主题 | 满分 | 评估内容 |
|------|:---:|----------|
| 估值分析 | 25 | DCF/相对估值/历史对比 |
| 商业模式 | 25 | 护城河/可持续性 |
| 财务质量 | 25 | 利润率/ROE/FCF/增速 |
| 竞争格局 | 25 | 竞对/市场份额/壁垒 |
| 管理层 | 25 | 履历/战略/资本配置 |
| 风险因素 | 25 | 风险识别与量化 |
| 用户价值 | 25 | 真实用户反馈/NPS |
| 未来前景 | 25 | 增长逻辑/第二曲线 |

总分 ≥150 进入最终分析。

---

## 7. 配置

`src/xueqiu_analyzer/config.yaml`：

```yaml
llm:
  model: deepseek-chat
  base_url: https://api.deepseek.com

crawler:
  headless: true
  delay_min: 3
  delay_max: 8

evaluator:
  score_threshold: 150
  max_rounds: 3

quality:
  health_threshold: 70
  news_min_ratio: 0.5
  notice_min_ratio: 0.3
  min_content_length: 20
```

**API Key 优先级**：
1. 环境变量 `DEEPSEEK_API_KEY`
2. `config/config.yaml` 中的占位符（自动替换）
3. OpenClaw provider 配置

---

## 8. 项目结构

```
xueqiu-analyzer-skill/
├── SKILL.md                     # Skill 元数据 + 完整文档
├── README.md                    # 本文档
├── requirements.txt
├── src/xueqiu_analyzer/
│   ├── __init__.py
│   ├── cli.py                   # CLI 入口
│   ├── orchestrator.py          # 迭代编排
│   ├── crawler.py               # Playwright 爬虫 (~1050行)
│   ├── models.py                # 数据模型 (dataclass)
│   ├── config.py                # 配置加载
│   ├── config.yaml              # 配置文件
│   ├── financial_fetcher.py     # 财务数据
│   ├── quality.py               # Layer 1 硬指标
│   ├── evaluator.py             # Layer 2 LLM 评分
│   ├── analyzer.py              # LLM 深度分析
│   └── llm_client.py            # LLM API 封装
├── prompts/
│   ├── evaluation.md            # 充分性评估 Prompt
│   ├── analysis.md              # 深度分析 Prompt
│   └── conservative.md          # 保守版 Prompt
├── tests/
│   ├── test_modules.py
│   ├── test_evaluator.py
│   └── test_quality.py
└── data/                        # 输出目录
```

---

## 9. 系统依赖

| 依赖 | 用途 |
|------|------|
| Python 3.11+ | 运行时 |
| Playwright + Chromium | 浏览器爬虫 |
| financial-sdk | 财务指标（ROE/ROIC/利润率） |
| `FINANCIAL_SDK_DIR` 环境变量 | financial-sdk 路径（默认 `/root/code/financial-sdk`） |

---

## 10. OpenClaw Agent 指引

### 触发关键词

| 模式 | 示例 | 动作 |
|------|------|------|
| `分析 {symbol}` | "分析 TCOM" | `cli.py analyze` |
| `爬取 {symbol}` | "爬一下00700" | `cli.py crawl` |

symbol 格式：`TCOM`, `PDD`, `00700`, `SH600519`, `SZ300760`

### 调用方式

```bash
cd /root/code/xueqiu-analyzer-skill && .venv/bin/python -m xueqiu_analyzer.cli analyze {symbol}
```

### 注意事项

- Playwright 同一时间只能跑一个实例
- 全流程分析约 5-8 分钟（含 LLM 调用）
- cookies 过期时执行 `cli.py cookies` 刷新

---

## 11. 已知限制

1. **时间停止**：热门股票当天可达 400+ 条，触及 `--max-pages` 兜底
2. **专栏误判**：少量「回复」型内容可能被错归 articles（<5%，已通过字数+前缀过滤）
3. **评论区**：详情页选择器可能因页面改版失效
4. **公告**：仅取第一页，旧公告不抓
5. **多年 ROIC**：financial-sdk 暂未集成
6. **DOM 脆弱**：严重依赖雪球页面结构

---

## 版本历史

| 版本 | 日期 | 核心变更 |
|------|------|----------|
| v3.1.0 | 2026-05-26 | 时间维度停止、四分类分离、JS 结构化提取、评论爬取、专栏详情富化 |
| v3.0.0 | 2026-05-24 | 模块化重构、financial-sdk 替代 AkShare、Layer 1 硬指标 |
| v2.2.1 | 2026-05-24 | 代码审查修复 |
| v2.0.0 | 2026-03-06 | Playwright + 双 Prompt + 智能迭代 |
| v1.0.0 | 2026-03-05 | 基础爬虫 + GLM-5 分析 |

## License

MIT
