# 雪球股票分析 Skill — 项目跟踪日志

> 最后更新：2026-10-05  
> 版本：V4.3  
> 最近一次 `LAST_ANALYZED`：`48ab818`
> 分析范围：全部历史 commit（149 个）

<!-- @@LAST_ANALYZED: 48ab818 @@-->
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
| 爬虫引擎 | `crawler.py` | 1688 | Playwright + 雪球 API 混合爬虫：讨论/资讯/公告/文章 + 互动量提取 |
| 爬虫引擎（反检测） | `crawler_nodriver.py` | 570 | nodriver 反检测爬虫：绕过阿里云 WAF 滑动验证，Tier 1 引擎，失败回退 playwright |
| 评估器 | `evaluator.py` | 281 | Layer 2 LLM 信息充分性评估（8 主题打分） |
| 分析器 | `analyzer.py` | 202 | 深度投资分析报告生成（LLM Prompt） |
| LLM 客户端 | `llm_client.py` | 170 | 统一 LLM 调用封装（chat/evaluate/analyze/simple_chat） |
| 财务获取 | `financial_fetcher.py` | 252 | 雪球 API + financial-sdk CLI 双源财务数据 |
| 配置加载 | `config.py` | 93 | YAML + 环境变量 + openclaw.json fallback 链 |
| 数据模型 | `models.py` | 281 | CrawlResult/EvaluationResult/FinancialData 等 dataclass |
| CLI 入口 | `cli.py` | 251 | Click 命令行接口（analyze/crawl/evaluate/reanalyze/cookies） |
| 风控判定 | `waf.py` | 190 | 风控页判定唯一实现：is_error_page / is_waf_blocked / classify_failure / needs_login / has_waf_marker |
| 限速器 | `opencli_rate_limiter.py` | 151 | 跨进程随机限速：状态文件调度命令起始时间，默认间隔 6–12 秒 + 每 30 次 45–75 秒长停 |
| 调用台账 | `opencli_call_logger.py` | 152 | opencli 每次调用追加 JSONL 台账（含 throttle 等待/预留时长 + expect_miss 探针标记），供峰值复盘 |

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
| nodriver | 反检测爬虫引擎（绕过 WAF 滑动验证） |
| DeepSeek / GLM (LLM) | AI 评估+分析引擎 |
| 雪球 API | 实时股票报价 |
| financial-sdk | 财务指标（毛利率/净利率/ROE/ROIC） |
| PyYAML | 配置文件 |
| Click | CLI 框架 |
| urllib | HTTP 请求 |
| pytest | 单元测试（282 个） |
| GitHub Actions | CI：push/PR/manual 触发 pytest |

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

### ADR-010：失败日志天级轮转（不做大小截断）

- **时间**：2026-10-01
- **背景**：`record_source_failure` 只追加不清理，`logs/source_failures.jsonl` 无限增长；monitor 的 health_check 每次全量读取该文件过滤当天记录，文件越大越慢，历史失败永久堆积
- **决策**：新增 `_rotate_fail_log()`，仅在「文件最后写入日 < 今天」时轮转 —— 旧文件归档到 `logs/source_failures/YYYY-MM-DD.jsonl`，默认保留 30 天
- **关键约束**：刻意不做按大小截断 —— 轮转只发生在跨天时，同一天内不动文件，保证读取方（health_check / cli）仍只需读固定路径即可拿到当天全部记录
- **替代方案**：按文件大小截断（truncate）—— 被否决，因为会丢掉当天早期失败记录，重新触发「静默无失败」类 bug
- **影响**：`fetcher_opencli.py` 新增 `_rotate_fail_log()` + `FAIL_ARCHIVE_KEEP_DAYS=30`；写失败仍不影响主流程

### ADR-011：风控页判定收为唯一实现（waf.py）

