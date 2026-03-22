# 雪球股票分析爬虫

自动化爬取雪球（xueqiu.com）股票详情页数据，支持讨论、资讯、公告、专栏文章等多维度数据获取。

## 功能特性

- 📊 **讨论（讨论）** - 获取用户对股票的最新讨论
- 📰 **资讯（资讯）** - 获取股票相关的新闻资讯
- 📋 **公告（公告）** - 获取上市公司公告，支持 PDF 原文链接
- 📝 **专栏文章** - 获取深度分析文章全文
- 🔄 **自动登录** - 支持 cookie 缓存和自动登录
- 🛡️ **反爬处理** - 自动处理弹窗、验证等

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 基本用法

```python
from stock_crawler_v2 import XueqiuStockCrawlerV2

# 初始化爬虫
crawler = XueqiuStockCrawlerV2(headless=True)

# 爬取股票数据
result = crawler.crawl(
    symbol='00700',      # 股票代码
    max_discussions=20,  # 最大讨论数
    max_news=20,         # 最大资讯数
    max_articles=10,    # 最大文章数
    max_scrolls=10      # 最大滚动次数
)

print(f"讨论: {len(result.discussions)}")
print(f"资讯: {len(result.news)}")
print(f"公告: {len(result.notices)}")
print(f"文章: {len(result.articles)}")
```

## 数据结构

### StockInfo（股票信息）

```python
@dataclass
class StockInfo:
    symbol: str              # 股票代码 (如 "00700")
    name: str = ""          # 股票名称 (如 "腾讯控股")
    price: str = ""         # 当前价格
    change: str = ""        # 涨跌幅
    discussions: List[Discussion] = None  # 讨论列表
    news: List[News] = None              # 资讯列表
    notices: List[Notice] = None         # 公告列表
    articles: List[Article] = None       # 文章列表
    financial_data: dict = None          # 财务数据
```

### Discussion（讨论）

```python
@dataclass
class Discussion:
    author: str              # 作者昵称 (如 "不讲男德")
    time: str               # 发布时间 (如 "3分钟前")
    content: str            # 内容正文
    link: str = ""          # 链接
    comments: List[str] = None  # 评论列表
```

**示例数据：**
```json
{
    "author": "不讲男德",
    "time": "3分钟前",
    "content": "回复@牛叉的员工: 老哥，腾讯拿了多久了",
    "link": "https://xueqiu.com/123456789/123456789",
    "comments": ["支持", "同意"]
}
```

### News（资讯）

```python
@dataclass
class News:
    title: str               # 标题
    time: str               # 发布时间
    source: str = ""        # 来源 (如 "36氪", "财联社")
    link: str = ""          # 链接
    content: str = ""       # 正文内容
```

**示例数据：**
```json
{
    "title": "腾讯控股(00700)52分钟前· 来自新闻",
    "time": "52分钟前",
    "source": "新闻",
    "link": "https://xueqiu.com/S/00700",
    "content": "腾讯控股发布2024年度财报..."
}
```

### Notice（公告）⚡️ 新增详情页

```python
@dataclass
class Notice:
    title: str               # 标题 (含股票名、时间、公告类型)
    link: str                # 公告详情页链接
    time: str = ""           # 发布时间 (如 "昨天", "03-18 08:40")
    id: str = ""            # 公告ID
    ai_summary: str = ""    # AI摘要 / PDF链接
    content: str = ""        # 公告正文内容 (新)
    pdf_link: str = ""       # PDF下载链接 (新)
```

**示例数据：**
```json
{
    "title": "腾讯控股(00700)昨天 09:00· 来自公告 [翌日披露报表]",
    "link": "https://xueqiu.com/S/00700/123456789",
    "time": "昨天",
    "id": "123456789",
    "pdf_link": "https://stockn.xueqiu.com/00700/20260319126967.pdf",
    "content": "腾讯控股 翌日披露报表 - [其他] 翌日披露报表 - 已发行股份变动 网页链接..."
}
```

### Article（专栏文章）

```python
@dataclass
class Article:
    title: str               # 标题
    author: str             # 作者 (如 "@巍巍昆仑侠", "@朱酒")
    time: str               # 发布时间
    content: str            # 文章正文
    link: str               # 文章链接
    article_id: str = ""    # 文章ID
```

**示例数据：**
```json
{
    "title": "腾讯控股深度分析报告",
    "author": "@巍巍昆仑侠",
    "time": "2024-03-15",
    "content": "腾讯控股作为中国互联网龙头企业...",
    "link": "https://xueqiu.com/123456789/987654321",
    "article_id": "987654321"
}
```

## 爬取能力对照表

| 数据类型 | 列表页 | 详情页 | 字段完整性 |
|----------|--------|--------|------------|
| 讨论 | ✅ | 部分（评论） | ⭐⭐⭐ |
| 资讯 | ✅ | ✅ | ⭐⭐⭐⭐ |
| 公告 | ✅ | ✅ 新增 | ⭐⭐⭐⭐⭐ |
| 文章 | ✅ | ✅ | ⭐⭐⭐⭐ |

## 公告详情页能力

从 v2.1 版本开始，公告支持详情页爬取：

### 获取的额外信息

1. **PDF 下载链接**
   - 格式：`https://stockn.xueqiu.com/{股票代码}/{公告ID}.pdf`
   - 可直接下载 PDF 原文

2. **公告正文内容**
   - 包含公告类型：翌日披露报表、末期业绩、股息分派、股东大会等
   - 包含股份变动信息
   - 包含业绩公布详情

### 公告类型识别

代码会自动从标题中提取公告类型：

| 类型 | 示例 |
|------|------|
| 翌日披露报表 | 翌日披露报表 |
| 末期业绩 | 截至二零二五年十二月三十一日止年度全年业绩公佈 |
| 股息或分派 | 末期股息 |
| 暂停办理过户 | 暂停办理过户登记手续 |
| 股东大会 | 股东周年大会 |

## 配置说明

### 配置文件位置

默认配置目录：`~/.xueqiu_crawler/`

```
~/.xueqiu_crawler/
├── cookies.json      # 登录 Cookies（自动生成）
├── credentials.yaml  # 登录凭据（需手动创建）
└── config.yaml      # 配置文件（可选）
```

### credentials.yaml 格式

```yaml
xueqiu:
  phone: "13112345678"   # 雪球账号
  password: "your-password"
```

### 登录状态

- 首次运行会自动尝试登录
- 登录成功后会保存 cookies 到 `cookies.json`
- 下次运行优先使用 cookies，无效时自动重新登录

## 项目结构

```
xueqiu-analyzer-skill/
├── SKILL.md              # Skill 元数据
├── README.md             # 说明文档
├── requirements.txt      # Python 依赖
├── config/
│   └── config.yaml       # 配置文件
├── scripts/
│   ├── analyzer.py       # 主分析脚本
│   ├── stock_crawler.py  # 股票详情页爬虫 (旧版)
│   ├── stock_crawler_v2.py  # 股票详情页爬虫 (新版 v2.1)
│   └── article_crawler.py # 专栏文章爬虫
├── data/                 # 数据存储
└── logs/                 # 日志
```

## 相关项目

- [xueqiu-crawler](https://github.com/winterswang/xueqiu-crawler) - 雪球用户文章爬虫
- [data_collector](https://github.com/winterswang/data_collector) - 统一数据服务层

## License

MIT