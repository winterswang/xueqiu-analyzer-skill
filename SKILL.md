---
name: xueqiu-analyzer
description: 雪球公司分析 Skill V3 — 自动化雪球舆情爬取 + 硬指标数据质检 + AI 深度投资报告
version: 3.0.0
author: winterswang
---

# 雪球公司分析 Skill V3

自动化爬取雪球股票舆情数据，经硬指标质检和 LLM 充分性评估后，生成结构化投资价值分析报告。

## 快速使用

```bash
cd /root/code/xueqiu-analyzer-skill

# 完整分析（爬取 + 评估 + 分析报告）
.venv/bin/python -m xueqiu_analyzer.cli analyze TCOM

# 只爬取数据
.venv/bin/python -m xueqiu_analyzer.cli crawl TCOM

# 只评估已有数据
.venv/bin/python -m xueqiu_analyzer.cli evaluate data/TCOM_data_20260524_140620.json

# 重新分析已有数据
.venv/bin/python -m xueqiu_analyzer.cli reanalyze data/TCOM_data_20260524_140620.json

# 使用保守模板（含估值温度）
.venv/bin/python -m xueqiu_analyzer.cli analyze TCOM --template conservative

# 刷新 cookies
.venv/bin/python -m xueqiu_analyzer.cli cookies
```

**注意**: 需要先设置 `DEEPSEEK_API_KEY` 环境变量。

---

## 架构总览

```
┌────────────────────────────────────────────────────────────────┐
│                      xueqiu-analyzer V3                        │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  CLI → Orchestrator (迭代编排)                                  │
│          │                                                     │
│          ├─ Crawler (Playwright 浏览器爬取)                     │
│          │    ├─ discussions (讨论帖) ×10                       │
│          │    ├─ news (资讯) ×9                                 │
│          │    ├─ notices (公告) ×10                             │
│          │    └─ articles (专栏文章) ×7                         │
│          │                                                     │
│          ├─ FinancialFetcher (财务数据)                         │
│          │    ├─ 雪球 API → PE, PB, 市值, 52周高低              │
│          │    └─ financial-sdk CLI → 毛利率, 净利率, ROE, ROIC, 增速 │
│          │                                                     │
│          ├─ QualityChecker (Layer 1: 硬指标, 不耗 LLM)          │
│          │    ├─ 逐类内容完整率 (≥20字符)                        │
│          │    ├─ 财务数据填充率                                  │
│          │    └─ 健康分 0-100 → <70 触发定向重爬                 │
│          │                                                     │
│          ├─ Evaluator (Layer 2: LLM 评分)                      │
│          │    └─ 8维度 × 25分 → 150分阈值                       │
│          │                                                     │
│          └─ Analyzer (LLM 深度分析)                             │
│               └─ 执行摘要 + 8主题分析 + 投资决策                 │
│                                                                │
│  输出: data/{SYMBOL}_data_{timestamp}.json                      │
│         data/{SYMBOL}_evaluation_{timestamp}.md                 │
│         data/{SYMBOL}_report_{timestamp}.md                     │
└────────────────────────────────────────────────────────────────┘
```

---

## 迭代爬取流程

```
Round 1
  ├─ crawl (pages=5, articles=10)
  ├─ QualityChecker → 健康分
  │   ├─ < 70 → 定向重爬 (articles+10 / pages+5)
  │   └─ >= 70 → Evaluator (LLM 8维度评分)
  │       ├─ >= 150 → ✅ 进入分析
  │       ├─ < 150 & round < max → 🔄 继续
  │       └─ round = max → ⚠️ 强制进入
```

**定向重爬策略**：
- `suggestions=[文章]` → articles +10
- `suggestions=[新闻]` → pages +5
- `suggestions=[公告]` → pages +5

---

## 数据模型

### CrawlResult（爬取输出）
| 字段 | 类型 | 说明 |
|------|------|------|
| symbol | str | 股票代码 |
| name | str | 雪球显示名 |
| price | str | 当前价 |
| discussions | list[Discussion] | 讨论帖 |
| news | list[News] | 资讯 |
| notices | list[Notice] | 公告 |
| articles | list[Article] | 专栏文章 |
| financial_data | FinancialData | 财务指标 |
| crawled_at | ISO timestamp | 爬取时间 |

### Discussion
| 字段 | 说明 |
|------|------|
| author | 作者 |
| content | 正文内容 |
| time | 发布时间 |
| link | 详情页链接 |

### News（🔧 V3 已修复正文提取）
| 字段 | 说明 |
|------|------|
| title | 标题（从 timeline 拆出） |
| content | 正文内容（从 item text 提取） |
| time | 发布时间 |
| source | 来源（新闻/公告/研报/媒体） |
| link | 外部链接 |

### Notice（🔧 V3 已修复摘要提取）
| 字段 | 说明 |
|------|------|
| title | 公告标题 |
| content | SEC 公告→结构化摘要；雪球内部→正文 |
| link | SEC EDGAR 或雪球详情页 |
| pdf_link | PDF 下载链接 |
| notice_type | 公告类型 |