- **时间**：2026-10-01
- **Commit**：`da91358`
- **背景**：雪球被风控拦下时返回「验证页」而非 HTTP 错误，认不出来就被当成「这只股票确实没有数据」→ 静默数据丢失。判定逻辑散落在 3 个仓库 8 处，关键词集合已漂移，同一页在不同环节结论不同。具体分歧：
  - `crawler_nodriver._is_content_error` 大小写敏感 vs `opencli_extractor._is_error_page` 先 `.lower()` → 「Request has been blocked」能被重试逻辑抓到、却写进磁盘
  - `opencli_extractor` 把 `"405"` 当正文子串匹配 → 任何开头 500 字含 405 的正常文章都被误判并重试
  - `crawler_nodriver` 同一文件里 `_detect_waf` 查 `aliyun_waf` 标记、`_is_content_error` 不查 → 两函数把同一页判成不同结果
  - `analyzer/crawler._check_login_status` 拿风控关键词判断登录态 → 风控页被误读成「未登录」
- **决策**：新增 `src/xueqiu_analyzer/waf.py` 作为唯一实现，把三个不同问题显式分开：
  - `is_error_page`（丢弃/过滤）
  - `is_waf_blocked`（重试/重启浏览器）
  - `classify_failure`（失败归类）
  - 登录墙单列 `needs_login`，不再与风控混用
  - 权威模式表集中管理：`TITLE_EXACT`（405/403/滑动验证页面，标题精确匹配）、`CONTENT_PATTERNS`（11 个，大小写不敏感）、`PAGE_MARKERS`（aliyun_waf）、`AUTH_REQUIRED_PATTERNS`（登录墙）
- **跨仓库一致性**：opencli 适配器（`xueqiu-crawler/opencli-adapters/*.js`）由 `sync_waf_patterns.py` 从本模块生成 `BLOCK_GUARD` 正则，并有漂移测试卡住两边不各走各的
- **影响**：`fetcher_opencli._classify_reason` → `waf.classify_failure`；`crawler._check_login_status` → `waf.contains_waf_text`（返回值语义保留）；新增 39 条回归测试，全量 248 passed

### ADR-012：opencli 限速默认参数作为「策略决定」显式固定

