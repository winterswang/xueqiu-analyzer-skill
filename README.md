# 雪球公司分析 Skill V4

> 输入股票代码，全自动爬取雪球社区数据 + PDF 公告正文 + AI 深度分析 → 结构化投资报告。

**版本**: 4.0.0-Hybrid ｜ **爬虫**: Playwright + 雪球内部 API 混合 ｜ **模型**: DeepSeek ｜ **覆盖**: A 股 / 港股 / 美股

---

## 1. 能力一览

| 能力 | 说明 | 数据量（茅台实测） |
|------|------|-------------------|
| 🕸️ 讨论爬取 | API 分页（10 页 × 20 条） | **86 条**，含互动指标 |
| 📰 资讯爬取 | DOM 翻页 + 详情正文提取 | **47 条**，正文 200-2200+ 字 |
| 📋 公告爬取 | API 分页 + PDF 正文（PyMuPDF） | **19 条**，正文 640-8017 字/条 |
| ✍️ 专栏文章 | type=2 标记 + `【专栏` 前缀匹配 | **18 篇**，LLM 正文提取 |
| 📊 硬指标质检 | Layer 1 纯代码检测（不用 LLM，省 token） | 内容完整率 + 健康分 0-100 |
| 🤖 LLM 评估 | Layer 2 信息充分性评估（8 主题打分） | 150 分触发充分通过 |
| 📝 投资报告 | 8 维度深度分析 + 投资决策 | **155/200 分**，6543 字 |
| 🔄 双向降级 | API 失败 → 自动退到 DOM 翻页 | 三 tab 独立降级 |

---

## 2. 架构

```
xueqiu analyze <symbol>
         │
         ▼
    orchestrator.py ── 编排：迭代爬取 → 硬指标 → LLM 评估 → 深度分析
         │
    ┌────┼────┬──────────┐
    ▼    ▼    ▼          ▼
  讨论  资讯  公告      专栏文章
  API   DOM  API+PDF   LLM提取
    │    │    │          │
    └────┴────┴──────────┘
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

**模块分工**（5588 行 Python，70 个测试）：

| 模块 | 职责 | 关键方法 |
|------|------|---------|
| `crawler.py`（1310 行） | API + Playwright 混合爬虫 | `_crawl_discussions_via_api`, `_crawl_discussion_detail` |
| `extractor.py`（313 行） | LLM 驱动的文章正文提取 | `ScrapingExtractor.extract` |
| `quality.py`（279 行） | Layer 1 硬指标检测 | `ContentQualityChecker.check` |
| `evaluator.py`（281 行） | Layer 2 LLM 充分性评估 | `Evaluator.evaluate` |
| `analyzer.py`（202 行） | 深度投资分析报告 | `Analyzer.analyze` |
| `orchestrator.py`（349 行） | 全流程编排 | `Orchestrator.run` |
| `models.py`（281 行） | 全局数据模型 | `CrawlResult`, `EvaluationResult` |
| `financial_fetcher.py`（252 行） | 财务数据获取 | 雪球 API + financial-sdk CLI |
| `cli.py`（251 行） | CLI 入口 | 6 个命令 |
| `config.py`（138 行） | 配置加载 | YAML + 环境变量 + openclaw.json |

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

---

## 4. 使用示例

### 4.1 全流程分析

```bash
# 自动爬取 + 质检 + LLM 评估 + 深度分析
DEEPSEEK_API_KEY=sk-xxx python -m xueqiu_analyzer.cli analyze SH600519

# 输出:
#   讨论: 86 | 资讯: 47 | 公告: 19 | 文章: 18
#   评分: 155/200 → 充分通过
```

### 4.2 单独爬取

```bash
# 爬取 + 详情提取
python -m xueqiu_analyzer.cli crawl PDD --max-pages 5 --max-articles 5

# 输出: data/PDD_data_20260530_173325.json
```

### 4.3 评估已有数据

```bash
python -m xueqiu_analyzer.cli evaluate --data data/PDD_data_20260530_173325.json

# 输出:
#   总分: 120/200 | 充分性: 基本充分
#   估值分析:  5分 | 商业模式: 15分 | ...
```

### 4.4 重新分析已有数据

```bash
python -m xueqiu_analyzer.cli reanalyze --data data/SH600519_data_20260530_173307.json

# 输出: data/SH600519_report_20260530_173432.md
```

### 4.5 跨股对比分析

```bash
# 爬取多只股票（三市场）
python -m xueqiu_analyzer.cli crawl SH600519 --max-pages 5
python -m xueqiu_analyzer.cli crawl 09992 --max-pages 5
python -m xueqiu_analyzer.cli crawl PDD --max-pages 5

