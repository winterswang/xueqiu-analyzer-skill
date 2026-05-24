# 雪球股票分析 Skill

输入股票代码，输出结构化投资分析报告。

**核心流程**：Playwright 爬取 → 财务数据获取 → GLM-5 AI 分析 → 报告生成 → Gist 同步 + 飞书推送

## 功能

- Playwright 爬取雪球讨论/资讯/公告/文章
- 雪球 API 获取 PE/PB/ROE/市值/52周高低
- AkShare 补充财务数据（毛利率、净利率、ROE）
- 多年 ROIC 计算（投入资本回报率）
- GLM-5 AI 生成结构化投资分析报告
- 智能迭代爬取：最多 10 轮，评分 ≥150 提前终止
- 分项 Token 统计 + Gist 同步 + 飞书推送

## 架构

```
用户输入股票代码（如 00700）
        ↓
stock_crawler_v2.py ──── Playwright 模拟登录 + 讨论/资讯/公告/文章爬取
        ↓
smart_crawler_v2.py ─── 多轮迭代评估（评分 ≥ 150 终止）
        ↓
financial_fetcher.py ── 雪球 API（PE/PB/ROE/市值）+ AkShare（毛利率/净利率）+ akshare_service（多年 ROIC）
        ↓
data_quality_checker.py  内容清洗 + 低质量过滤
        ↓
report_generator.py ──── GLM-5 Prompt 1（评估）+ Prompt 2（深度分析）
        ↓
run_analysis.py ──────── Gist 同步 + 飞书推送
```

## 目录结构

```
xueqiu-analyzer-skill/
├── SKILL.md                # Skill 元数据（v2.2.0）
├── README.md               # 本文档
├── PROJECT_LOG.md          # 项目跟踪日志（ADR / Bug / 技术债务）
├── requirements.txt        # Python 依赖
├── config/
│   ├── config.yaml         # GLM-5 / 爬虫配置
│   ├── target_users.yaml   # 目标用户列表
│   └── cookies/            # 登录凭据
├── scripts/
│   ├── stock_crawler_v2.py   # Playwright 爬虫（1375行）
│   ├── smart_crawler_v2.py   # 智能迭代爬取（1066行）
│   ├── report_generator.py   # GLM-5 调用 + 报告生成（413行）
│   ├── financial_fetcher.py   # 财务数据（302行）
│   ├── data_quality_checker.py # 内容清洗 + 质量过滤（223行）
│   ├── report_template.py   # 报告 Markdown 模板（382行）
│   ├── run_analysis.py     # 全流程编排（164行）
│   ├── analyzer.py         # 主入口（146行）
│   ├── config.py           # 路径/日志配置
│   ├── login_xueqiu.py     # 独立登录脚本
│   ├── debug_news_notices.py
│   ├── get_username.py
│   ├── update_template.py
│   └── (archive/ 已清理，见 v2.2.1)
├── data/reports/           # 分析报告输出
└── logs/
```

## 使用

```bash
# 全流程分析（推荐）
python scripts/smart_crawler_v2.py 00700

# 手动全流程
python scripts/run_analysis.py --symbol 00700

# 只爬数据
python scripts/stock_crawler_v2.py 00700

# 生成报告
python scripts/analyzer.py 00700
```

## 核心模块

| 脚本 | 职责 | 行数 | 质量 |
|------|------|------|------|
| `stock_crawler_v2.py` | Playwright 登录 / Tab 切换 / 滚动加载 / 去重 / 公告详情 | 1375 | ⚠️ 过长 |
| `smart_crawler_v2.py` | 多轮迭代爬取 + Prompt 构建 + LLM 调用 + 报告生成 | 1066 | ⚠️ 与 stock_crawler_v2 重叠 |
| `report_generator.py` | GLM-5 API 调用 + V1 报告生成 | 413 | ⚠️ 模型名与 smart_crawler_v2 不一致 |
| `financial_fetcher.py` | 雪球 API + AkShare + ROIC | 302 | ✅ |
| `run_analysis.py` | 全流程编排 | 164 | ✅ |
| `analyzer.py` | SKILL 入口 | 146 | ✅ |
| `data_quality_checker.py` | 内容清洗 + 低质量过滤 | 223 | ✅ |

---

## 代码质量评估（2026-05-24）

> 基于全部 37 个 commit、6 个核心模块、~3000 行代码的逐文件审查。

### 总览