- **时间**：2026-10-05
- **Commit**：`4a404be`
- **背景**：限速参数（间隔/长停）原本是 `_env_*` 调用里的字面量默认值，既没说明「为什么是这个值」，也没有东西阻止它们被无意识改掉；12–24 秒的默认间隔缺乏证据支撑（2026-10-05 被风控拦截那次是当天第一次调用，此前 14 小时调用数为 0），却把爬取拖慢一倍
- **决策**：五个默认值抽成具名常量 `DEFAULT_*`，注释写明它们是**策略决定**而非实现细节，并记下「为什么是 6–12」的推理（均值 9 秒 → 峰值上限 ≈ 6.7 次/分，仍低于修复 browser open 限速前的 10 次/分实测值）
- **锁定机制**：`test_default_interval_policy_is_pinned` 锁住策略值（要调参就得连同测试一起改，杜绝静默漂移）；`test_default_band_used_when_env_absent` 确认无环境变量时预定间隔落在默认 band 内
- **影响**：默认间隔 12–24 → 6–12 秒（130 次调用预计从 43 分钟缩到 24 分钟）；全部仍可用 `XUEQIU_OPENCLI_*` 环境变量覆盖，无需改代码

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
| F-018 | opencli 调用台账 | ✅ 完成 | V4.3 | 每次 opencli 调用追加 JSONL 日志（含 throttle 等待/预留时长），支持峰值复盘 |
| F-019 | opencli 随机限速 | ✅ 完成 | V4.3 | 跨进程随机限速：状态文件调度命令起始时间，默认间隔 6–12 秒 + 每 30 次 45–75 秒长停 |
| F-020 | 台账「预期未命中」标记 | ✅ 完成 | V4.3 | record_opencli_call 支持 expect_miss，把探针序列与真失败分开，避免假警报淹掉真失败 |

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
| V4.2.0 | 2026-10-01 | 风控页判定收为唯一实现 waf.py + 39 条回归测试 |
| V4.3.0 | 2026-10-04 | opencli 调用台账 + 跨进程随机限速（默认间隔 6–12 秒） |

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
| B-015 | 互动量全为零（like/comment/forward） | 4 处 Discussion 构造路径均未填充互动字段，dataclass 默认 0 | ✅ 已修复 | `3c273e0` | 为 API/opencli/HTML 三条路径全部补抓互动量，新增 5 个测试 |
| B-016 | source_failures.jsonl 无限增长 | record_source_failure 只追加不清理，无轮转/归档机制 | ✅ 已修复 | `38a482b` | 新增 `_rotate_fail_log()` 跨天归档到 `logs/source_failures/YYYY-MM-DD.jsonl`，保留 30 天；同天内不动文件 |
| B-017 | crawler_nodriver.py 误归档 → monitor 静默回退 playwright | 归档判定仅 grep 本仓库，未发现 xueqiu-monitor 的跨仓库引用；monitor 的 import 被 try/except 包住，失败不报错 | ✅ 已修复 | `843f9a1` | 文件移回 `src/xueqiu_analyzer/`、删除 archive/ 目录；nodriver 能过 WAF 滑动验证而 playwright 不能，回退即丢数据 |
| B-018 | 风控页被误判为「无数据」导致静默数据丢失（隐患） | 风控页判定散落 3 仓库 8 处，关键词漂移；405 正文子串误判、大小写不一致、风控与登录态混用 | ✅ 已修复 | `da91358` | 收为唯一实现 waf.py，三问题显式分离，39 条回归测试 |
| B-019 | 「405 Forbidden」错误页漏检（标题正常、正文含 405 形态） | da91358 把 405 从正文匹配整个去掉，导致「标题正常、正文写着 405 Forbidden」的错误页漏判为正常文章 | ✅ 已修复 | `a9b42ab` | 并入 PR #54 收紧：裸「405」不做子串匹配，但认「405 forbidden / http 405 / 405 not allowed」三种形态，兼顾两边 |
| B-020 | extractor 缺 key 时静默 401，日志语焉不详 | `DEEPSEEK_API_KEY` 在导入时读成模块常量；key 为空仍发 `Authorization: Bearer ` 空请求换 401；`python-dotenv` 缺失被 `except ImportError: pass` 静默吞掉 | ✅ 已修复 | `2e04064` | 新增 `MissingCredentialError` + `_deepseek_api_key()` 调用时读取，缺失抛带修复指引的错误；dotenv 缺失改 `logger.warning` |
| B-021 | 人工验证页漏检（check.xueqiu.com/captcha） | waf 模式表缺「访问触发保护 / 完成人机验证」两条文案，实测验证页未命中旧模式 | ✅ 已修复 | `0dbc58f` | CONTENT_PATTERNS 补 2 条 + 回归测试 |
| B-022 | browser open 从未被限速（限速覆盖仅 ~13%） | `_should_throttle` 对 browser 判定写成 `values[3] == "open"`，而 values[3] 是 URL，永不成立 → 最重的页面导航漏限速 | ✅ 已修复 | `73c91b1` | 下标 values[3]→values[2]；新增 2 条测试枚举各命令判定 |
| B-023 | 探针未命中被误报为失败（browser:extract 假警报「75% 失败」） | detail_fetcher 按精确度顺序试 8 个正文选择器，未命中 rc=2 是正常探测，台账却把每条 rc=2 当失败统计——两次抓取都成功却被报成多数失败 | 🟡 部分修复 | `48ab818` | logger 侧能力就绪（expect_miss 标记），但调用方未接线，见 TD-018 / TODO-009 |

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
| TD-013 | 跨仓库引用不可见 | 归档判定仅 grep 单仓库，未覆盖外部 consumer（xueqiu-monitor），导致误归档 | P2 | 🟡 部分解决 | 归档决策流程需纳入跨仓库引用检测 |
| TD-014 | 语义遗留 | `_check_login_status` 遇风控页返回 False，调用方走登录流程而非退避等待（作者注释标注的既有行为） | P2 | 🔴 未解决 | 稳定性 |
| TD-015 | 模式表漂移 | `crawler_nodriver._detect_waf` 仍用本地 `_WAF_CONTENT_PATTERNS=("aliyun_waf","_waf_","renderData")`，与 `waf.PAGE_MARKERS=("aliyun_waf",)` 已漂移；`has_waf_marker` 已抽出但尚未接线 | P1 | 🔴 未解决 | 稳定性 |
| TD-016 | 配置读取两套机制 | `extractor.py` 直读 `os.environ['DEEPSEEK_API_KEY']` + 硬编码项目根 `.env` 路径并自行 `load_dotenv`，与 `config.py` 的 `_resolve_env`（支持 `${VAR}` 插值 + ARK/BAILIAN/DASHSCOPE/openclaw 回退链）是两套不互通的机制 | P2 | 🔴 未解决 | 配置一致性 |
| TD-017 | 敏感信息残留历史 | `.deepseek/state/subagents.v1.json` 含完整 agent 运行记录（prompt/result/绝对路径），`git rm --cached` 只停止跟踪工作树、不清理 git 历史；若仓库公开需 `git filter-repo` 重写历史 | P2 | 🔴 未解决 | 隐私/安全 |
| TD-018 | expect_miss 未接线 | `record_opencli_call` 的 `expect_miss` 参数与 2 个测试已就绪，但生产调用方（`detail_fetcher.fetch_page_opencli` 探针序列）未传 `expect_miss=True`，台账假警报能力到位但尚未生效 | P1 | 🔴 未解决 | 可观测性 |

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
| TODO-008 | `crawler_nodriver._detect_waf` 改用 `waf.has_waf_marker`，删除本地漂移模式表 `_WAF_CONTENT_PATTERNS` | P1 | TD-015 |
| TODO-009 | `detail_fetcher.fetch_page_opencli` 探针序列接线 `expect_miss=True` | P1 | TD-018 |

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

