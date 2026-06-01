# 参数模式统一设计

## 动机

当前三个命令 (`crawl` / `deep-analyze` / `analyze`) 各用一套参数体系，行为不一致：

| 命令 | 参数 | 停止条件 |
|------|------|----------|
| `crawl` | `--max-pages --max-articles --days` | 翻页数/文章数/时间，任一先达 |
| `deep-analyze` | `--max-pages --days --max-articles --max-news --max-notices` | 同上 |
| `analyze` | `--max-rounds` | 迭代爬取+评分达标 |

**核心问题**：`--max-pages` 是机械参数（翻几页），不是用户心智模型。用户问的是"我要多少内容"、"多久以内的"、"质量够不够"。

## 目标

统一为三种业务模式，可任意组合：

| # | 模式 | 语义 | 默认 |
|---|------|------|------|
| ⏱ | 时间驱动 | 限定窗口内全量，不设上限 | `--days 30` |
| 📏 | 数量驱动 | 限定总条数，不限时间 | `--max-items 50` |
| 🧠 | 质量驱动 | 不限量不限时，评分达标即停 | `--auto` |

三种模式**不互斥**——组合时 N 个停止条件**任一满足**即停。

## 当前架构 Gap 分析

```
组件                       | 时间过滤 | 数量限制 | 质量驱动停止
---------------------------|----------|----------|-------------
API 讨论 (crawl_discussions)| ✅ days  | ❌       | ❌
API 公告 (crawl_notices)   | ✅ days  | ❌       | ❌
DOM 资讯翻页 (w_pagination)| ❌       | ❌       | ❌
DOM 公告翻页 (w_pagination)| ❌       | ❌       | ❌
Orchestrator (analyze)     | ❌无透传 | ✅rounds | ✅ quality+health
DeepAnalyzer (deep-analyze)| ✅透传   | ❌       | ❌
```

**三个关键 Gap**：
1. **DOM 翻页无时间过滤** — 设了 `--days 30` 对资讯/公告不走 API 时不生效
2. **无 count-based stop** — API 翻页只看 `max_pages`，没有总条数限制
3. **quality 被隔离** — `ContentQualityChecker` + `Evaluator` 只在老 `analyze` 命令里用，未接入 `deep-analyze`

## 新参数体系

```
deep-analyze SYMBOL [OPTIONS]
  --days N          时间窗口（天），0=不限，默认 0
  --max-items N     最大总内容条数，0=不限，默认 0
  --auto / --no-auto  质量驱动模式，默认 false
  --quality-score N 质量阈值（配合 --auto），默认 150

  --max-pages N     [兼容] 硬上限兜底，默认 1000
                    （设为 0 或极大值 = 无硬上限）
  
  --max-articles N  [保留] 专栏文章上限，默认 10
  --max-news N      [保留] 新闻详情上限，默认 10，0=只爬标题
  --max-notices N   [保留] 公告详情上限，默认 10，0=只爬标题
```

**向后兼容**：`--max-pages` 保留，旧用法不 break。

## 行为矩阵

| `--days` | `--max-items` | `--auto` | 行为 |
|----------|--------------|----------|------|
| 0 | 0 | ❌ | 全量爬取 (硬上限 max_pages=1000) |
| 30 | 0 | ❌ | 过去30天全部，不限条数 |
| 0 | 50 | ❌ | 最新50条，不限时间 |
| 30 | 50 | ❌ | 过去30天，最多50条（任一先停） |
| 0 | 0 | ✅ | 迭代爬取，quality ≥ threshold 即停 |
| 7 | 0 | ✅ | 7天 + 评分，任一满足 |
| 30 | 100 | ✅ | 三种条件：时间/数量/评分，任一满足 |

## 实现路径

### Phase 1: 爬虫层参数重构

**1.1 `XueqiuCrawler.crawl()` 新增 `max_items` 参数**

```python
def crawl(self, symbol, max_pages=1000, max_items=0, days=0,
          max_articles=10, max_news=10, max_notices=10):
```

- `max_items` 跟踪总条数（discussions + news + notices + articles）
- 在 API 翻页循环、DOM 翻页循环中每一轮检查总条数
- `max_pages` 降级为硬上限兜底（不再参与业务逻辑）

**1.2 DOM 翻页添加时间过滤**

`_crawl_items_with_pagination()` 新增 `days` 参数：
- 从 DOM 元素中提取日期文本
- 与 `time_cutoff` 比较
- 连续 N 条超出窗口 → 停止（防止边界误判）

