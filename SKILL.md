---
name: xueqiu-analyzer
description: 雪球公司分析 Skill V2 - 自动化分析雪球文章中提及的上市公司，生成投资价值分析报告
version: 2.0.0
author: winterswang
triggers:
  - pattern: "分析 雪球 {company}"
  - pattern: "雪球分析 {company}"
  - pattern: "分析{company}雪球"
---

# 雪球公司分析 Skill V2

自动化分析雪球文章中提及的上市公司，结合多数据源生成结构化的投资价值分析报告。

## 🎉 V2 新增功能

| 功能 | 描述 | 状态 |
|------|------|------|
| **新版爬虫** | 解决登录弹窗、Tab切换、分页累积问题 | ✅ |
| **雪球财务API** | PE、PB、ROE、市值、52周高低 | ✅ |
| **AkShare 补充** | 毛利率、净利率等盈利指标 | ✅ |
| **K线数据** | 雪球 API 支持 52周高低等 | ✅ |
| **全流程自动化** | 一键生成完整分析报告 | ✅ |

### 已解决问题

1. ✅ 登录弹窗拦截 - JavaScript 自动移除
2. ✅ Tab 切换被遮罩拦截 - JS 点击绕过
3. ✅ 分页数据累积 - 内容 hash 去重
4. ✅ 财务数据集成 - 雪球 API + AkShare

## 功能模块

### 1. 股票详情页爬取 (`stock_crawler_v2.py`)

- 自动登录（使用保存的凭据）
- 爬取讨论、资讯、公告
- 分页累积加载
- 文章详情获取

### 2. 财务数据获取 (`financial_fetcher.py`)

**数据源优先级：**
1. 雪球 API - PE、PB、ROE、市值、52周高低
2. AkShare - 毛利率、净利率

**支持指标：**
| 指标 | 来源 | 说明 |
|------|------|------|
| PE_TTM | 雪球 | 滚动市盈率 |
| PB | 雪球 | 市净率 |
| ROE | 雪球(计算) | 净利润/股东权益 |
| 市值 | 雪球 | 总市值 |
| 52周高低 | 雪球 | 价格区间 |
| 毛利率 | AkShare | 销售毛利率 |
| 净利率 | AkShare | 销售净利率 |

### 3. GLM-5 深度分析 (`report_generator.py`)

- 结构化投资分析报告
- 引用原文内容
- 估值判断 + 投资建议
- 风险提示

### 4. 全流程自动化 (`run_analysis.py`)

一键完成：爬取 → 分析 → 报告

## 使用方式

```bash
# 全流程分析
python scripts/run_analysis.py TCOM --max-pages 3

# 单独爬取
python scripts/stock_crawler_v2.py TCOM

# 单独获取财务数据
python scripts/financial_fetcher.py TCOM
```

## 数据源状态

| 数据源 | 内容 | 状态 |
|--------|------|------|
| 雪球股票详情页 | 讨论、资讯、公告 | ✅ |
| 雪球 API | PE、PB、ROE、市值 | ✅ |
| 雪球 K线 | 52周高低、价格区间 | ✅ |
| AkShare | 毛利率、净利率 | ✅ |
| GLM-5 | 深度分析 | ✅ |

## 项目文件

```
xueqiu-analyzer-skill/
├── scripts/
│   ├── run_analysis.py        # 全流程入口
│   ├── stock_crawler_v2.py    # 新版爬虫
│   ├── financial_fetcher.py   # 财务数据
│   ├── report_generator.py    # 报告生成
│   └── get_username.py        # 用户名获取
├── config/
│   ├── xueqiu_credentials.yaml
│   └── xueqiu_cookies.json
└── data/
    └── reports/               # 生成的报告
```

## 验收标准

- [x] 能从股票详情页爬取讨论、资讯、公告
- [x] 分页累积加载，数据量可配置
- [x] 财务数据自动获取（雪球 + AkShare）
- [x] GLM-5 深度分析报告
- [x] 全流程自动化测试通过