| 维度 | 评分 | 上次(05-22) | 变化 |
|------|------|-------------|------|
| **架构** | 6/10 | 7/10 | -1 |
| **代码质量** | 5/10 | 6/10 | -1 |
| **工程化** | 3/10 | 4/10 | -1 |
| **可维护性** | 5/10 | 5/10 | — |
| **安全** | 5/10 | — | 新增 |
| **整体** | **4.8/10** | 6/10 | -1.2 |

> 下降原因：逐行审查发现了上次基于文件头扫描未暴露的结构性问题（见下文 P0-1~P0-5）。

### P0 必须修复

#### P0-1：`smart_crawler_v2.py` 与 `stock_crawler_v2.py` 职责严重重叠

两个文件共 2441 行，但存在大量功能重复：
- 两个文件各自包含完整的 LLM 调用逻辑（API Key 回退链、`openclaw.json` 读取）— **70+ 行完全相同的代码**
- `smart_crawler_v2.py` 的 `crawl_round()` (L118) 直接实例化 `XueqiuStockCrawlerV2`，但自身也维护了一套内容合并、去重、Token 统计逻辑
- `smart_crawler_v2.py` 中 `call_llm()` (L535) 和 `report_generator.py` 中 `GLM5Analyzer.analyze()` (L79) 是独立的 LLM 调用实现，且 **模型名不一致**（`glm-5` vs `qwen3.5-plus`）

**建议**：抽取独立 `LLMClient` 类；去除 `smart_crawler_v2.py` 中重复的 API Key fallback 逻辑。

#### P0-2：`report_generator.py` 与 `smart_crawler_v2.py` 模型名不一致

| 文件 | 行号 | 模型名 |
|------|------|--------|
| `report_generator.py` | L85 | `qwen3.5-plus` |
| `smart_crawler_v2.py` | L583 | `glm-5` |

SKILL.md 宣称使用 glm-5，但 `report_generator.py` 实际调用的是 `qwen3.5-plus`，且两个模块通过不同的 `api_url` 端点调用（可能不是同一个服务）。

#### P0-3：`stock_crawler_v2.py` L696 硬编码股票名

```python
title = re.sub(r'^携程\(TCOM\)\d{2}-\d{2}\s*\d{1,2}:\d{2}·\s*来自新闻\s*', '', title)
```

这行在通用爬虫中硬编码了携程(TCOM)，任何其他美股资讯标题都不匹配此正则，导致清洗失效。

#### P0-4：`debug_news_notices.py` 代码错误

```python
import config       # ← 无意义的顶层 import
#!/usr/bin/env python3   # ← shebang 出现在 import 之后
...
with open('str(config.CONFIG_DIR / "xueqiu_cookies.json")', 'r') as f:  # ← 字符串字面量 'str(...)'，永远找不到文件
```

工具脚本本身有语法/逻辑错误，根本不可能运行。

#### P0-5：废弃代码未清理（✅ 已修复）

~`scripts/archive/` 目录下 4 个文件共 **1302 行**：
- `stock_crawler.py` (328行) — V1 爬虫
- `smart_crawler.py` (270行) — V1 智能爬虫
- `iterative_crawler.py` (342行) — 迭代原型
- `fixed_crawler.py` (362行) — 修复版原型~

全部已被 V2 系列替代，已在 `v2.2.1` 中删除。

### P1 重要

#### P1-1：API Key 回退链在 2 个文件中重复定义

`report_generator.py` L41-74（34 行）和 `smart_crawler_v2.py` L543-581（39 行）包含**完全相同的** 5 级回退逻辑：

```
BAILIAN_API_KEY → DASHSCOPE_API_KEY → OPENAI_API_KEY → openclaw.json providers[4种名称]
```

#### P1-2：`_parse_discussions` / `_parse_news` 中解析逻辑高度重复

`stock_crawler_v2.py` 中这两个方法（L626/L683）有近乎相同的结构：
- 相同的 `re.search` 时间匹配正则
- 相同的 `query_selector_all` + `inner_text` 模式
- 相同的 `re.sub` 清理链（展开/转发/赞/收藏）

但它们走不同的条件分支处理不同的字段（作者 vs 标题 vs 来源），没有抽取公共解析基类。

#### P1-3：`crawl()` 方法 1375 行文件中的巨方法问题

`crawl()` (L981) 是 `stock_crawler_v2.py` 的核心方法，包含三层嵌套 try-except、多 Tab 切换、内联的讨论/资讯解析和评论爬取。方法体约 350 行，深度嵌套 5-6 层。测试、调试、阅读都极困难。

#### P1-4：`smart_crawler_v2.py` L986 使用 `subprocess.run`

