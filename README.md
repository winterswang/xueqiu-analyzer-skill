# 雪球公司分析 Skill V4

> 输入股票代码，全自动爬取雪球社区数据 + PDF 公告正文 + AI 深度分析 → 结构化投资报告。

**版本**: 4.1.0 ｜ **爬虫**: Playwright + 雪球内部 API 混合 ｜ **模型**: DeepSeek ｜ **覆盖**: A 股 / 港股 / 美股

---

## 1. 能力一览

| 能力 | 说明 | 核心参数 |
|------|------|----------|
| 🕸️ 讨论爬取 | API 分页（type=11），159 条/轮 | `--max-pages` |
| 📰 资讯爬取 | DOM 翻页 + 详情正文提取 | `--max-news` |
| 📋 公告爬取 | API 分页 + PDF 正文（PyMuPDF） | `--max-notices` |
| ✍️ 专栏文章 | type=2 标记 + `【专栏` 前缀双路径分离 | `--max-articles` |
| 🔄 双向降级 | API 失败 → 自动退到 DOM 翻页，三 tab 独立降级 | 阈值：`len < 3` |
| 📊 硬指标质检 | Layer 1 纯代码检测（不用 LLM，省 token） | 健康分 0-100 |
| 🤖 LLM 评估 | Layer 2 信息充分性评估（8 主题打分） | ≥150 充分通过 |
| ⭐ 内容筛优 | ContentGrader：LLM 对讨论帖质量评分筛选 | `xueqiu grade` |
| 📝 投资报告 | 8 维度深度分析 + 入场/退出策略 + 原文引用 | 6000+ 字 |
| ⏱📏🧠 三种爬取模式 | 时间窗口 / 数量限制 / 质量驱动迭代（可组合） | `--days` `--max-items` `--auto` |
| 🌐 LLM 文章提取 | ScrapingExtractor：深挖详情页正文 + CSS fallback | 自动调用 |

---

## 2. 架构

```
xueqiu analyze <symbol>
         │
         ▼
    orchestrator.py ── 编排：迭代爬取 → 硬指标 → LLM 评估 → 深度分析
         │
    ┌────┼────┬──────────┬──────────────┐
    ▼    ▼    ▼          ▼              ▼
  讨论  资讯  公告      专栏文章       内容筛选
  API   DOM  API+PDF   LLM提取       ContentGrader
    │    │    │          │              │
    └────┴────┴──────────┴──────────────┘
         │
         ▼
    quality.py ── Layer 1 硬指标（健康分 < 70 → 定向重爬）
         │
         ▼
    evaluator.py ── Layer 2 LLM 评估（8 主题 ≥ 150 → 充分）
         │
         ▼
    analyzer.py ── 8 维度投资分析报告
```

**模块分工**（~4800 行 Python，100 个测试）：

| 模块 | 行数 | 职责 |
|------|------|------|
| `crawler.py` | 1363 | API + Playwright 混合爬虫，双向降级，count-stop |
| `stock_analyzer.py` | 822 | DeepAnalyzer：爬→分组分析→合成报告，含 auto 模式 |
| `extractor.py` | 365 | LLM 驱动的文章正文提取 + CSS selector fallback |
| `orchestrator.py` | 349 | 全流程编排，迭代爬取+评估+分析 |
| `quality.py` | 300 | Layer 1 硬指标：内容完整率 + 健康分 + 定向重爬建议 |
| `models.py` | 283 | 全模块统一数据模型（CrawlResult/EvaluationResult 等） |
| `evaluator.py` | 281 | Layer 2 LLM 充分性评估：8 主题打分 + 爬取建议 |
| `financial_fetcher.py` | 252 | 雪球 API + financial-sdk CLI 双源财务数据 |
| `cli.py` | 331 | Click CLI：7 个命令 + 参数模式统一 |
| `analyzer.py` | 202 | 8 维度投资分析报告生成 |
| `content_grader.py` | 197 | 讨论帖质量评分 + 批量主题提取 |
| `config.py` | 153 | YAML + 环境变量 + openclaw.json 多源回退 |
| `llm_client.py` | 95 | 统一 LLM 调用封装（chat/evaluate/analyze） |
| `token_utils.py` | 41 | Token 估算 + LLM 批量分组 |