### v4.3.3 (2026-10-05) — 台账支持「预期未命中」标记

**Commit**：`48ab818`

**变更**：
- ✨ `record_opencli_call` 新增 `expect_miss: bool = False`：标记「探针序列」中非零退出是正常结果而非错误
- 🔧 `ok` 仍如实反映退出码（不被改写），`expect_miss` 只多带解释标记；且只在为真时写字段（避免台账每行都加字段，台账涨到 20MB 才轮转）
- 🧪 新增 2 个测试：`test_expect_miss_marks_probe_but_keeps_ok_faithful`、`test_expect_miss_absent_by_default`

**动机**：detail_fetcher 按精确度顺序试 8 个正文选择器，没命中就 continue，命中到 300 字才 break；两个页面各留 3 条 rc=2，台账把 browser:extract 报成「75% 失败」——其实两次抓取都成功，只是各探测 3 次，假警报会淹掉真失败。

**遗留**：生产调用方 `detail_fetcher.fetch_page_opencli` 尚未接线 `expect_miss=True`（见 TD-018 / TODO-009），台账假警报能力就绪但未生效。

**验证**：✅ 台账相关测试通过；`opencli_call_logger.py` 139 → 152 行

### v4.3.2 (2026-10-05) — 限速默认间隔调优 12–24 → 6–12 秒

**Commit**：`4a404be`

**变更**：
- 🔧 `opencli_rate_limiter.py` 五个默认值抽成具名常量 `DEFAULT_*`，注释写明「策略决定 + 为什么是 6–12」的推理
- 🔧 默认间隔 12–24 → 6–12 秒（均值 9 秒 → 峰值上限 ≈ 6.7 次/分，仍低于修复 browser open 限速前的 10 次/分实测）
- 🧪 新增 `test_default_interval_policy_is_pinned` + `test_default_band_used_when_env_absent` 锁住策略

**动机**：被风控拦截那次是当天第一次调用（此前 14 小时调用数为 0），说明拦截并非即时频率所致，把间隔翻倍收益存疑；收到 6–12 秒后按 130 次调用估算从 43 分钟缩到 24 分钟。全部仍可用 `XUEQIU_OPENCLI_*` 覆盖。

**验证**：✅ pytest 280 passed；实测 8 次预定间隔 10.0/11.5/6.5/9.9/10.7/7.1/10.4 秒

### v4.3.1 (2026-10-05) — 限速修复：人工验证检测 + browser open 漏限速

**Commit**：`0dbc58f` / `cc05f39` / `73c91b1`

