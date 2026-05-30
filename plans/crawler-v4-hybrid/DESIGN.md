# 爬虫 V4 混合方案：API 列表 + Playwright 详情

> 状态：设计阶段  
> 基于：[PR #9 API 爬虫方案](https://github.com/winterswang/xueqiu-analyzer-skill/pull/9)  
> 前置：[雪球爬虫 V3 技术方案.pdf](/code/xueqiu-analyzer-skill/../雪球爬虫%20V3%20技术方案.pdf)

---

## 一、背景

### 当前架构（main @ e3d5521）

```
crawl()
  ├─ Playwright 启动（~5s）
  ├─ 讨论 → _crawl_items_with_pagination() → DOM 翻页（~8s/页，最多 10 条/页）
  ├─ 资讯 → 同上 → DOM 翻页（~8s/页）
  ├─ 资讯详情 → Playwright new_page() × 10（~8s/条）
  ├─ 公告 → DOM（1 页，~5s）
  ├─ 公告详情 → Playwright × 10（~3s/条）
  ├─ 专栏分离 → 【专栏 前缀匹配
  └─ 详情富化 → _crawl_discussion_detail() × max_articles（~5s/条）

  # 结果：10 讨论, 10 资讯, 10 公告, 2 文章
  # 耗时：~124s
  # LLM 评分：55/200（数据不足）
```

### 问题

1. **数据量天花板** — DOM 翻页最多 10 条/页，实际换页可能只刷新不增量（假翻页）
2. **专栏区分不准** — `【专栏` 前缀匹配漏报率高，TYPE=2 才是服务器标记
3. **耗时集中在 DOM 翻页** — 每个 tab 翻页 + HTML 解析占 80+ 秒

### PR #9 已验证

| 指标 | 当前 | PR #9 API | 提升 |
|------|------|-----------|------|
| 讨论条数 | 10 | 159 | 16× |
| 专栏区分 | 不准 | 精准（type=2） | ✓ |
| 资讯条数 | 10 | 20 | 2× |
| 公告条数 | 10 | 19（86 页天花板） | 2× |
| 耗时 | ~124s | ~30s（API 部分） | -76% |

---

## 二、设计要点（对上版方案的修正）

### 2.1 Cookie 加载

**问题发现**：API 调用需要 `xq_a_token` Cookie。当前 cookies 在 `_create_browser_context()` 中通过 `context.add_cookies()` 注入 Playwright，API 层无法直接使用。

**做法**：在 `__init__` 中新增 `_load_api_headers()`，读取 `~/.xueqiu_crawler/cookies.json`，提取 `xq_a_token` 构造 HTTP 头。

```python
def _load_api_headers(self) -> dict:
    try:
        with open(self.cookies_path) as f:
            cookies = json.load(f)
        token = next((c['value'] for c in cookies if c['name'] == 'xq_a_token'), '')
        return {"Cookie": f"xq_a_token={token}", ...} if token else {}
    except Exception:
        return {}
```

### 2.2 API 降级粒度和阈值

**上版问题**：提出"每个 tab 独立降级"但没有明确阈值。

**修正**：
- 降级条件：API 返回列表 ≤ 2 条，或 HTTP 状态码 ≠ 200
- 降级动作：该 tab 用 `_crawl_items_with_pagination()` DOM 路径
- 不降级时：API 数据直接入 `result.discussions` / `result.news` / `result.notices`

### 2.3 专栏分离逻辑修正

**当前 main 已存在 `【专栏` 前缀匹配（lines 249-293）**。API 路径用 `type=2` 标记更准确，DOM fallback 路径保留原有逻辑。

| 路径 | 判断标准 | 来源 |
|------|---------|------|
| API | `item['type'] == 2` | 服务器端标记 |
| DOM fallback | `content.startswith('【专栏')` | 当前 main 逻辑 |

### 2.4 资讯列表 vs 资讯详情

**上版混淆**：把 API 返回的列表（20 条摘要）和 Playwright 详情（正文 2000+ 字）当成同一件事。

**澄清**：
- API `interview/search.json` 只返回 200 字摘要 → 用于**列表**
- Playwright 打开文章链接 → 用于**正文**

所以资讯流程是：API 取列表（20 条） → 精选 Top 5 走 Playwright 取正文 → 其余 15 条保留摘要。

### 2.5 公告 API 的真实内容

**上版误判**："公告 API 返回 HTML 内容可取代 Playwright"。

**澄清**：`stock_timeline.json` 返回 `description` 字段只包含标题 + 链接的 HTML 片段（如 `贵州茅台：关于xxx公告 <a href="...">网页链接</a>`），不是正文。公告正文在 PDF 中，仍需 Playwright 打开。

所以公告 API 只改善列表获取量（10→19），不影响内容质量。

### 2.6 现有 `_crawl_discussion_detail()` 直接复用

**线 current main 已有完善的详情富化方法**（lines 917-1016），包含：
- 多 CSS 选择器提取标题
- 多选择器提取正文 + body fallback  
- 评论提取（30 条上限）
- 免责声明过滤

**无需重写**，API 获取的专栏文章链接直接传入即可。

### 2.7 耗时重算（纠正上版）

```
阶段                          当前      新方案    说明
────────────────────────────────────────────────────────
Playwright 启动               5s        5s       不变
登录 + 首页                   5s        5s       不变
股票详情页                    5s        5s       不变
讨论列表                     80s       20s      10 页 DOM → 10 页 API
资讯列表                     10s        1s       1 页 API
资讯详情（新闻）              80s       40s      10 条 → 5 条精选
公告列表                      5s        2s       1 页 → 2 页 API
公告详情                     30s       15s      10 条 → 5 条精选
专栏分离                      0s        0s       type=2 开箱即用
详情富化（专栏文章）           10s       25s      2 篇 → 5 篇（因为专栏数量从 2→25，精选 5 篇）
────────────────────────────────────────────────────────
总计                         ~230s     ~118s     -49%
```

⚠️ 注意：耗时节约主要在**列表层**。详情富化因为数据量增加，实际耗时**增加**（因为 API 能拿到更多有价值的专栏文章）。

### 2.8 真正的价值不在速度，在数据量

| 指标 | 当前 | 新方案 | 对 LLM 分析的影响 |
|------|------|--------|------------------|
| 讨论条数 | 10 | ~159 | 评分 +50 |
| 资讯条数 | 10 | 20（摘要需跑详情） | 评分 +10 |
| 公告条数 | 10 | 19 | 评分 +5 |
| 专栏文章 | 2 | 5（从 25 中精选） | 评分 +30 |
| 预计 LLM 评分 | 55 | **120-150** | ↑ 可翻越阈值 |

---

## 三、执行流（精确版）

```
crawl(symbol)
│
├─ __init__: _load_api_headers() ← 读 xq_a_token
│
├─ Playwright 启动 → 登录 → 访问股票页 → 提取名称+股价 (不变)
│
├─ Q1: 讨论列表
│   ├─ [Try]  _fetch_discussions_via_api()  ← GET /query/v1/symbol/search/status.json
│   │         for page in 1..10:
│   │           20 条/页, type=2 → articles, type≠2 → discussions
│   │           if len(items) < 20: break
│   └─ [Fallback] if total < 3:
│                _crawl_items_with_pagination(page, _parse_single_discussion, ...)  ← DOM 翻页
│                + 【专栏 前缀匹配
│
├─ Q2: 资讯列表
│   ├─ [Try]  _fetch_news_via_api()  ← GET /statuses/interview/search.json (1 次请求)
│   └─ [Fallback] if < 3:
│                _crawl_items_with_pagination(page, _parse_single_news, ...)  ← DOM
│
├─ Q3: 公告列表
│   ├─ [Try]  _fetch_notices_via_api()  ← GET /statuses/stock_timeline.json?source=公告
│   │         for page in 1..5: 10 条/页
│   └─ [Fallback] if < 3:
│                DOM: items = page.query_selector_all('.timeline__item')
│
├─ Q4: 资讯详情（精选）
│   从 result.news 中取 top 5（按时间排序），Playwright 打开链接提取正文
│   复用现有的 _crawl_discussion_detail() 选择器逻辑
│   过滤免责声明（_is_disclaimer）
│
├─ Q5: 公告详情（精选）
│   从 result.notices 中取 top 5，Playwright 打开 PDF 链接
│   复用现有的 _crawl_notice_detail()
│
├─ Q6: 详情富化（专栏文章）
│   从 result.articles[:max_articles] 取链接列表
│   复用现有 _crawl_discussion_detail(page, link) ← 返回 full_content + comments
│
└─ 保存 cookies → browser.close()
```

---

## 四、实现清单

### 新增方法

| 方法 | 位置 | 说明 |
|------|------|------|
| `_load_api_headers()` | `XueqiuCrawler.__init__` | 从 cookies.json 提取 xq_a_token |
| `_fetch_discussions_via_api(symbol, max_pages)` | crawler.py | 调用 status.json 分页 |
| `_fetch_news_via_api(symbol)` | crawler.py | 调用 interview/search.json |
| `_fetch_notices_via_api(symbol, max_pages)` | crawler.py | 调用 stock_timeline.json |

### 修改方法

| 方法 | 改动 |
|------|------|
| `crawl()` | 替换讨论/资讯/公告获取逻辑为 API-try-first + DOM-fallback |
| `_create_browser_context()` | 不改 |

### 模型变更

| 字段 | 理由 |
|------|------|
| Discussion 不加 `is_column` | 因为专栏通过 type=2 直接入 `result.articles`，不需要标记位 |

### 不修改的

- `_parse_single_discussion()` — DOM fallback 路径继续使用
- `_parse_single_news()` — DOM fallback 路径继续使用  
- `_parse_single_notice()` — DOM fallback 继续
- `_crawl_discussion_detail()` — 详情提取底层不变
- `_crawl_notice_detail()` — 公告详情底层不变
- `_is_disclaimer()` — 免责声明过滤器不变

---

## 五、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| API 字段名变更 | 中 | 高（静默失效） | `total < 3` 降级条件自动退到 DOM |
| cookies 过期导致 API 401 | 中 | 中 | 同上，DOM 也会失败但至少不崩溃 |
| API 限频 | 低 | 中 | `human_delay(1, 2)` 在 API 分页之间 |
| 专栏文章过多（25 篇）导致详情爬取超时 | 高 | 中 | `max_articles` 限制，默认 10 |
| 雪球 API 需要 Referer 头 | 低 | 高 | 在 `_load_api_headers()` 中预设 |
