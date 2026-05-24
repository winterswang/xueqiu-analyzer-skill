# 雪球股票分析 Skill — 项目跟踪日志

> 最后更新：2026-05-25  
> 版本：V3.0.2  
> 最近一次 `LAST_ANALYZED`：`f58e9f4`
> 分析范围：全部历史 commit（47 个）

<!-- @@LAST_ANALYZED: f58e9f44f58052abf91c4c84a8b8ceb3119edc09 @@-->

---

## 🏗️ 系统架构

### 项目概述

输入股票代码，输出结构化投资分析报告。核心流程：Playwright 爬取雪球社区数据 → 多源财务数据获取 → LLM 评估（Layer 2）→ LLM 深度分析 → 报告生成（Gist/飞书推送）。V3 重构后代码迁移到 `src/xueqiu_analyzer/` 标准 Python 包结构，通过 `pyproject.toml` 构建。

### 组件关系

```
用户输入 `xueqiu analyze <symbol>`
        │
        ▼
┌───────────────────────────────┐
│      cli.py (Click CLI)       │  ← 命令路由：analyze/crawl/evaluate/reanalyze
└───────────┬───────────────────┘
            │
            ▼
┌───────────────────────────────┐
│      orchestrator.py          │  ← 编排：迭代爬取 → 硬指标 → LLM评估 → 分析
│   ┌───────────────────────┐   │
│   │ Layer 1: quality.py   │   │  ← 纯代码硬指标检测（不耗 token）
│   └───────────────────────┘   │
│   ┌───────────────────────┐   │
│   │ Layer 2: evaluator.py │   │  ← LLM 信息充分性评估（8 主题打分）
│   └───────────────────────┘   │
└───────────┬───────────────────┘
            │
            ▼
┌───────────────────────────────┐
│  crawler.py (Playwright)      │  ← 雪球数据爬虫：讨论/资讯/公告/文章
└───────────┬───────────────────┘
            │
            ▼
┌───────────────────────────────┐
│  financial_fetcher.py         │  ← 财务数据：雪球 API + financial-sdk
│  - PE/PB/ROE/市值/52周高低    │
│  - 毛利率/净利率/营收增速/利润增速 │
│  - 多年 ROIC 趋势             │
└───────────┬───────────────────┘
            │
            ▼
┌───────────────────────────────┐
│  analyzer.py (LLM)            │  ← 深度投资分析报告生成
│  llm_client.py (统一调用)     │  ← 通用 LLM 封装（urllib）
│  prompts/ (分析模板)           │
└───────────┬───────────────────┘
            │
            ▼
┌───────────────────────────────┐
│  models.py (数据模型)          │  ← 全模块共用 dataclass
│  config.py (配置加载)          │  ← YAML + 环境变量 + openclaw.json fallback
└───────────────────────────────┘
```

### 模块清单（V3 重构版）

| 模块 | 文件 | 行数 | 职责 |
|------|------|------|------|
| 编排器 | `orchestrator.py` | 349 | 迭代爬取 + 硬指标检测 + LLM 评估 + 分析全流程编排 |
| 数据质量 | `quality.py` | 279 | Layer 1 硬指标检测器：内容完整率/财务填充率/健康分 |
| 爬虫引擎 | `crawler.py` | 727 | Playwright 浏览器自动化：登录、Tab 切换、滚动加载、去重合并 |
| 评估器 | `evaluator.py` | 281 | Layer 2 LLM 信息充分性评估（8 主题打分） |
| 分析器 | `analyzer.py` | 202 | 深度投资分析报告生成（LLM Prompt） |
| LLM 客户端 | `llm_client.py` | 170 | 统一 LLM 调用封装（chat/evaluate/analyze/simple_chat） |
| 财务获取 | `financial_fetcher.py` | 252 | 雪球 API + financial-sdk CLI 双源财务数据 |
| 配置加载 | `config.py` | 93 | YAML + 环境变量 + openclaw.json fallback 链 |
| 数据模型 | `models.py` | 281 | CrawlResult/EvaluationResult/FinancialData 等 dataclass |
| CLI 入口 | `cli.py` | 251 | Click 命令行接口（analyze/crawl/evaluate/reanalyze/cookies） |