**修复**：
- 🐛 `0dbc58f` 人工验证页漏检：`waf.CONTENT_PATTERNS` 补「访问触发保护」「完成人机验证」，命中 check.xueqiu.com/captcha 实测文案
- 🐛 `cc05f39` 限速范围收紧：`acquire_opencli_slot` 新增 `_should_throttle(args)`，只限速会发起雪球请求的命令（xueqiu 非 help / browser open），get/extract/close 本地交互不限速
- 🐛 `73c91b1` browser open 从未被限速：判定下标 `values[3]` → `values[2]`（values[3] 是 URL，永远不等于 "open"）；此前限速只覆盖约 13% 流量（130 次里仅 user-articles 的 17 次被限速），漏掉的恰是最重的页面导航

**验证**：✅ pytest 278 passed；真实 argv 复验 browser open → 限速=True

### v4.3.0 (2026-10-04) — opencli 调用台账 + 随机限速

**Commit**：`be414d8` / `d92ffff`

**新增**：
- ✨ `opencli_call_logger.py`（139 行）：每次 opencli 调用追加一条 JSONL 台账（命令/开始时间/结果/错误/调用方），`record_opencli_call` 支持 `throttle` 字段记录等待与预留时长
- ✨ `opencli_rate_limiter.py`（151 行）：跨进程随机限速器，状态文件（`~/.opencli/xueqiu-throttle.json` + `.lock`）调度命令**起始时间**，锁只在预留时持有、sleep 在释放后进行，避免长命令阻塞无关爬取
- 🔧 `fetcher_opencli._run` 接入两模块：先 `acquire_opencli_slot` 再执行，`record_opencli_call` 带上 throttle 数据

**验证**：✅ pytest 新增 5 个测试（限速 3 + 台账 2），全量通过

### v4.2.5 (2026-10-02) — 停止跟踪 .deepseek/ 运行期状态

**Commit**：`2c87ed4`

**变更**：
- 🔨 `.gitignore` 新增忽略 `.deepseek/`（DeepSeek TUI 自动生成的运行期状态）
- 🔨 `git rm --cached` 停止跟踪两个运行期状态文件（磁盘文件保留）：
  - `.deepseek/instructions.md`（61 行）—— 自动生成的目录树，文件头写明「可随时删除」
  - `.deepseek/state/subagents.v1.json`（52 行）—— 过去 agent 运行记录，含完整 prompt / result / evidence 与绝对路径

**动机**：这类运行期状态不该进版本库（同理于 `__pycache__`、`.pytest_cache`），五月起已停止更新，属历史残留。含完整 prompt 与绝对路径的 agent 运行记录进版本库有隐私/安全暴露风险。

**影响**：仓库不再跟踪 `.deepseek/` 运行期状态，无代码行为变更。

### v4.2.4 (2026-10-01) — extractor 缺 key 时报可操作错误

**Commit**：`2e04064`

**修复**：
- 🐛 `extractor.py` 在 `DEEPSEEK_API_KEY` 缺失时静默发出 `Authorization: Bearer ` 空请求，换回语焉不详的 `HTTP Error 401` —— 排查方向被带偏到网络/额度，而非配置
- 🐛 `python-dotenv` 未安装时 `except ImportError: pass` 静默吞掉，`.env` 从未被加载、key 恒为空 —— 正是 2026-06-08 的事故（见 DAILY_LOG.md）→ 改为 `logger.warning` 显式提示

**变更**：
- ✨ 新增 `MissingCredentialError(RuntimeError)`：凭证未配置与「API 调用失败」显式区分
- 🔧 新增 `_deepseek_api_key()`：调用时读取，不再导入时缓存成模块常量（规避 import 顺序与 `.env` 加载先后导致的「环境变量设了却读到空」），缺失则抛带修复指引的错误（读顺序 / 修复方法 / python-dotenv 检查）
- 🔧 `call_deepseek_extract` 在 try 块之外提前校验凭证，缺失时不再发任何请求
- 🧪 `test_extractor.py` 新增 autouse fixture 显式提供凭证 + 2 个回归测试（缺失抛可操作错误、缺失不触网）

**验证**：✅ pytest 268 passed

### v4.2.3 (2026-10-01) — 添加 GitHub Actions CI

**Commit**：`13b8b31`