---

## 3. 快速开始

### 3.1 安装

```bash
pip install -r requirements.txt
playwright install chromium
pip install -e .
```

### 3.2 配置 API Key

```bash
export DEEPSEEK_API_KEY="sk-xxx"
```

并在 `config/config.yaml` 中确认：
```yaml
llm:
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  api_key: "${DEEPSEEK_API_KEY}"
```

### 3.3 登录雪球（首次需要）

```bash
python -m xueqiu_analyzer.cli cookies  # 引导登录
```

### 3.4 安装 PyMuPDF（公告 PDF 提取）

```bash
pip install PyMuPDF
```

---

## 4. CLI 命令

### 4.1 `analyze` — 全流程分析（Legacy 编排器）

```bash
python -m xueqiu_analyzer.cli analyze SH600519
# 迭代爬取 + 质检 + LLM 评估 + 深度分析
```

### 4.2 `deep-analyze` — 深度舆情分析（推荐）

```bash
# 基础用法：手动控制爬取量
python -m xueqiu_analyzer.cli deep-analyze 00700 --max-pages 10 --days 30

# 时间窗口模式：只看最近 7 天
python -m xueqiu_analyzer.cli deep-analyze 00700 --days 7

# 数量驱动模式：最多 100 条内容
python -m xueqiu_analyzer.cli deep-analyze 00700 --max-items 100

# 质量驱动模式：迭代爬取到评分达标
python -m xueqiu_analyzer.cli deep-analyze 00700 --auto --quality-score 150

# 组合模式：过去 30 天 + 最多 200 条 + 评分达标，任一满足即停
python -m xueqiu_analyzer.cli deep-analyze 00700 --days 30 --max-items 200 --auto
```

### 4.3 `crawl` — 单独爬取

```bash
# 基础爬取
python -m xueqiu_analyzer.cli crawl PDD --max-pages 5 --max-articles 5

# 数量驱动
python -m xueqiu_analyzer.cli crawl 00700 --max-items 200

# 时间过滤
python -m xueqiu_analyzer.cli crawl 00700 --days 7
```

### 4.4 `grade` — 内容质量评分

```bash
# 对已爬数据中的讨论帖进行质量分级
python -m xueqiu_analyzer.cli grade --data data/00700_data.json

# 输出：高质量帖 / 主题聚类 / 共识观点 / 信息缺口
```

### 4.5 `evaluate` — 评估已有数据

```bash
python -m xueqiu_analyzer.cli evaluate --data data/00700_data.json
# 输出：8 主题评分 + 充分性判定 + 爬取建议
```

### 4.6 `reanalyze` — 重新分析已有数据

```bash
python -m xueqiu_analyzer.cli reanalyze --data data/00700_data.json
# 换 Prompt 或换模型重新生成报告
```

---

## 5. 配置参考（config/config.yaml）

```yaml
llm:
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  api_key: "${DEEPSEEK_API_KEY}"
  max_tokens: 8000
  temperature: 0.7

crawler:
  headless: true
  delay_min: 3
  delay_max: 8
  timeout: 30000
  default_max_pages: 1000        # --max-items 无上限时的硬兜底
  max_items_fallback: 2000       # max_items 隐含上限
  auto_max_rounds: 20            # --auto 模式最大迭代轮次

evaluator:
  score_threshold: 150           # 充分性通过阈值
  max_rounds: 3

quality:                         # Layer 1 硬指标
  health_threshold: 70
  news_min_ratio: 0.5
  notice_min_ratio: 0.3
  min_content_length: 20
  min_article_length: 100
```

---

## 6. 参数模式对照