```python
subprocess.run(['gh', 'gist', 'create', str(report_path), '--desc', f'{symbol} ...'], ...)
```

使用 shell 命令上传 Gist，没有错误降级策略（`gh` CLI 未安装时静默失败）。

#### P1-5：零测试覆盖

6 个核心模块无任何单元测试或集成测试。

#### P1-6：错误处理策略不统一

| 文件 | 方法 | 失败行为 |
|------|------|----------|
| `stock_crawler_v2.py` | `crawl()` | 捕获所有异常，部分继续，部分返回不完整 `StockInfo` |
| `financial_fetcher.py` | `fetch()` | 返回 `None`（调用方需自己检查） |
| `smart_crawler_v2.py` | `call_llm()` | 抛 `ValueError` |
| `report_generator.py` | `analyze()` | 抛 `Exception`（包装） |

上层调用者无法预知某个模块失败会导致什么。

### P2 可改进

#### P2-1：`login_xueqiu.py` 硬编码 macOS Chrome 路径

```python
chrome_path = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
```

只在 macOS 可用，其他平台需手动修改。

#### P2-2：`data/reports/` 报告堆积无清理

多次运行产生大量 `*_smart_v2_*.json`、`*_evaluation_*.md`、`*_smart_v2_report_*.md` 文件，目前 ~80 个文件，无自动清理策略。

#### P2-3：日志混合使用 `logging` 和 `print`

`stock_crawler_v2.py` 使用标准 `logging` 模块，其他模块（`smart_crawler_v2.py`、`financial_fetcher.py`）使用 `print()`。调试时无法统一控制日志级别。

#### P2-4：`financial_fetcher.py` 和 `report_generator.py` 中 `urllib` 硬编码

未使用 `requests`（已在 `requirements.txt` 中），而是使用标准库 `urllib` + 手动拼接 Cookie/Header，缺少连接池、重试、超时控制。

#### P2-5：`report_generator.py` L110 裸 `except Exception`

```python
except urllib.error.HTTPError as e:
    error_body = e.read().decode('utf-8') if e.fp else ''
    raise Exception(f"API 请求失败 ({e.code}): {error_body}")
except Exception as e:
    raise Exception(f"API 调用异常: {e}")
```

重抛 `Exception` 丢失了原始异常类型和 traceback。

---

## 模块逐个评分

| 模块 | 架构 | 可读性 | 错误处理 | 可测试性 | 总分 |
|------|------|--------|----------|----------|------|
| `stock_crawler_v2.py` | 5 | 4 | 3 | 1 | 3.3 |
| `smart_crawler_v2.py` | 4 | 5 | 4 | 2 | 3.8 |
| `report_generator.py` | 6 | 6 | 4 | 4 | 5.0 |
| `financial_fetcher.py` | 7 | 7 | 5 | 6 | 6.3 |
| `run_analysis.py` | 7 | 7 | 6 | 6 | 6.5 |
| `data_quality_checker.py` | 6 | 7 | 6 | 7 | 6.5 |
| `analyzer.py` | 6 | 6 | 4 | 4 | 5.0 |

---

## 与上次评估对比（2026-05-22 → 2026-05-24）

| 维度 | 旧评分 | 新评分 | 关键发现 |
|------|--------|--------|----------|
| 架构 | 7→6 | 重叠代码从"看起来重叠"升级为"确认 70+ 行逐字重复" |
| 代码质量 | 6→5 | 发现硬编码 TCOM、debug_news_notices 语法错误、模型名不一致 |
| 工程化 | 4→3 | subprocess.run 无降级、urllib 替代 requests、无 CI |
| 安全 | —→5 | 首次审计：cookies 明文存储、凭据固定路径但环境变量隔离 |

---

## 版本历史

| 版本 | 日期 | 核心变更 |
|------|------|----------|
| v1.0.0 | 2026-03-05 | 初始版本：基础爬虫 + GLM-5 分析 |
| v2.0.0 | 2026-03-06 | Playwright 浏览器自动化 + 双 Prompt + 财务数据 |
| v2.1.0 | 2026-03-07 | 智能迭代（10轮）+ 评分≥150 终止 + Token 统计 |
| v2.2.0 | 2026-03-08 | 多年 ROIC + 财务数据加分项 |

## 相关项目

- [xueqiu-crawler](https://github.com/winterswang/xueqiu-crawler) — 雪球用户文章爬虫
- [unified-downloader](https://github.com/winterswang/unified-downloader) — 年报/招股书/10-K 下载

## License

MIT