**变更**：
- 🔨 新增 `.github/workflows/tests.yml`：GitHub Actions 在 push 到 `main`、PR、手动触发（`workflow_dispatch`）时自动跑 pytest
  - Python 3.11 + pip 缓存 + `pip install -r requirements.txt pytest` + `pip install -e .`
  - 单 job `pytest`，`ubuntu-latest`，超时 15 分钟，`concurrency` 同 ref 并发取消
  - 注释说明：测试 import `xueqiu_analyzer.crawler` 会在模块级 import playwright，但装包即可，无需下载浏览器二进制

**影响**：
- 从「本地手动跑 pytest」升级为「push/PR 自动验证」，工程质量屏障补上（对应「代码质量」板块工程化维度）

### v4.1.2 (2026-10-01) — source_failures.jsonl 天级轮转

**Commit**：`38a482b`

**修复**：
- 🐛 `fetcher_opencli.py` 的 `record_source_failure` 只追加不清理，`logs/source_failures.jsonl` 无限增长 —— monitor 的 health_check 每次全量读取该文件过滤当天记录，文件越大越慢，历史失败永久堆积
- 🔧 新增 `_rotate_fail_log()`：仅在「文件最后写入日 < 今天」时轮转，旧文件归档到 `logs/source_failures/YYYY-MM-DD.jsonl`，默认保留 30 天
- 🧪 `test_source_fail_rotation.py` 新增 7 个测试（同日不动、跨天归档、空文件、文件缺失、过期归档清理、同日追加、跨天轮转）

**关键设计**：
- 刻意不做按大小截断 —— 轮转只发生在跨天时，同一天内不动文件，保证读取方（health_check / cli）仍只需读固定路径即可拿到当天全部记录，避免「静默无失败」类 bug 复发

**验证**：
- ✅ 全量 pytest 216 passed，无回归

### v4.2.2 (2026-10-01) — 405 匹配收紧（并入 PR #54）

**Commit**：`a9b42ab`

**变更**：
- 🐛 `waf.py` `CONTENT_PATTERNS` 新增 3 条具体形态：`"405 forbidden"` / `"http 405"` / `"405 not allowed"`，裸「405」仍不做正文子串匹配
- 🧪 新增回归测试 `test_specific_405_forms_detected_but_bare_digits_are_not`：具体 405 形态能命中，但「营收 405 亿元」这类正常文章不误判

**动机**：xueqiu-crawler PR #54 对同一 bug 用了「收紧关键词」的办法（405 Forbidden / HTTP 405 / 405 Not Allowed），而本仓库早先（da91358）是「把 405 从正文匹配整个去掉」。两个方案各有盲区：
- 只去掉 → 漏掉「标题正常、正文写着 405 Forbidden」的错误页
- 只收紧 → `http 405` 仍可能（低概率）出现在正常文章里

合并为：裸「405」不做正文子串匹配，但认这三种具体形态，两边的好处都留下。

**验证**：✅ pytest 253 passed

### v4.2.1 (2026-10-01) — 抽出 has_waf_marker 页面标记检查

**Commit**：`bdf4e8b`

**变更**：
- 🔧 `waf.py` 抽出 `has_waf_marker(html)`：整页 HTML 是否含 WAF 注入标记（`aliyun_waf`），大小写不敏感；`is_waf_blocked` 改为复用它，外部行为不变
- 🧪 新增回归测试 `test_has_waf_marker_is_page_wide_and_case_insensitive`：验证「标记查整页 HTML 而非仅头部」+ 大小写不敏感（5000 字之后的大写 `ALIYUN_WAF` 仍能命中，而头部扫描 `contains_waf_text` 看不到）

**动机**：`crawler_nodriver._detect_waf` 需要「整页 HTML 是否含 WAF 标记」这一个判断，但走 `is_error_page` 不合适——那条「空标题算错误页」规则是为过滤坏文章设计的，拿来触发浏览器重启太激进（一次没取到标题就重启不划算）。抽成独立函数后 crawler 侧可直接调它。

**验证**：✅ pytest 249 passed

**遗留**：本提交只完成「抽出」这一步，`crawler_nodriver._detect_waf` 尚未接线（见 TD-015 / TODO-008）。

### v4.2.0 (2026-10-01) — 风控页判定统一重构

**Commit**：`da91358`