# 分别评估
python -m xueqiu_analyzer.cli evaluate --data data/SH600519_data_*.json
python -m xueqiu_analyzer.cli evaluate --data data/09992_data_*.json
python -m xueqiu_analyzer.cli evaluate --data data/PDD_data_*.json

# 分别分析
python -m xueqiu_analyzer.cli reanalyze --data data/SH600519_data_*.json
python -m xueqiu_analyzer.cli reanalyze --data data/09992_data_*.json
python -m xueqiu_analyzer.cli reanalyze --data data/PDD_data_*.json
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
  delay_min: 3          # 模拟人类延迟（秒）
  delay_max: 8
  timeout: 30000

evaluator:
  score_threshold: 150  # 充分性通过阈值
  max_rounds: 3         # 最大迭代轮次

quality:                # Layer 1 硬指标
  health_threshold: 70
  news_min_ratio: 0.5
  notice_min_ratio: 0.3
  min_content_length: 20
```

---

## 6. 实测效果

### 三市场验证（2026-05-30，max_pages=5）

| 指标 | 🍶 茅台 (SH600519) | 🫧 泡泡玛特 (09992) | 📦 PDD |
|------|-------------------|---------------------|--------|
| **市场** | A 股 | 港股 | 美股（NASDAQ） |
| **讨论** | 86 条 | 81 条 | 54 条 |
| **资讯** | 47 条（DOM） | 49 条（DOM） | 48 条（DOM） |
| **公告** | 19 条（**19/19 PDF** ✅） | 50 条（**19/20 PDF** ✅） | 50 条（SEC 无 PDF ⏳） |
| **文章** | 18 篇 | 22 篇 | 10 篇 |
| **股价** | ¥1326.00 | 未提取 | $84.44 |
| **评估分** | **155/200** ✅ | **145/200** | **120/200** |
| **报告** | 6543 字, 34 引用 | 4925 字, 21 引用 | 6473 字, 30 引用 |

### 特征

| | 茅台 | 泡泡玛特 | PDD |
|--|------|---------|-----|
| 核心讨论主题 | 估值内卷、回购分红 | 段永平持仓、IP 运营 | 仅退款争议、利润率 |
| 公告亮点 | Q1 季报 + 2025 审计报告（8017 字） | 年报 + 组织章程 + 8 条回购 | 6-K/20-F SEC 摘要 |
| LLM 关键判断 | "合理偏低，持有" | "合理偏高，持有" | "买入"（估值低 + EPS miss 修复） |

---

## 7. 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 讨论获取 | API 分页（type=11） | 10 条 → 159 条，16× 提升 |
| 资讯获取 | DOM 直接爬取 | `interview/search.json` 是访谈接口，非实时新闻 |
| 公告获取 | API 分页 + PDF 解析（PyMuPDF） | 港股/A 股 PDF 可提取，SEC 待适配 |
| 文章提取 | DeepSeek LLM + CSS selector fallback | 智能提取 + 保底降级 |
| 专栏区分 | API type=2 / DOM `【专栏` 前缀 | 服务器标记 + 内容前缀，双重保障 |
| 双向降级 | 每个 tab 独立检查 `len < 3` | 部分失败不阻塞其他 tab |

---

## 8. 局限与路线

| 局限 | 状态 | 计划 |
|------|------|------|
| 美股 SEC 公告正文提取 | ⏳ 未实现 | 需要 EDGAR 定向解析 |
| 港股股价提取 | ⏳ 选择器失效 | 更新 .stock-current 兼容性 |
| ScrapingExtractor JSON 截断 | 🔧 已加修复 | 持续监控成功率 |
| 资讯详情耗时 ~3 分钟 | ⚠️ 瓶颈 | 可选异步并行 |

---

## 9. 开发与贡献

```bash
# 运行测试
python -m pytest tests/ -v

# 代码质量检查
python -m pyflakes src/xueqiu_analyzer/
```

**分支策略**：
- `main` — 稳定版本（V3.0.2）
- `feature/v4-hybrid-crawl` — V4 混合爬虫（已合并 #8 + #9，含 DOM 降级）
- `feature/scrapegraph-extractor` — ScrapingExtractor 实验分支（不合并）
- `feature/api-based-crawl` — #9 纯 API 方案（已被 V4 替代）

---

*最后更新: 2026-05-30*
