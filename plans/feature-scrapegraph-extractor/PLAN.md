# Plan: ScrapeGraphAI 集成 — ScrapingExtractor

## 1. 背景与目标

### 现状问题
`xueqiu-analyzer-skill` 的 `crawler.py` 在解析资讯/公告/研报正文时，依赖大量硬编码 CSS selector + 多选择器兼容策略（`try A except try B`）。这是维护的痛点：
- 雪球改版时 selector 容易坏
- 多版兼容代码丑陋且不稳定
- 正文提取质量不稳定

### 目标
引入 ScrapeGraphAI 作为**提取层**，替代硬编码 selector，将爬虫部分（Playwright + 认证）保留，两者是互补关系。

### 范围
- ✅ 新增 `ScrapingExtractor` 类，使用 ScrapeGraphAI 接管文章详情页正文提取
- ✅ 爬虫部分（登录、列表页、分页）保留不变
- ✅ 测试验收基于真实雪球页面

---

## 2. 技术架构

### 集成位置

```
xueqiu_analyzer/
├── crawler.py          ← 保留（Playwright + 认证 + 导航）
├── extractor.py        ← 新增（ScrapeGraphAI 封装）
└── ...
```

### ScrapingExtractor 职责

接收：文章 URL（雪球帖子详情页）
输出：结构化 `ArticleContent`（标题、正文、作者、时间）

### 依赖

```python
# pyproject.toml / requirements.txt 新增
scrapegraphai>=0.5.0
playwright>=1.40.0  # ScrapeGraphAI 依赖
```

### LLM 配置

| 用途 | 模型 | Key |
|------|------|-----|
| Extractor | `deepseek-v4-flash` | `DEEPSEEK_API_KEY` |

### 输入输出

```python
@dataclass
class ArticleContent:
    title: str           # 标题
    author: str          # 作者
    content: str         # 正文（清洗后）
    time: str             # 发布时间
    symbols: List[str]    # 提及的股票代码
    url: str              # 原文链接

class ScrapingExtractor:
    def extract(self, url: str) -> ArticleContent:
        """
        使用 ScrapeGraphAI 提取文章正文
        失败时回退到原有 selector 逻辑
        """
```

---

## 3. 使用场景

| 场景 | 输入 | 输出 | 说明 |
|------|------|------|------|
| 新闻详情页 | https://xueqiu.com/xxx/xxx | ArticleContent | 正文提取 |
| 公告详情页 | https://xueqiu.com/xxx/xxx | ArticleContent | 公告正文 |
| 研报详情页 | https://xueqiu.com/xxx/xxx | ArticleContent | 研报全文 |

---

## 4. 实现计划

### Phase 1: 环境与依赖
- [ ] 安装 `scrapegraphai` 包
- [ ] 验证 Playwright + ScrapeGraphAI 连通性
- [ ] 配置 DeepSeek API Key（复用现有）

### Phase 2: ScrapingExtractor 核心
- [ ] 设计 `ArticleContent` 数据模型
- [ ] 实现 `ScrapingExtractor.extract(url)` 方法
- [ ] 实现 `SmartScraperGraph` prompt 模板（中文 prompt）
- [ ] 实现错误回退逻辑（ScrapeGraphAI 失败 → 原有 selector 逻辑）

### Phase 3: 集成到 Crawler
- [ ] 修改 `crawler.py` 的新闻/公告详情解析逻辑，调用 `ScrapingExtractor`
- [ ] 保留原有 selector 作为 fallback，确保向后兼容

### Phase 4: 测试验证
- [ ] 单元测试：`test_extractor_basic`（mock LLM）
- [ ] 集成测试：3 个真实雪球页面（新闻、公告、研报各一）
- [ ] 回退测试：模拟 ScrapeGraphAI 失败，验证 fallback

---

## 5. 测试验收逻辑（核心）

### 5.1 单元测试 `test_extractor_basic`

**测试目标**：ScrapingExtractor 核心逻辑

**测试步骤**：
1. Mock DeepSeek API（返回固定 JSON）
2. 调用 `extractor.extract("https://xueqiu.com/xxx")`
3. 验证返回 `ArticleContent` 结构正确

**验收条件**：
```
✅ fields: title, author, content, time, symbols, url 全部非空
✅ content 长度 >= 50 字符（有效正文）
✅ symbols 包含至少一个股票代码
```

### 5.2 集成测试 `test_extractor_real_pages`

**测试目标**：3 个真实雪球页面提取

**测试数据**（真实 URL，需可访问）：

| 类型 | 股票 | 用途 |
|------|------|------|
| 新闻 | https://xueqiu.com/xxx/xxxxx | 新闻正文提取 |
| 公告 | https://xueqiu.com/xxx/xxxxx | 公告正文提取 |
| 研报 | https://xueqiu.com/xxx/xxxxx | 研报全文提取 |

**验收条件**：
```
✅ 每个 URL 返回非空 content
✅ content 中无 "403" / "登录" 等干扰文本
✅ 标题与页面实际标题一致（人工确认）
```

### 5.3 回退测试 `test_extractor_fallback`

**测试目标**：ScrapeGraphAI 失败时 fallback 到原有 selector

**测试步骤**：
1. Mock ScrapeGraphAI 抛出异常
2. 调用 `extractor.extract(url)`
3. 验证 fallback 返回非空结果

**验收条件**：
```
✅ fallback 返回 ArticleContent（非 None）
✅ warning log 被正确记录
```

### 5.4 性能测试 `test_extractor_performance`

**测试目标**：提取时间不超过 30 秒（LLM 调用延迟）

**验收条件**：
```
✅ extract() 端到端时间 <= 30s（置信区间 95%）
```

---

## 6. 风险与对策

| 风险 | 概率 | 影响 | 对策 |
|------|------|------|------|
| ScrapeGraphAI 版本兼容性 | 低 | 高 | 指定 `>=0.5.0,<1.0.0` 版本范围 |
| 雪球登录态过期 | 中 | 高 | 在 crawler 层维护 cookie + extractor 层复用 session |
| LLM 调用失败（网络/Key） | 中 | 中 | fallback + 告警 log |
| 雪球反爬（403/验证码） | 低 | 中 | headless=True + 随机 UA |

---

## 7. 不纳入范围

- ❌ 修改 crawler.py 的登录逻辑
- ❌ 修改列表页爬取逻辑（分页、翻页）
- ❌ 替代价格/涨跌幅等结构化数据提取
- ❌ 修改 `xueqiu-crawler` 项目

---

## 8. 交付物

| 文件 | 说明 |
|------|------|
| `src/xueqiu_analyzer/extractor.py` | 核心提取器 |
| `tests/test_extractor.py` | 测试用例 |
| `plans/feature-scrapegraph-extractor/PLAN.md` | 本计划 |
| `SKILL.md` 更新 | 新增 extractor 使用说明 |