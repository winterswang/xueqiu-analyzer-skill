
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

---
## 2026-06-08

## FEATURE
- IMA笔记集成：新增 `src/xueqiu_analyzer/ima_publisher.py` 模块，实现标题提取（从Markdown `# heading`）、UTF-8校验、IMA `import_doc` API发布，自动归入「价值投资研究」笔记本；CLI `analyze`/`reanalyze` 集成IMA发布，支持 `--ima-folder`/`--ima-folder-name` 参数；`_save_results` 自动添加报告标题前缀（如 `# OKTA Okta(NASDAQ:OKTA) 投资分析报告`）
- 成功执行影石创新(SH688775)深度分析，生成报告并存入IMA（`note_id=7469675810136022`），发现天量解禁、增收不增利、大疆竞争、存货暴雷等核心风险

## BUGFIX
- `python-dotenv` 未安装导致 `.env` 从未被加载，`DEEPSEEK_API_KEY` env始终为空（静默失败）
- base_url不跟随fallback key切换：即使通过 `ARK_API_KEY` 拿到Ark key，`base_url` 仍是 `api.deepseek.com`（yaml默认值），导致 Ark key + DeepSeek endpoint = 401
- opencli公告链接格式导致PDF爬取跳过：`_crawl_notice_pdf_text` 仅在 `.pdf` 结尾或含 `stockmc.xueqiu.com` 时执行，opencli `stock-notices` 返回的URL格式不匹配 → 公告内容率0%

## DISCUSS
- 用户询问是否需要更新xueqiu-analyzer-skill的描述文档
- opencli fallback PR (#14) code review：原判断C1/C2（公告内容丢失、专栏丢失）被撤回，实际执行流中PDF内容爬取和文章详情爬取对所有路径统一执行；核心问题收敛为M2（opencli链接格式导致公告PDF爬取跳过）

## DECISION
- PR #15修复两个bug后合并：dotenv依赖补入requirements.txt，base_url随key来源自动切换
- PR #14（feat/opencli-fallback）代码质量过关，无Critical问题，核心逻辑正确
- 用户决定暂时不动xueqiu-monitor的未提交日报和未合并分支

## TODO
- [?] 修复PR #14 M2：opencli公告链接格式兼容，确保PDF内容爬取不被跳过
- [?] 修复PR #15 code review提出的3个"必须改"：①消除cli.py和orchestrator.py标题前缀重复代码（提取为shared utility） ②import语句规范化（time/os提到模块顶部） ③补充`extract_title`单元测试
- [?] 修复PR #15建议项：UTF-8校验改为显式surrogate清理、统一HTTP客户端为requests、将`_FALLBACK_KEYS`提为模块常量
- [?] 更新xueqiu-analyzer-skill的SKILL.md描述文档
- [?] 合并3个未合并的远程分支：`feat/ima-integration`、`feat/opencli-fallback`、`feature/param-modes`

---
## 2026-06-08

## FEATURE
- IMA 笔记发布模块集成到 xueqiu-analyzer-skill：新增 `src/xueqiu_analyzer/ima_publisher.py`，支持 `extract_title()` 从 Markdown 提取标题、UTF-8 校验、自动发布到「价值投资研究」笔记本；CLI `analyze`/`reanalyze` 自动加标题前缀并发布到 IMA
- PR #15 合并修复了两个配置 bug：① `requirements.txt` 补 `python-dotenv` 依赖（解决 `.env` 从未加载）② `config.py` 中 `base_url` 跟随 key 来源自动切换（Ark key → Ark endpoint，DS key → DS endpoint）
- 使用 xueqiu-analyzer-skill 完成影石创新 (SH688775) 深度分析，股价 ¥155.56，PE 74.5x，报告含五大风险揭示（天量解禁/增收不增利/大疆竞争/存货暴雷/无人机亏损），IMA 笔记已发布

## BUGFIX
- PR #15 修复 `python-dotenv` 未在依赖中导致 `.env` 从未加载的静默失败问题
- PR #15 修复 base_url 不跟随 fallback key 切换的问题（Ark key + DeepSeek endpoint = 401）
- PR #14 Code Review 撤回：初始判定公告内容丢失(C1)和专栏文章丢失(C2)为 Critical，实为误判——PDF 正文爬取和 Article 详情爬取对所有路径统一执行，opencli 只负责预取列表

## DISCUSS
- PR #14 Code Review 发现 `scripts/stock_fetcher_opencli.py` 与 `src/fetcher_opencli.py` 代码重复约 80%，建议合并或 scripts 版 import src 版
- PR #15 Code Review 发现 `cli.py` 和 `orchestrator._save_results` 存在完全相同的 3 行标题前缀逻辑，建议抽取为共享函数

## DECISION
- 确定 IMA 默认笔记本为「价值投资研究」(folder_id: folder48942b2ec00057d0)，报告自动发布到该笔记本
- PR #14 审查结论：整体质量过关，无 Critical 问题，可以合并；M2（opencli 公告链接格式导致 PDF 爬取跳过）是唯一实质影响，取决于 opencli 工具返回的 URL 格式

## TODO
- [必须] PR #15 修完 3 个问题后合并：① 消除 cli.py 和 orchestrator.py 标题前缀重复代码 ② import 语句提到模块顶部 ③ 为 `ima_publisher.py` 补充 `extract_title` 单元测试
- [建议] PR #14 合并后统一 HTTP 客户端风格（将 `urllib.request` 替换为 `requests`）
- [建议] PR #14 合并后将 `_FALLBACK_KEYS` 提为模块级常量
- [已开 Issue] Issue #16：讨论内容含雪球 icon font PUA 字符污染问题待处理