### V2 遗留代码

| 目录 | 说明 |
|------|------|
| `scripts/` | V2 代码（DEPRECATED.md 声明废弃），V3 替代方案见 `src/xueqiu_analyzer/` |
| `scripts/archive/` | 已删除（1302 行，64d0bde 清理） |

### 数据流

```
雪球社区 ──Playwright──▶ 讨论/资讯/公告/文章 (CrawlResult)
雪球 API  ──HTTP────▶ PE/PB/ROE/市值/52周
financial-sdk ──CLI──▶ 毛利率/净利率/增速/ROIC
                              │
                              ▼
         Layer 1: quality.py —— 硬指标检测（健康分 < 70 → 定向重爬）
                              │
                              ▼
         Layer 2: evaluator.py —— LLM 评分（8 主题，≥150 通过）
                              │
                              ▼
         analyzer.py —— 深度分析报告（Markdown）
                              │
                              ▼
         保存至 data/ + Gist 同步 + 飞书推送
```

### 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.11+ | 主语言 |
| Playwright | 浏览器自动化爬虫 |
| DeepSeek / GLM (LLM) | AI 评估+分析引擎 |
| 雪球 API | 实时股票报价 |
| financial-sdk | 财务指标（毛利率/净利率/ROE/ROIC） |
| PyYAML | 配置文件 |
| Click | CLI 框架 |
| urllib | HTTP 请求 |
| pytest | 单元测试（51 个） |

---

## 📐 ADR (架构决策记录)

### ADR-001：Playwright 为首选爬虫方案

- **时间**：2026-03-06
- **背景**：V1 使用 requests + 模拟浏览器，登录弹窗和遮罩拦截无法可靠绕过
- **决策**：改用 Playwright 全浏览器自动化，通过 JavaScript 注入移除登录弹窗、绕过 Tab 遮罩
- **替代方案**：纯 API 方案（`8a419e8`）曾短暂尝试后被 revert（`61e43ec`），原因：API 方案缺少社区讨论数据
- **影响**：依赖 Chromium 运行时，启动延迟约 5s

### ADR-002：双 Prompt 评估-分析流程

- **时间**：2026-03-07
- **背景**：单次爬取信息不充分，需迭代确定是否继续爬取
- **决策**：Prompt 1 做信息充分性评估（8 个主题打分），Prompt 2 做深度分析
- **评分阈值**：≥150 直接进入深度分析，< 100 继续爬取，100-150 建议补充
- **影响**：爬取轮次从固定 3 轮变为动态终止，分析质量提升

### ADR-003：评分≥150 提前终止机制

- **时间**：2026-03-07
- **背景**：固定最大轮次 10 轮对信息充分的股票浪费计算资源
- **决策**：达到 150 分提前终止，减少 API 调用成本
- **效果**：多数股票 3-5 轮即达标，节省约 50% 爬取时间

### ADR-004：多年 ROIC 数据集成

- **时间**：2026-03-08
- **背景**：投资者关注 ROIC 趋势，单一财务指标不足
- **决策**：集成 akshare_service 获取 5 年 ROIC（已替换为 financial-sdk）
- **影响**：报告新增 ROIC 趋势表格，财务分析深度提升

### ADR-005：多源 API Key 回退链

- **时间**：2026-03-27 → 2026-05-24
- **背景**：不同环境有不同 API Key 来源，需统一回退策略
- **决策**：YAML 指定 env → ARK_API_KEY → BAILIAN_API_KEY → DASHSCOPE_API_KEY → openclaw.json providers
- **优化**：V3 重构简化回退链，移除 OPENAI_API_KEY 路径
- **问题**：回退链仍较长，但各有实际用途

