
---
## 2026-05-27

## BUGFIX

- xueqiu-monitor 存储阶段失败修复：`sqlite3.OperationalError: no such column: stock_code` at `db.py:389 → get_existing_post_ids()`，根因是 `data/xueqiu.db` 为空文件（0 bytes），表结构未初始化

## TODO

- 修复 `db.py` 的 schema 初始化逻辑，确保在查询前表已存在

---
## 2026-05-27

## FEATURE
- (none)

## BUGFIX
- sqlite3.OperationalError: no such column: stock_code at db.py:389 → get_existing_post_ids() — database file data/xueqiu.db was empty (0 bytes), schema not initialized, causing all 3 stocks (AAPL.US / 700.HK / 600519.SH) storage to fail despite successful scraping

## DISCUSS
- Root cause identified: empty database file didn't trigger table creation; schema initialization logic in db.py needs to ensure tables exist before any query

## DECISION
- (none)

## TODO
- Fix db.py schema initialization logic to ensure table structure is created before queries execute against data/xueqiu.db

---
## 2026-05-27

## BUGFIX

- xueqiu-monitor 存储阶段全量失败：`data/xueqiu.db` 为空文件（0 bytes），表结构未初始化，`db.py:389 → get_existing_post_ids()` 查询时报 `sqlite3.OperationalError: no such column: stock_code`

## TODO

- 修复 `db.py` 的 schema 初始化逻辑，确保在存储查询前表已存在且列结构完整

---
## 2026-05-28

## FEATURE
- (不适用：当日对话全部为 cron 管线自动化执行，无功能开发)

## BUGFIX
- **analyzer.py** — 模块顶层加载 `.env` 文件，修复 `MINIMAX_API_KEY` 在 cron isolated session 中间歇性丢失（55% 成功率）的根因 bug。改用 `python-dotenv` 在 `ArticleAnalyzer` 初始化时直接读取，不再依赖 shell 环境变量传递
- **match_messages_to_projects()** — 新增 LLM 去重步骤（`disambiguate()`），解决同一消息同时命中 `xueqiu-crawler`、`xueqiu-monitor`、`xueqiu-analyzer-skill` 多个项目导致的重复分发问题
- **build_feishu_card()** — 卡片描述截断从 `80` 字符扩展至 `120` 字符，修复 BUGFIX 条目被截断导致文件路径/函数名丢失的问题

## DISCUSS
- (none)

## DECISION
- **.env 加载策略**：在 Python 模块层加载 `.env`，不依赖 shell 脚本传递环境变量，作为跨场景（cron/手动/命令行）的一致性解决方案
- **跨项目消息去重**：用 LLM 做归属判断而非关键词广播，确保 bug 报告归到唯一正确项目

## TODO
- 验证 04:00 cron 是否彻底修复 MiniMax 间歇性失效问题
- 飞书推送的 5/29 卡片质量验证（今日实打实的开发对话）

---
## 2026-05-30

## FEATURE
- (不适用：当日对话全部为 cron 管线自动化执行，无功能开发)

## BUGFIX
- (不适用：当日对话全部为 cron 管线自动化执行，无 bug 修复)

## DISCUSS
- (不适用：当日对话全部为 cron 管线自动化执行，无设计讨论)

## DECISION
- (不适用：当日对话全部为 cron 管线自动化执行，无架构决策)

## TODO
- (不适用：当日对话全部为 cron 管线自动化执行，无待办任务)

---
## 2026-05-30

## FEATURE
- (不适用：当日对话全部为 cron 管线自动化执行，无功能开发)

## BUGFIX
- (不适用：当日对话全部为 cron 管线自动化执行，无 bug 修复)

## DISCUSS
- (不适用：当日对话全部为 cron 管线自动化执行，无方案讨论)

## DECISION
- (不适用：当日对话全部为 cron 管线自动化执行，无技术决策)

## TODO
- (不适用：当日对话全部为 cron 管线自动化执行，无待办任务)

---

> 注：当日 02:04 的对话内容为日报分析 cron 管线的执行报告（扫描 6099 个 session 文件，匹配 3 个项目活跃度），属于自动化运营任务，不涉及功能开发、bug 修复或技术讨论。

---
## 2026-05-30

## FEATURE
- (不适用：当日对话全部为 cron 管线自动化执行，无功能开发)

## BUGFIX
- (不适用：当日对话全部为 cron 管线自动化执行，无 bug 修复)

## DISCUSS
- (不适用：当日对话全部为 cron 管线自动化执行，无方案讨论)

## DECISION
- (不适用：当日对话全部为 cron 管线自动化执行，无技术决策)

## TODO
- (不适用：当日对话全部为 cron 管线自动化执行，无待办任务)
