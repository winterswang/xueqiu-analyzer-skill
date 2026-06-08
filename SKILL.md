---
name: xueqiu-analyzer
description: 雪球公司分析 Skill V3 — 自动化雪球舆情爬取 + 硬指标数据质检 + AI 深度投资报告
version: 3.2.0
author: winterswang
---

# 雪球公司分析 Skill V3

自动化爬取雪球股票舆情数据，经硬指标质检和 LLM 充分性评估后，生成结构化投资价值分析报告。分析结果自动发布到飞书文档和 IMA 笔记。

## 快速使用

```bash
cd /root/code/xueqiu-analyzer-skill

# 完整分析（爬取 + 评估 + 分析报告）
.venv/bin/python -m xueqiu_analyzer.cli analyze TCOM

# 只爬取数据（时间维度自动停止，按今天全部内容）
.venv/bin/python -m xueqiu_analyzer.cli crawl TCOM

# 爬取指定数量 + 自定义超时
.venv/bin/python -m xueqiu_analyzer.cli crawl TCOM --max-pages 50 --max-articles 30 --timeout 1200

# 只评估已有数据
.venv/bin/python -m xueqiu_analyzer.cli evaluate data/TCOM_data_20260524_140620.json

# 重新分析已有数据（自动发布到 IMA）
.venv/bin/python -m xueqiu_analyzer.cli reanalyze data/TCOM_data_20260524_140620.json

# 重新分析并发布到指定 IMA 笔记本
.venv/bin/python -m xueqiu_analyzer.cli reanalyze data/TCOM_data_20260524_140620.json \
    --ima-folder folder_xxx --ima-folder-name "我的笔记本"

# 使用保守模板（含估值温度）
.venv/bin/python -m xueqiu_analyzer.cli analyze TCOM --template conservative

# 刷新 cookies
.venv/bin/python -m xueqiu_analyzer.cli cookies
```

**CLI 参数**：

