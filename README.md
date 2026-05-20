# xueqiu-analyzer V3

雪球股票分析工具 — 自动化爬取雪球数据，结合 LLM 生成结构化投资分析报告。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt
playwright install chromium  # 或使用系统 Chromium

# 完整分析（爬取→评估→分析）
PYTHONPATH=src python3 -m xueqiu_analyzer.cli analyze 00700

# 只爬数据
PYTHONPATH=src python3 -m xueqiu_analyzer.cli crawl 00700

# 评估已有数据
PYTHONPATH=src python3 -m xueqiu_analyzer.cli evaluate --data data/00700.json

# 用已有数据重新分析（支持换模板/模型）
PYTHONPATH=src python3 -m xueqiu_analyzer.cli reanalyze --data data/00700.json --template conservative

# 管理 cookies
PYTHONPATH=src python3 -m xueqiu_analyzer.cli cookies --check
PYTHONPATH=src python3 -m xueqiu_analyzer.cli cookies --import cookies.json
```

## 命令一览

| 命令 | 说明 |
|------|------|
| `analyze SYMBOL` | 完整流程：爬取→评估→分析 |
| `crawl SYMBOL` | 只爬数据，保存为 JSON |
| `evaluate --data FILE` | 评估数据充分性 |
| `reanalyze --data FILE` | 用已有数据重新分析 |
| `cookies --check/--import` | 管理登录状态 |

## 分析模板

| 模板 | 文件 | 特点 |
|------|------|------|
| `analysis` (默认) | `prompts/analysis.md` | 标准分析，8主题+投资决策 |
| `conservative` | `prompts/conservative.md` | 保守型，安全边际≥30%，确定性评分 |

切换模板：`--template conservative`

## 配置

编辑 `config/config.yaml`：

```yaml
llm:
  base_url: "https://ark.cn-beijing.volces.com/api/coding/v3"
  model: "doubao-seed-2.0-pro"    # 换模型只改这里
  api_key: "${ARK_API_KEY}"
  max_tokens: 8000
  temperature: 0.7

evaluator:
  score_threshold: 150              # 充分性阈值
  max_rounds: 10                    # 最大迭代轮次
```

## 架构

```
Crawler → JSON 文件 → Evaluator → JSON 文件 → Analyzer
                             ↓                        ↓
                        可独立运行 ←─────────────────┘
```

每个模块从文件读取输入、向文件写入输出，互不依赖。

## 项目结构

```
src/xueqiu_analyzer/
├── models.py            # 数据模型 (CrawlResult/EvaluationResult/...)
├── config.py            # 配置加载 (环境变量 > yaml > openclaw.json)
├── llm_client.py        # LLM 客户端 (evaluate/analyze/simple_chat)
├── crawler.py           # 雪球爬虫 (Playwright)
├── evaluator.py         # 信息充分性评估
├── analyzer.py          # 深度分析 (支持多模板)
├── orchestrator.py      # 编排器 (迭代循环)
├── financial_fetcher.py # 财务数据 (雪球API + AkShare)
└── cli.py               # CLI 入口

prompts/
├── evaluation.md        # 评估 Prompt 模板
├── analysis.md          # 标准分析模板
└── conservative.md      # 保守型分析模板

tests/
├── test_evaluator.py    # 14 个核心测试
└── test_modules.py      # 21 个模块测试
```

## 测试

```bash
PYTHONPATH=src pytest tests/ -v
# 35 passed
```

## V2 → V3 改进

| 指标 | V2 | V3 |
|------|-----|-----|
| 代码量 | 4,781 行 | 2,531 行 (-47%) |
| run() 函数 | 441 行 | < 50 行 |
| CLI 入口 | 3 个 | 1 个 |
| 测试 | 0 | 35 |
| Prompt | 硬编码 Python | 外部模板文件 |
| 爬虫/分析 | 耦合 | 完全解耦 |
| 敏感文件 | cookies+数据进 Git | 已排除 |

## License

MIT