### Article
| 字段 | 说明 |
|------|------|
| title | 文章标题 |
| author | 作者 |
| content | 全文（最长 10000 字符） |
| time | 发布时间 |
| link | 文章链接 |
| article_id | 雪球文章 ID |

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

## 数据质量报告（Layer 1 硬指标）

评估报告第一部分，纯代码检测，不消耗 LLM token：

```
📊 爬取数据质量报告（硬指标）
健康分: 91/100 ✅ 通过

内容完整率:
| 类别 | 总数 | 有内容 | 完整率 |
|------|:---:|:---:|:---:|
| 资讯 | 9   | 9   | 100% ✅
| 公告 | 10  | 10  | 100% ✅
| 文章 | 7   | 4   | 57%  ✅
| 讨论 | 10  | 10  | 100% ✅

财务数据完整性: 7/7 100% ✅
```

**预警触发条件**：
- 资讯有内容率 < 50% → 建议重爬新闻
- 公告有内容率 < 30% → 建议重爬公告
- 文章数为 0 → 建议重爬文章
- 财务字段缺失 → 告警
- 健康分 < 70 → 跳过 LLM 评估，直接定向重爬

---

## LLM 评分体系（Layer 2）

| 主题 | 满分 | 评分依据 |
|------|:---:|----------|
| 估值分析 | 25 | DCF/相对估值/历史对比 |
| 商业模式 | 25 | 护城河/可持续性/平台效应 |
| 财务质量 | 25 | 利润率/ROE/FCF/增速 |
| 竞争格局 | 25 | 竞对分析/市场份额/壁垒 |
| 管理层 | 25 | 履历/战略/资本配置 |
| 风险因素 | 25 | 系统性风险识别与量化 |
| 用户价值 | 25 | 真实用户反馈/NPS |
| 未来前景 | 25 | 增长逻辑/第二曲线 |

**终止条件**：总分 >= 150 或达到 max_rounds（默认 3 轮）

---

## 配置

`config/config.yaml`：

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

quality:          # Layer 1 硬指标
  health_threshold: 70
  news_min_ratio: 0.5
  notice_min_ratio: 0.3
  min_content_length: 20
  min_article_length: 200

notify:
  gist: false
  feishu: false
```

**API Key 优先级**：
1. 环境变量 `DEEPSEEK_API_KEY`
2. `config/config.yaml` 中的 `${DEEPSEEK_API_KEY}` 占位符（自动替换）
3. OpenClaw provider 配置

---

## 模块清单

```
src/xueqiu_analyzer/
├── __init__.py
├── cli.py              # CLI 入口 (analyze/crawl/evaluate/reanalyze/cookies)
├── orchestrator.py     # 迭代编排 (crawl→quality→evaluate→analyze)
├── crawler.py          # Playwright 浏览器爬虫 (反检测/登录/cookies)
├── models.py           # 数据模型 (dataclass)
├── config.py           # 统一配置 (env > yaml > openclaw.json)
├── financial_fetcher.py # 财务数据 (雪球API + financial-sdk CLI)
├── quality.py          # Layer 1 硬指标检测器
├── evaluator.py        # Layer 2 LLM 充分性评估
├── analyzer.py         # LLM 深度分析报告
├── llm_client.py       # LLM API 客户端封装
├── config.yaml         # 配置文件
prompts/
├── evaluation.md       # 充分性评估 Prompt
├── analysis.md         # 深度分析 Prompt
├── conservative.md     # 保守版分析 Prompt (含估值温度)
tests/
├── test_modules.py     # 模块单元测试
├── test_evaluator.py   # 评估器测试
└── test_quality.py     # 硬指标检测器测试
```

---

## 测试

```bash
.venv/bin/python -m pytest tests/ -q
# 50 passed
```

---

## 系统依赖

| 依赖 | 用途 |
|------|------|
| Python 3.11+ | 运行时 |
| Playwright + Chromium | 浏览器爬虫 |
| financial-sdk | 财务指标（毛利率/净利率/ROE/ROIC） |
| gh CLI | Gist 上传（可选） |

`FINANCIAL_SDK_DIR` 环境变量可指定 financial-sdk 路径（默认 `/root/code/financial-sdk`）。

---

## 已知限制

1. **讨论评论**：不爬取评论（低价值，且雪球限制评论可见）
2. **多年 ROIC**：financial-sdk 暂未集成多年度 ROIC 趋势
3. **飞书通知**：通过文件 IPC（`/tmp/`）中转，未直连 API
4. **爬虫脆弱**：严重依赖雪球 DOM 结构，UI 变更可能失效
5. **无集成测试**：缺少端到端 Playwright + LLM 测试

---

## 版本历史

- **V3.0.0**: 完整模块化重构，financial-sdk 替换 AkShare，Layer 1 硬指标质检
- **V2.2**: 多年 ROIC，公告详情页
- **V2.1**: 10轮迭代，30分超时，Token 统计
- **V2.0**: 智能迭代爬取
