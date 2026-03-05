# 雪球公司分析 Skill

自动化分析雪球文章中提及的上市公司，结合多数据源生成结构化的投资价值分析报告。

## 功能特性

- 📊 **股票详情页爬取** - 自动获取讨论、资讯、公告
- 📝 **专栏文章分析** - 提取投资观点和逻辑
- 🤖 **GLM-5 深度分析** - 结构化分析报告
- 📈 **补充数据整合** - Longbridge K线、AkShare 财务（可选）

## 使用方式

```
分析 雪球 APP
雪球分析 携程
```

## 数据源

| 数据源 | 内容 | 状态 |
|--------|------|------|
| 雪球股票详情页 | 讨论、资讯、公告 | ✅ |
| 雪球专栏文章 | 投资观点 | ✅ |
| GLM-5 | 深度分析 | ✅ |
| Longbridge | K线数据 | 待集成 |
| AkShare | 财务数据 | 待集成 |

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
│   ├── stock_crawler.py  # 股票详情页爬虫
│   ├── article_crawler.py # 专栏文章爬虫
│   └── report_generator.py # 报告生成器
├── data/                 # 数据存储
└── logs/                 # 日志
```

## 安装

```bash
pip install -r requirements.txt
playwright install chromium
```

## 配置

在 `config/config.yaml` 中配置：

```yaml
# GLM-5 API
bailian:
  api_key: "your-api-key"
  
# 爬虫配置
crawler:
  headless: true
  delay_min: 2
  delay_max: 5
```

## 开发状态

| 功能 | 状态 |
|------|------|
| 需求设计 | ✅ 完成 |
| 项目初始化 | ✅ 完成 |
| 股票详情页爬虫 | ⏳ 开发中 |
| 报告生成 | ⏳ 待开发 |

## 相关项目

- [xueqiu-crawler](https://github.com/winterswang/xueqiu-crawler) - 雪球爬虫基础库

## License

MIT