**变更**：
- 🔧 新增 `src/xueqiu_analyzer/waf.py`（178 行）：风控页判定的唯一实现
  - `is_error_page`（丢弃/过滤）、`is_waf_blocked`（重试/重启浏览器）、`classify_failure`（失败归类）
  - 登录墙单列 `needs_login`，与风控分离（不再拿风控关键词判登录态）
  - 权威模式表：`TITLE_EXACT`（405/403/滑动验证页面精确匹配）、`CONTENT_PATTERNS`（11 个，大小写不敏感）、`PAGE_MARKERS`（aliyun_waf）
  - `block_guard_js()` 生成 opencli 适配器用的 BLOCK_GUARD 正则，含正则元字符的模式直接抛错
- 🔧 `fetcher_opencli._classify_reason` → `waf.classify_failure`
- 🔧 `crawler._check_login_status` → `waf.contains_waf_text`（返回值语义保留：风控页仍返回 False）
- 🧪 新增 `test_waf.py`（39 条测试），覆盖每处历史分歧的回归断言

**修复的隐患**：
- 🐛 `"405"` 正文子串误判（任何开头 500 字含 405 的正常文章被误判重试）→ 改为标题精确匹配
- 🐛 大小写敏感不一致（「Request has been blocked」能被重试抓到却写进磁盘）→ 统一大小写不敏感
- 🐛 同页不同结论（`_detect_waf` 查标记、`_is_content_error` 不查）→ `is_waf_blocked ⊃ is_error_page` 关系显式化
- 🐛 风控页被误读为「未登录」触发重新登录 → `needs_login` 单独判断

**验证**：
- ✅ pytest 248 passed（新增 39 条 waf 测试）

### v4.1.3 (2026-10-01) — 撤销 crawler_nodriver.py 误归档

**Commit**：`843f9a1`

**修复**：
- 🐛 撤销上一提交（`b815846`）对 `crawler_nodriver.py` 的误归档。归档依据「全仓库 0 处 .py 引用」不成立——该模块被**另一个仓库** `xueqiu-monitor` 的 `src/crawler.py:559` 引用（`from xueqiu_analyzer.crawler_nodriver import XueqiuNodriverCrawler`），是 monitor 的 Tier 1 爬取引擎
  - 引用被 try/except 包裹，归档后不崩，而是每次**静默回退 playwright**
  - 同段代码注释证明 nodriver 能过 WAF 滑动验证、playwright 不能，回退 = 撞滑块 = 丢数据
- 🔨 文件移回 `src/xueqiu_analyzer/crawler_nodriver.py`（纯 rename，内容 100% 不变），删除仅为它建立的 `archive/` 目录

**验证**：
- ✅ `from xueqiu_analyzer.crawler_nodriver import XueqiuNodriverCrawler` 成立
- ✅ pytest 209 passed

### v4.1.1 (2026-08-04) — 互动量数据修复

**Commit**：`3c273e0`

**修复**：
- 🐛 `crawler.py` 4 处 Discussion 构造路径均未填充互动字段（like_count/comment_count/forward_count），导致下游 CSV 导出和内容质量筛选中的互动数据全为零
  - **Path 1&2 (opencli)**：API 返回字段 `likes`/`replies`/`forwards` 未映射到 Discussion
  - **Path 3 (Xueqiu API)**：API 返回字段 `like_count`/`reply_count`/`retweet_count` 未映射
  - **Path 4 (HTML 解析)**：`_parse_single_discussion()` 未从页面 footer 提取「转发 N 回复 N 赞 N」互动数据
- 🔧 `_parse_single_discussion()` 新增正则匹配从 HTML footer 提取互动量：`(?:转发|转发数)\s*(\d+)\s*(?:回复|评论)\s*(\d+)\s*(?:赞|点赞)\s*(\d+)`
- 🧪 `test_crawler.py` 新增 `TestEngagementMetrics` 类（5 个测试），覆盖全部 4 个构造路径 + 默认零值

**影响**：
- `crawler.py`：1655 → 1688 行（+33），`test_crawler.py`：82 → 196 行（+114）
- 下游 CSV 导出和 ContentGrader 评分现在可获得真实互动量数据

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