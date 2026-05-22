# 雪球股票分析 Skill

输入股票代码，输出结构化投资分析报告。

**核心流程**：Playwright 爬取 → 财务数据获取 → GLM-5 AI 分析 → 报告生成 → Gist 同步

## 功能

- ✅ Playwright 爬取雪球讨论/资讯/公告/文章
- ✅ AkShare 补充财务数据（毛利率、净利率、ROE）
- ✅ 多年 ROIC 计算（投入资本回报率）
- ✅ GLM-5 AI 生成结构化分析报告
- ✅ Gist 同步 + 飞书推送

## 架构

```
用户输入股票代码（如 00700）
        ↓
stock_crawler_v2.py (Playwright 模拟登录 + 爬取)
        ↓
financial_fetcher.py (雪球 API + AkShare 获取 PE/PB/ROE/ROIC)
        ↓
data_quality_checker.py (内容清洗 + 质量过滤)
        ↓
report_generator.py (GLM-5 分析 + 报告生成)
        ↓
run_analysis.py (Gist 同步 + 飞书推送)
```

## 目录结构

```
xueqiu-analyzer-skill/
├── SKILL.md              # Skill 元数据
├── README.md             # 本文档
├── requirements.txt      # Python 依赖
├── config/
│   ├── config.yaml       # GLM-5/爬虫配置
│   ├── target_users.yaml # 目标用户列表
│   ├── xueqiu_cookies.json
│   └── xueqiu_credentials.yaml
├── scripts/
│   ├── analyzer.py         # 主入口（analyzer.py 包装）
│   ├── run_analysis.py     # 全流程编排
│   ├── stock_crawler_v2.py # Playwright 爬虫（主）
│   ├── smart_crawler_v2.py  # 雪球帖子爬虫（独立）
│   ├── report_generator.py  # GLM-5 调用 + 报告生成
│   ├── financial_fetcher.py # 财务数据（雪球 API + AkShare）
│   ├── data_quality_checker.py # 内容清洗 + 质量过滤
│   ├── login_xueqiu.py      # 登录模块
│   ├── get_username.py      # 用户名获取
│   ├── debug_news_notices.py
│   ├── update_template.py
│   └── archive/            # 废弃代码（待清理）
│       ├── stock_crawler.py
│       ├── smart_crawler.py
│       ├── iterative_crawler.py
│       └── fixed_crawler.py
├── data/
│   └── reports/            # 分析报告输出
└── logs/
```

## 使用

```bash
# SKILL 触发（推荐）
# 用户说"分析腾讯/00700"，通过 SKILL.md 调用

# 手动全流程
python scripts/run_analysis.py --symbol 00700

# 只爬数据
python scripts/stock_crawler_v2.py 00700

# 生成报告
python scripts/analyzer.py 00700
```

## 核心模块

| 脚本 | 职责 | 行数 |
|------|------|------|
| `stock_crawler_v2.py` | Playwright 爬虫（登录/滚动/Tab切换） | 1373 |
| `report_generator.py` | GLM-5 调用 + 报告生成 | 412 |
| `smart_crawler_v2.py` | 雪球帖子爬取（与 stock_crawler_v2 部分重叠） | 1065 |
| `financial_fetcher.py` | 财务数据（雪球 API + AkShare） | 301 |
| `run_analysis.py` | 全流程编排 | 164 |
| `analyzer.py` | 主入口（简单包装 stock_crawler_v2） | 146 |
| `data_quality_checker.py` | 内容清洗 + 质量过滤 | 222 |

## 代码质量评估（2026-05-22）

| 维度 | 评分 | 说明 |
|------|------|------|
| **架构** | 7/10 | 模块分离清晰，dataclass 规范 |
| **代码质量** | 6/10 | 关键函数缺文档，部分命名不一致 |
| **工程化** | 4/10 | 大量废弃代码，零测试，无日志配置 |
| **可维护性** | 5/10 | 配置分散，API Key 回退链过长 |
| **整体** | **6/10** | 架构思路清晰，工程化程度低 |

### P0 必须修复

1. **废弃代码未清理** — `scripts/archive/` 里 4 个旧版爬虫（1302行）
2. **`smart_crawler_v2.py` 与 `stock_crawler_v2.py` 职责重叠**
3. **`config.yaml` 中 `${BAILIAN_API_KEY}` 是字符串** — 不是真正的环境变量插值，代码读 `os.environ.get()` 而非 yaml

### P1 重要

4. **硬编码路径** — cookie 路径 `~/.xueqiu_crawler/` 硬编码
5. **`run_analysis.py` 无 `if __name__`** — 不可直接运行
6. **错误处理薄弱** — `crawl()` 失败时返回空 dict 还是抛异常？行为不明确
7. **零测试覆盖**

### P2 可改进

8. **`data/reports/` 临时文件堆积** — 无清理机制
9. **日志无统一配置** — 纯 print，无日志文件
10. **`report_generator.py` API Key 回退链过长** — 5种回退路径（BAILIAN_API_KEY → DASHSCOPE_API_KEY → OPENAI_API_KEY → openclaw.json providers）

## 相关项目

- [xueqiu-crawler](https://github.com/winterswang/xueqiu-crawler) — 雪球用户文章爬虫（定时任务驱动）
- [unified-downloader](https://github.com/winterswang/unified-downloader) — 年报/招股书/10-K 下载

## License

MIT