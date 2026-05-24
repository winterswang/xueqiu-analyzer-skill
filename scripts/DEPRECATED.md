# V2 代码已废弃

V3 重构完成后，`scripts/` 下的所有文件已废弃，仅保留作为参考。

## V3 替代方案

| V2 文件 | V3 替代 | 命令 |
|---------|---------|------|
| smart_crawler_v2.py | orchestrator.py + evaluator.py + analyzer.py | `xueqiu analyze` |
| stock_crawler_v2.py | crawler.py | `xueqiu crawl` |
| run_analysis.py | cli.py | `xueqiu analyze` |
| analyzer.py | cli.py | `xueqiu analyze` |
| report_generator.py | analyzer.py | `xueqiu reanalyze` |
| financial_fetcher.py | financial_fetcher.py (V3) | 内置 |
| llm_config.py | config.py + llm_client.py | 内置 |
| refresh_cookies.py | cli.py | `xueqiu cookies` |
| data_quality_checker.py | crawler.py 内置 | 内置 |

## 迁移指南

```bash
# 旧方式
python3 scripts/smart_crawler_v2.py 00700 --max-rounds 5

# 新方式
PYTHONPATH=src python3 -m xueqiu_analyzer.cli analyze 00700 --max-rounds 5

# 旧方式：只爬数据
python3 scripts/stock_crawler_v2.py 00700

# 新方式
PYTHONPATH=src python3 -m xueqiu_analyzer.cli crawl 00700

# 旧方式：用已有数据分析
(无此功能)

# 新方式
PYTHONPATH=src python3 -m xueqiu_analyzer.cli reanalyze --data data/00700.json
```