| 参数 | 默认值 | 说明 |
|------|:---:|------|
| `--max-pages` | 10 | 最大翻页数（兜底，实际由时间停止控制） |
| `--max-articles` | 20 | 讨论详情富化上限（打开详情页补标题/评论） |
| `--timeout` | 1200 | 超时秒数 |
| `--ima-folder` | — | IMA 笔记本 ID（默认「价值投资研究」） |
| `--ima-folder-name` | — | IMA 笔记本名称（可选） |

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
│          │    ├─ discussions (讨论帖) · 时间停止                 │
│          │    ├─ articles (专栏文章) · 从讨论分离 + 详情富化     │
│          │    ├─ news (资讯) · 时间停止                         │
│          │    └─ notices (公告) · 首页 20 条                    │
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
│          ├─ Analyzer (LLM 深度分析)                             │
│          │    └─ 执行摘要 + 8主题分析 + 投资决策                  │
│          │                                                     │
│          └─ IMA Publisher (笔记发布)                             │
│               ├─ prepend_report_title (自动标题前缀)             │
│               ├─ extract_title (Markdown → 笔记标题)             │
│               └─ import_doc (写入 IMA 笔记本)                    │
│                                                                │
│  输出: data/{SYMBOL}_data_{timestamp}.json                      │
│         data/{SYMBOL}_evaluation_{timestamp}.md                 │
│         data/{SYMBOL}_report_{timestamp}.md                     │
│         IMA note_id (自动发布到指定笔记本)                       │
└────────────────────────────────────────────────────────────────┘
```

---

## 爬取机制（V3.1 时间维度驱动）

### 时间停止策略

爬取 讨论 和 资讯 时，不再按固定页数/条数限制，而是按**发布时间**判断：

1. 每页解析 `.timeline__item` 中的 `time` 字段
2. 当一页出现 ≥3 条"昨天"或日期格式（如 `05-24` / `2026-05-24`）→ 停止翻页
3. 讨论 tab 默认使用「最新」排序（非热帖），确保按时间线获取今天全部内容

### 翻页机制

- 雪球使用传统页码分页（`[1] [2] ... [下一页]`），非无限滚动
- 爬虫点击「下一页」链接逐页翻页
- 每页解析后立即存入结果列表（DOM 元素在换页后失效，必须先解析再翻页）
- 兜底：最多翻 `--max-pages` 页（默认 10），或连续 3 页无新内容时停止

### 公告

- 公告数量少，不翻页，只取第一页的 10-20 条
- 不走时间停止（公告标题格式与讨论/资讯不同）

### 专栏文章分离（四分类）

爬取时为保持四分类模型（讨论/专栏/资讯/公告），在讨论页解析后自动分离：

- 检测 timeline item 中的专栏标题（h3 含「专栏」）
- **真文章**（正文 ≥80 字且不以「回复」开头）→ `articles[]`
- **回复帖**（引用专栏的短回复）→ 保留在 `discussions[]`
- 分离后删除讨论中的 `【专栏xxx】` 前缀残留

### 讨论详情富化

- 专栏文章优先富化（先 articles 后 discussions）
- 取前 `--max-articles` 条有链接的讨论（默认 30）
- 打开详情页提取：专栏文章标题、完整正文（最多 5000 字）、评论列表
- 讨论富化上限 2000 字

### 解析方式

- 使用 `item.evaluate(JS)` 结构化提取，替代旧的 `inner_text() + regex`
- Author: 从 `<a>` 标签提取，过滤掉"收起/展开/$股票名/时间串/icon"等噪音
- Time: 从时间链接 regex 提取
- Content: 优先 `.article__bd__detail` → 回退 `innerText` 减 chrome
- 评论: 详情页 `.comment-item` → `innerText`
- 去重: 按正文前 50 字符签名去重

### 爬取耗时参考

| 股票 | 讨论 | 专栏 | 资讯 | 公告 | 耗时 |
|------|:---:|:---:|:---:|:---:|:---:|
| AAPL | ~90 | ~10 | ~10 | ~10 | ~4 min |
| 00700 | ~440 | ~20 | ~10 | ~10 | ~6 min |
| SH600519 | ~490 | ~13 | ~10 | ~10 | ~6 min |

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
| articles | list[Article] | 专栏文章 |
| news | list[News] | 资讯 |
| notices | list[Notice] | 公告 |
| financial_data | FinancialData | 财务指标 |
| crawled_at | ISO timestamp | 爬取时间 |

### Discussion
| 字段 | 说明 |
|------|------|
| author | 作者（JS 结构化提取，已过滤"收起/展开"等噪音） |
| content | 正文（最长 2000 字符） |
| time | 发布时间 |
| link | 详情页链接 |
| comments | list[str] · 评论列表（从详情页提取，最多 30 条） |
| comment_count | int · 评论数 |
| forward_count | int · 转发数 |
| like_count | int · 赞数 |

### Article
| 字段 | 说明 |
|------|------|
| title | 专栏标题（如「专栏腾讯的熵增困境...」） |
| author | 作者 |
| content | 全文（最长 5000 字符，从详情页提取） |
| time | 发布时间 |
| link | 文章链接 |
| article_id | 雪球文章 ID |
| comments | list[str] · 评论列表（最多 30 条） |
| comment_count | int · 评论数 |
| like_count | int · 赞数 |

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

---

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
| 讨论 | 88  | 88  | 100% ✅
| 专栏 | 11  | 11  | 100% ✅
| 资讯 | 10  | 10  | 100% ✅
| 公告 | 10  | 10  | 100% ✅

财务数据完整性: 7/7 100% ✅
```

**预警触发条件**：
- 资讯有内容率 < 50% → 建议重爬新闻
- 公告有内容率 < 30% → 建议重爬公告
- 专栏数为 0 → 建议重爬专栏
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
1. `config.yaml` 中 `api_key` 指定的环境变量（如 `${DEEPSEEK_API_KEY}`）
2. 通用 fallback 链：`ARK_API_KEY` → `BAILIAN_API_KEY` → `DASHSCOPE_API_KEY`
3. OpenClaw provider 配置（`~/.openclaw/openclaw.json`）