### ADR-006：V3 架构重构（2026-05）

- **时间**：2026-05-24
- **背景**：V2 代码放在 `scripts/` 目录下，模块间职责重叠严重（smart_crawler_v2.py 与 stock_crawler_v2.py 爬取逻辑重叠 70+ 行），无标准 Python 包结构，无法 `pip install`
- **决策**：
  - 迁移到 `src/xueqiu_analyzer/` 标准包结构 + `pyproject.toml`
  - 提取公共数据模型到 `models.py`（CrawlResult / EvaluationResult / FinancialData）
  - 分层架构：Layer 1 硬指标（quality.py）→ Layer 2 LLM 评估（evaluator.py）→ 分析（analyzer.py）→ 编排（orchestrator.py）
  - 统一 LLM 调用：`llm_client.py` 替代 V2 分散的 API 调用
- **影响**：可 `pip install`、可 import、职责解耦、测试可行（51 个）

### ADR-007：Layer 1 硬指标 + Layer 2 LLM 双层评估

- **时间**：2026-05-24
- **背景**：之前每轮迭代都调用 LLM 评估，cost 高（LLM 调用计费），且大量轮次在 LLM 调用前就因数据质量低而注定不合格
- **决策**：新增 `quality.py` ContentQualityChecker，在 LLM 评估前用纯代码检查数据完整性：
  - 逐类内容完整率（资讯/公告/文章/讨论）
  - 财务数据 7 字段填充率
  - 健康分 < 70 直接定向重爬，跳过 LLM（省 token）
- **影响**：减少无效 LLM 调用约 30%，新增 15 个测试

### ADR-008：financial-sdk 替换 AkShare

- **时间**：2026-05-24
- **背景**：AkShare 在中国大陆外网络不稳定，且依赖多个 C 扩展
- **决策**：改用 financial-sdk CLI 获取财务指标（毛利率/净利率/ROE/ROIC/增速）
- **替代方案**：雪球 API 作为备选（ROE fallback）
- **影响**：减少外部依赖，提升财务数据稳定性

### ADR-009：配置目录标准化 ~/.xueqiu_crawler/

- **时间**：2026-03-14
- **背景**：cookies 和凭据分散在不同路径，首次使用需手动创建
- **决策**：统一到 `~/.xueqiu_crawler/`，提供 `XueqiuStockCrawlerV2.init()` 自动创建配置
- **影响**：路径硬编码问题仍有，未做平台兼容

---

## 🚀 功能特性

| ID | 名称 | 状态 | 版本 | 描述 |
|----|------|------|------|------|
| F-001 | 雪球股票详情页爬虫 | ✅ 完成 | V1 | Playwright 获取讨论、资讯、公告、专栏文章 |
| F-002 | 雪球 API 财务数据 | ✅ 完成 | V1 | PE/PB/ROE/市值/52 周高低 |
| F-003 | AkShare/financial-sdk 财务补充 | ✅ 完成 | V1→V3 | 毛利率/净利率/营收利润增速（V3 替换为 financial-sdk） |
| F-004 | LLM 投资分析报告 | ✅ 完成 | V2 | 双 Prompt：评估充分性 + 深度分析，8 主题打分 |
| F-005 | 多轮智能迭代爬取 | ✅ 完成 | V2.1 | 最大 10 轮，评分≥150 提前终止 |
| F-006 | 分项 Token 统计 | ✅ 完成 | V2.1 | 文章/讨论/资讯/公告 各自 Token 统计 |
| F-007 | 资讯正文内容爬取 | ✅ 完成 | V2.1 | 资讯 Token 从 5K 提升到 34K |
| F-008 | 多年 ROIC 财务趋势 | ✅ 完成 | V2.2 | 5 年 ROIC、NOPAT、投入资本 |
| F-009 | Gist 同步 + 飞书推送 | ✅ 完成 | V2 | 自动上传报告并推送 |
| F-010 | 爬虫通用化 v2.1 | ✅ 完成 | V2.1 | 配置目录统一到 `~/.xueqiu_crawler/` |
| F-011 | 数据质量检查器（Layer 1） | ✅ 完成 | V3 | `quality.py` 硬指标检测（内容完整率/财务填充率/健康分） |
| F-012 | Layer 2 LLM 充分性评估 | ✅ 完成 | V2 | evaluator.py 8 主题打分，≥150 通过 |
| F-013 | V3 标准包结构 | ✅ 完成 | V3 | `src/xueqiu_analyzer/` + `pyproject.toml` + Click CLI |
| F-014 | 公告详情页 PDF | ✅ 完成 | V2.2 | 读取公告 PDF 原文链接和正文 |
| F-015 | financial-sdk 集成 | ✅ 完成 | V3 | 替换 AkShare，获取毛利率/净利率/ROE/ROIC |
| F-016 | 纯 API 模式爬虫 | ❌ 已回滚 | — | 尝试替代 Playwright 但丢失社区讨论数据 |
| F-017 | 单元测试 | ✅ 完成 | V3 | 51 个测试：quality/evaluator/config/模型序列化 |