**1.3 API 翻页添加 count-based stop**

`_crawl_discussions_via_api()` / `_crawl_notices_via_api()` 新增 `max_items` 参数：
- 每轮检查 `total_discussions + total_news + total_notices >= max_items`
- 达标即 `should_stop = True`

### Phase 2: 质量驱动模式

**2.1 扩展 DeepAnalyzer.analyze()**

新增 `auto=False, quality_score=150` 参数：

```python
def analyze(self, symbol, max_pages=1000, max_items=0, days=0,
            max_articles=10, max_news=10, max_notices=10,
            auto=False, quality_score=150):
```

当 `auto=True` 时：
1. 首轮：`crawl(max_pages=N, days=days, max_items=max_items, ...)`
2. `ContentQualityChecker.check()` → 硬指标（news_ratio ≥ 50%, notice_ratio ≥ 30%, min_article_length ≥ 200）
3. 不通过 → 调整策略重爬（多拉资讯/多翻页）
4. 通过 → `Evaluator.evaluate()` → LLM 充分性评分
5. `effective_score ≥ quality_score` → 停止
6. 未达标 + 未超硬上限 → 继续迭代

**2.2 迭代策略**

当前 orchestrator 的 `_iterative_crawl` 逻辑可直接复用，核心差异：
- 不是"定向补充"（旧逻辑），而是"渐进增量"
- round 1: 基准爬取（较低 max_pages/max_articles）
- round 2+: 扩大范围（翻页+50%、文章+5）
- 每轮增量 merge，不重复爬取

### Phase 3: CLI 统一

**3.1 `deep-analyze`**

```
@click.argument('symbol')
@click.option('--auto', is_flag=True, help='质量驱动模式')
@click.option('--quality-score', default=150, help='质量阈值')
@click.option('--max-items', default=0, help='最大总条数（0=不限）')
@click.option('--days', default=0, help='时间窗口（天）')
@click.option('--max-pages', default=1000, help='硬上限兜底')
@click.option('--max-articles', default=10)
@click.option('--max-news', default=10)
@click.option('--max-notices', default=10)
```

**3.2 `crawl`**

同样加上 `--auto`、`--max-items`、`--quality-score`。

**3.3 `analyze`（向后兼容）**

保持现有参数不变，标记为 `[Legacy]`。

### Phase 4: 安全保护

| 保护 | 机制 |
|------|------|
| 硬上限 | `--max-pages 1000`（默认），防止无限制翻页 |
| 时间兜底 | DOM 翻页无日期信息时，最多翻 `min(max_pages, 100)` 页 |
| 质量兜底 | auto 模式最多 `--max-pages/10` 轮迭代 |
| 总条数兜底 | `--max-items 2000` 隐含默认（可 override） |

## 配置

```yaml
# config/config.yaml 新增
crawl:
  default_max_pages: 1000       # 硬上限默认值
  max_items_fallback: 2000      # max_items 隐含上限
  auto_max_rounds: 20           # auto 模式最大迭代轮次

quality:
  health_threshold: 70          # 硬指标阈值（已有）
  auto_score_threshold: 150     # auto 模式评分阈值
  news_min_ratio: 0.5           # 已有
  notice_min_ratio: 0.3         # 已有
```

## 影响范围

| 文件 | 变更类型 |
|------|----------|
| `src/xueqiu_analyzer/crawler.py` | 🔴 核心：参数重构 + DOM时间过滤 + count-based stop |
| `src/xueqiu_analyzer/stock_analyzer.py` | 🔴 核心：auto 模式迭代循环 |
| `src/xueqiu_analyzer/cli.py` | 🟡 CLI：新参数 + 向后兼容 |
| `src/xueqiu_analyzer/orchestrator.py` | 🟢 提取可复用逻辑 |
| `src/xueqiu_analyzer/config.py` | 🟢 新配置项 |
| `config/config.yaml` | 🟢 新配置项 |
| `tests/` | 🟡 新测试 |
| `README.md` | 🟢 文档更新 |

## 不做的

- ~~删除 `--max-pages`~~（保留，向后兼容）
- ~~修改 `analyze` 命令~~（标记 Legacy，不维护）
- ~~改变 `_crawl_items_with_pagination` 的 Playwright 策略~~（只加时间过滤，不重写）
- ~~引入异步/并行~~（超出范围）