当 Key 来源变更时（如从 yaml key 回退到 ARK_KEY），`base_url` 自动跟随切换，避免 Key/Endpoint 不匹配导致 401 错误。

**依赖管理**：`python-dotenv>=1.0` 已加入 `requirements.txt`，`.env` 文件在项目启动时自动加载。

**IMA 凭证**：
- 环境变量 `IMA_OPENAPI_CLIENTID` / `IMA_OPENAPI_APIKEY`（优先）
- 文件 `~/.config/ima/client_id` / `~/.config/ima/api_key`（回退）
- 默认发布到「价值投资研究」笔记本

---

## 模块清单

```
src/xueqiu_analyzer/
├── __init__.py
├── cli.py              # CLI 入口 (analyze/crawl/evaluate/reanalyze/cookies)
├── orchestrator.py     # 迭代编排 (crawl→quality→evaluate→analyze→IMA)
├── crawler.py          # Playwright 浏览器爬虫 (反检测/登录/cookies)
├── models.py           # 数据模型 (dataclass)
├── config.py           # 统一配置 (env > yaml > openclaw.json)
├── financial_fetcher.py # 财务数据 (雪球API + financial-sdk CLI)
├── quality.py          # Layer 1 硬指标检测器
├── evaluator.py        # Layer 2 LLM 充分性评估
├── analyzer.py         # LLM 深度分析报告
├── ima_publisher.py    # IMA 笔记发布 (标题提取/UTF-8校验/笔记本归入)
├── llm_client.py       # LLM API 客户端封装
├── config.yaml         # 配置文件
prompts/
├── evaluation.md       # 充分性评估 Prompt
├── analysis.md         # 深度分析 Prompt
├── conservative.md     # 保守版分析 Prompt (含估值温度)
tests/
├── test_modules.py     # 模块单元测试
├── test_evaluator.py   # 评估器测试
├── test_quality.py     # 硬指标检测器测试
└── test_ima_publisher.py # IMA 发布测试
```

---

## 测试

```bash
.venv/bin/python -m pytest tests/ -q
# 114 passed
```

---

## 系统依赖

| 依赖 | 用途 |
|------|------|
| Python 3.11+ | 运行时 |
| Playwright + Chromium | 浏览器爬虫 |
| financial-sdk | 财务指标（毛利率/净利率/ROE/ROIC） |
| IMA OpenAPI | 笔记发布（需凭证） |
| gh CLI | Gist 上传（可选） |

`FINANCIAL_SDK_DIR` 环境变量可指定 financial-sdk 路径（默认 `/root/code/financial-sdk`）。

---

## 已知限制

1. **时间停止精度**：讨论按"昨天"判断，热门股票当天可达 400+ 条，触及 `--max-pages 50` 兜底
2. **专栏文章误判**：少量"回复"型内容可能被错误归入 articles（<5%），已通过正文长度和"回复"前缀过滤
3. **评论区提取**：详情页评论区选择器可能因页面改版而失效
4. **公告不翻页**：仅取第一页，旧公告不会抓取
5. **多年 ROIC**：financial-sdk 暂未集成多年度 ROIC 趋势
6. **飞书通知**：通过文件 IPC（`/tmp/`）中转，未直连 API
7. **爬虫脆弱**：严重依赖雪球 DOM 结构，UI 变更可能失效
8. **无集成测试**：缺少端到端 Playwright + LLM 测试
9. **IMA 内容大小**：超长报告可能触发 API 100009 错误，需拆分为多次 append 写入（暂未实现自动拆分）

---

## 版本历史

- **V3.2.0**: IMA 笔记自动发布（标题提取 + 笔记本归入），python-dotenv 依赖修复，base_url 跟随 Key 来源自动切换
- **V3.1.0**: 时间维度停止翻页、四分类模型（讨论/专栏/资讯/公告）、JS 结构化提取、评论爬取、专栏详情富化
- **V3.0.0**: 完整模块化重构，financial-sdk 替换 AkShare，Layer 1 硬指标质检
- **V2.2**: 多年 ROIC，公告详情页
- **V2.1**: 10轮迭代，30分超时，Token 统计
- **V2.0**: 智能迭代爬取