| `--days` | `--max-items` | `--auto` | 行为 |
|----------|--------------|----------|------|
| 0 | 0 | ❌ | 全量爬取（硬上限 max_pages=1000） |
| 30 | 0 | ❌ | 过去 30 天全部，不限条数 |
| 0 | 50 | ❌ | 最新 50 条，不限时间 |
| 30 | 50 | ❌ | 过去 30 天，最多 50 条（任一先停） |
| 0 | 0 | ✅ | 迭代爬取，评分达标即停 |
| 7 | 100 | ✅ | 三种条件：任一满足即停 |

---

## 7. 实测效果

### 三市场验证

| 指标 | 🍶 茅台 (SH600519) | 🫧 泡泡玛特 (09992) | 📦 PDD |
|------|-------------------|---------------------|--------|
| **讨论** | 86 条 | 81 条 | 54 条 |
| **资讯** | 47 条 | 49 条 | 48 条 |
| **公告** | 19/19 PDF ✅ | 19/20 PDF ✅ | SEC 摘要 |
| **文章** | 18 篇 | 22 篇 | 10 篇 |
| **评估分** | **155/200** ✅ | **145/200** | **120/200** |
| **报告字数** | 6543 | 4925 | 6473 |

---

## 8. 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 讨论获取 | API 分页（type=11） | 10 条 → 159 条，16× 提升 |
| 资讯获取 | DOM 直接爬取 | `interview/search.json` 是访谈接口，非实时新闻 |
| 公告获取 | API 分页 + PyMuPDF PDF | 港股/A 股 PDF 可提取，数据量 10→19 |
| 文章提取 | DeepSeek LLM + CSS fallback | 智能提取 + 保底降级 |
| 专栏区分 | API type=2 / DOM `【专栏` 前缀 | 服务器标记 + 内容前缀，双重保障 |
| 双向降级 | 每个 tab 独立检查 `len < 3` | 部分失败不阻塞其他 tab |
| 双层评估 | Layer1 硬指标 + Layer2 LLM | 省 30% token 成本 |
| 参数模式 | 时间/数量/质量可组合 | 用户心智模型，非机械参数 |

---

## 9. 已修复 Bug（V3.0 以来）

| 症状 | 根因 | 修复 commit |
|------|------|------------|
| 资讯正文全部为免责声明 | 无免责声明过滤 | `f58e9f4`（#6） |
| 股价/涨跌未提取 | CSS selector 单一 | `f58e9f4`（#6） |
| `max_tokens=0` 被当作 falsy 覆盖 | `max_tokens or config` 逻辑 | `1f8ca71`（#4） |
| openclaw.json 异常静默吞 | `except Exception: pass` 无日志 | `1f8ca71`（#4） |
| 未使用 import + 空 f-string | V3 重构遗留 | `1f8ca71`（#4） |
| 硬编码股票代码 TCOM | 正则写死 | `64d0bde` |
| 资讯链接缺失 | DOM 结构变动 | `2b2d9e9` |
| 多页数据重复 | 未按类型去重 | `d4d6928` |

---

## 10. 局限与路线

| 局限 | 状态 | 计划 |
|------|------|------|
| 美股 SEC 公告正文 | ⏳ 未实现 | EDGAR 定向解析 |
| 港股股价提取 | ⏳ 选择器失效 | 更新兼容性 |
| 资讯详情耗时 ~3 分钟 | ⚠️ 瓶颈 | 可选异步并行 |
| ScrapingExtractor JSON 截断 | 🔧 已加修复 | 持续监控 |

---

## 11. 开发

```bash
# 运行测试（100 个）
python -m pytest tests/ -v

# 代码质量检查
python -m pyflakes src/xueqiu_analyzer/
```

**分支策略**：
- `main` — 稳定版本（V4.1.0）
- `feature/param-modes` — 🚧 参数模式统一（#12，即将合并）
- `feature/scrapegraph-extractor` — ScrapingExtractor 实验（#8，已合并）
- `feature/api-based-crawl` — #9 纯 API 方案（已被 V4 替代）

---

*最后更新: 2026-06-03*