### 版本演进

| 版本 | 时间 | 亮点 |
|------|------|------|
| V1 | 2026-03-05 | 初始版本：基础爬虫 + GLM-5 分析 |
| V2 | 2026-03-06 | Playwright 爬虫 + 双 Prompt + 财务数据 |
| V2.1 | 2026-03-07 | 多轮迭代（10轮）+ 评分≥150终止 + Token 统计 |
| V2.2 | 2026-03-08 | 多年 ROIC 趋势 + 财务数据加分项 |
| v2.1 (refactor) | 2026-03-14 | 配置目录统一 + 首次自动初始化 |
| Fix series | 2026-03-27 | API 配置修复 × 5、模型名称调整 |
| V2.2.1 | 2026-05-24 | 代码审查修复：删除 archive（1302行）、统一 LLM 客户端、修复硬编码 |
| V3.0 (#2 #3) | 2026-05-24 | Layer 1 硬指标 + financial-sdk 替换 + 包结构重构 |
| V3.0.1 | 2026-05-25 | 代码审查清理：未使用 import、空 f-string、异常日志、max_tokens 修复 |

---

## 🐛 Bug 跟踪

| ID | 症状 | 根因 | 修复状态 | 修复 commit | 说明 |
|----|------|------|----------|------------|------|
| B-001 | 文章收集不全 | 只检查特定格式链接 | ✅ 已修复 | `4a62e5f` | 遍历所有链接找文章格式 |
| B-002 | 资讯链接解析错误 | 页面 DOM 结构变动 | ✅ 已修复 | `2b2d9e9` | 修复链接提取逻辑 |
| B-003 | 财务数据未集成到全流程 | `run_analysis.py` 未调用 fetcher | ✅ 已修复 | `cd8d5ab` | 串联爬虫→财务→报告 |
| B-004 | 文章类型数据缺失 | 爬取后未提交文章到模型 | ✅ 已修复 | `14a287d` | 补充文章提交逻辑 |
| B-005 | API 调用超时（10分钟） | 单次 Prompt 生成超时 | ✅ 已修复 | `5828512` | 超时延长到 30 分钟 |
| B-006 | 多页数据重复 | 不同轮次爬取内容未去重 | ✅ 已修复 | `d4d6928` | 按类型分别去重（CrawlResult.merge） |
| B-007 | 配置中 `${BAILIAN_API_KEY}` 为字符串 | YAML 不自动做环境变量插值 | ✅ 已修复 | `b97574c` | 显式读取 `os.environ.get()` |
| B-008 | API 配置读取异常 | `openclaw.json` provider 名称变更 | ✅ 已修复 | `d911813` | 遍历多个 provider 名称 |
| B-009 | 模型名称不匹配百炼 | 百炼不支持旧模型名 | ✅ 已修复 | `8c91d34` | 使用 `qwen-plus` |
| B-010 | 硬编码 TCOM 修正 | 正则写死股票代码 | ✅ 已修复 | `64d0bde` | 代码审查 P0 修复 |
| B-011 | `bare except: pass` | 2 处裸异常捕获 | ✅ 已修复 | `64d0bde` | 代码审查 P1 修复 |
| B-012 | `debug_news_notices.py` 语法错误 | shebang/import/路径字符串 | ✅ 已修复 | `64d0bde` | 代码审查 P0 修复 |
| B-013 | max_tokens 0 被当作 falsy 覆盖 | `max_tokens or config` 逻辑 | ✅ 已修复 | `1f8ca71` | 改为 `max_tokens is not None` |
| B-014 | openclaw.json 异常静默吞 | `except Exception: pass` 无日志 | ✅ 已修复 | `1f8ca71` | 改为 `logger.debug(...)` |

---

## 🔧 技术债务

| ID | 类型 | 描述 | 优先级 | 状态 | 影响范围 |
|----|------|------|--------|------|----------|
| TD-001 | 废弃代码 | `scripts/` 目录 V2 代码（DEPRECATED.md 已声明） | P0 | 🟡 部分解决 | 可维护性 |
| TD-002 | 职责重叠 | V2 `stock_crawler_v2.py` 与 V3 `crawler.py` 爬取逻辑重叠 | P0 | 🟡 部分解决 | 可维护性（V3 已迁移，V2 未删） |
| TD-004 | 硬编码路径 | cookie 路径 `~/.xueqiu_crawler/` 硬编码 | P1 | 🔴 未解决 | 平台兼容 |
| TD-005 | 入口缺失 | `scripts/run_analysis.py` 无 `if __name__` | P1 | ✅ 已解决 | V3 已废弃 |
| TD-006 | 错误处理薄弱 | `crawl()` 失败时行为不明确 | P1 | 🟡 部分解决 | V3 已改善，但仍有改进空间 |
| TD-007 | 零测试覆盖 | V2 无测试 | P1 | ✅ 已解决 | V3 有 51 个测试 |
| TD-008 | 临时文件堆积 | `data/reports/` 无清理机制 | P2 | 🔴 未解决 | 维护性 |
| TD-009 | 日志未统一 | V2 混用 print/logging | P2 | 🟡 部分解决 | V3 已统一使用 logging |
| TD-010 | API Key 回退链过长 | 多种回退路径 | P2 | 🟡 部分解决 | V3 简化了但仍有 5 种 |
| TD-011 | max_tokens falsy | `max_tokens or 8000` 将 0 当 falsy | P2 | ✅ 已解决 | 1f8ca71 |
| TD-012 | 静默吞异常 | `_load_openclaw_provider` 无日志 | P2 | ✅ 已解决 | 1f8ca71 |

---

## ✅ 待办事项

| ID | 描述 | 优先级 | 关联 |
|----|------|--------|------|
| TODO-001 | 清理 `scripts/` 废弃 V2 代码 | P0 | TD-001 |
| TODO-002 | 删除 `data/reports/` 过期的临时报告文件 | P2 | TD-008 |
| TODO-003 | 简化 API Key 回退链（保留 2-3 种） | P2 | TD-010 |
| TODO-004 | 增加爬虫单元测试（mock Playwright） | P1 | 测试覆盖缺口 |
| TODO-005 | 增加 orchestrator 流程测试 | P1 | 测试覆盖缺口 |
| TODO-006 | 增加 financial_fetcher fallback 测试 | P1 | 测试覆盖缺口 |
| TODO-007 | 检查 `_refresh_cookies()` 中 `subprocess.check_output` 路径硬编码 | P2 | 稳定性 |

---

## 📊 代码质量

> 评估日期：2026-05-25 — 基于 V3 架构审查，含本次 code review 结果。

### 总览

| 维度 | 评分 | 上次(05-24) | 变化 | 说明 |
|------|------|-------------|------|------|
| **架构** | 8/10 | 6/10 | +2 | V3 重构：标准包结构、分层清晰（Layer 1→Layer 2）、职责解耦 |
| **代码质量** | 7/10 | 5/10 | +2 | 清理 18 处未使用 import、修复空 f-string、bare except 加日志 |
| **工程化** | 6/10 | 3/10 | +3 | pyproject.toml、pytest 51 tests、Click CLI、日志统一 |
| **可维护性** | 6/10 | 5/10 | +1 | 模块文件减少 40%、import 图清晰、数据模型统一 |
| **安全** | 5/10 | 5/10 | — | cookies 明文存储、凭据固定路径但环境变量隔离 |
| **整体** | **6.4/10** | 4.8/10 | +1.6 | V3 重构和代码审查清理效果显著 |

### 模块逐个评分

| 模块 | 架构 | 可读性 | 错误处理 | 可测试性 | 总分 |
|------|------|--------|----------|----------|------|
| `models.py` | 9 | 9 | 8 | 9 | 8.8 |
| `config.py` | 7 | 7 | 6 | 8 | 7.0 |
| `quality.py` | 8 | 8 | 7 | 9 | 8.0 |
| `llm_client.py` | 7 | 7 | 6 | 7 | 6.8 |
| `evaluator.py` | 7 | 7 | 6 | 7 | 6.8 |
| `analyzer.py` | 7 | 7 | 5 | 6 | 6.3 |
| `orchestrator.py` | 8 | 7 | 6 | 6 | 6.8 |
| `crawler.py` | 6 | 5 | 5 | 2 | 4.5 |
| `financial_fetcher.py` | 7 | 7 | 6 | 6 | 6.5 |
| `cli.py` | 7 | 7 | 6 | 5 | 6.3 |

---

## 🔄 版本记录

### v3.0.1 (2026-05-25) — 代码审查清理

**Commit**：`1f8ca71`（PR #4 — squash merge into main）

**修复**：
- 🐛 `max_tokens or config['max_tokens']` 将 0 当 falsy → 改为 `is not None`
- 🐛 `_load_openclaw_provider` 静默吞异常 → 加 `logger.debug()`
- 🔧 移除 8 个文件中 18 处未使用 import（json, typing.Any/Dict/List/Optional, datetime, shutil, FinancialData）
- 🔧 修复 4 处空 f-string（改为普通字符串）

**验证**：
- ✅ 51 个测试全部通过
- ✅ pyflakes 零告警

### v3.0.2 (2026-05-25) — 数据质量修复（资讯免责声明过滤 + 股价选择器兼容）

**Commit**：`f58e9f4`（PR #6 — squash merge into main，closes #5）

**修复**：
- 🐛 资讯正文全部为免责声明 — 新增 `_is_disclaimer()` 免责声明关键词过滤，提取后跳过无用内容
- 🐛 股价/涨跌未提取 — 股价选择器从单一 `.stock-current` 扩展为 5 个备选，涨跌幅新增 4 个备选
- 🐛 质量检测器盲区 — `_has_real_content()` 同时检查长度 + 实质内容，免责声明无法逃逸 Layer 1 检测

**验证**：
- ✅ 51 个测试全部通过
- ✅ pyflakes 零告警

### v3.0.0 (2026-05-24) — V3 架构重构 + Layer 1 硬指标

**PR #3**：`152d8d2` — Layer 1 数据质量硬指标检测器

**新增**：
- ✨ `quality.py` ContentQualityChecker：纯代码硬指标检测（不消耗 LLM token）
  - 逐类内容完整率（资讯/公告/文章/讨论）
  - 财务数据 7 字段填充率
  - 爬取健康分 0-100（< 70 触发定向重爬）
  - 定向重爬建议（新闻/公告/文章）
- 🧪 15 个 quality 测试（共 51 个）
- 📝 SKILL.md V3 完整重写

**PR #2**：`f3d8b91` — 爬取质量提升 + financial-sdk 替换

**变更**：
- 🔧 financial-sdk 替换 AkShare（减少外部依赖）
- 🔧 V3 标准 Python 包结构 `src/xueqiu_analyzer/`
- 🔧 `pyproject.toml` 构建配置
- 🔧 分层架构（Layer 1 → Layer 2）
- 🔧 废弃 `scripts/` 目录（DEPRECATED.md）

**文档更新**：
- 📚 README.md 重写（架构/数据流/执行流）
- 📚 CODE_REVIEW.md 更新
- 📚 PROJECT_LOG.md 首次创建

### v2.2.1 (2026-05-24) — 代码审查修复

**Commit**：`64d0bde`

**P0 修复**：
- 删除 scripts/archive/ 废弃代码（1302 行）
- 修复 debug_news_notices.py shebang/import/路径字符串错误
- 提取共享 LLMClient 类，统一模型名 glm-5 和 API Key 回退链
- 修复 stock_crawler_v2.py L696 中硬编码 TCOM 的正则

**P1 修复**：
- Gist 上传增加 shutil.which('gh') 检查，细分异常类型
- 统一 LLM 调用错误处理为 LLMError
- 消除 stock_crawler_v2.py 中 2 处 bare except: pass

**P2 修复**：
- login_xueqiu.py Chrome 路径跨平台检测
- report_generator.py 异常重抛保留原始异常链

### v2.2.0 (2026-03-08) — 多年 ROIC 集成

**已打标签**：V2.2 系列 commit

```
e880ad4 feat: V2.2 - 多年ROIC财务数据集成
7c80f12 feat: V2.2 with multi-year ROIC and financial data
```

**新增**：
- 集成 akshare_service 获取 5 年 ROIC 趋势数据
- 财务数据加分项（有多年数据 +10 分）
- Prompt 2 财务质量章节添加 ROIC 趋势分析
- 报告末尾追加 ROIC 表格附录

### v2.1.0 (2026-03-07) — 智能迭代爬取

**已打标签**：V2.1 系列 commit

```
46f4c91 feat: 添加完整评估报告生成
5828512 fix: 修复API超时问题
d4d6928 feat: V2.1 - 最大10轮/30分钟超时/分项Token统计
208c138 feat: V2.1 优化调整
bb5857f feat: V2.1验证成功
8ba348e feat: 资讯内容爬取（Token 5K→34K，评分→160）
```

**新增**：
- 最大爬取轮次：3 轮 → 10 轮
- API 超时时间：10 分钟 → 30 分钟
- 提前终止条件：评分 ≥ 150 分
- 分项 Token 统计（文章/讨论/资讯/公告）
- 完整评估报告（含爬取内容清单）
- 资讯正文爬取，Token 从 5K 增加到 34K

**Bugs 已修复**：
- API 超时中断
- 文章类型未提交到模型
- 分页数据重复
- 资讯链接缺失

### v2.0.0 (2026-03-06) — Playwright 重构

**已打标签**：V2 系列 commit

```
700d554 feat: 添加雪球股票详情页爬虫v2
c1b0a62 feat: 集成新版爬虫到全流程分析
```

**重大变更**：
- 爬虫从 requests 重构为 Playwright 全浏览器自动化
- 解决登录弹窗拦截、Tab 切换遮罩
- 支持多页滚动加载和去重累积
- 全流程自动化（run_analysis.py）

### v1.0.0 (2026-03-05) — 初始版本

**已打标签**：V1 系列 commit

```
53bb6fb initial commit
1259851 feat: 添加雪球股票数据爬虫
a548847 feat: 添加雪球API财务数据获取
9692b46 fix: 爬虫路径
```

**里程碑**：项目启动，首个爬虫 + 财务数据 + 分析报告
