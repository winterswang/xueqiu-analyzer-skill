# xueqiu-analyzer V3 — Code Review 报告 V2（独立验证版）

> 验证日期：2026-05-24 | 验证方：DeepSeek-TUI v0.8.40 (deepseek-v4-pro) | 基于 CR_REPORT_V1 逐项复审

---

## 一、逐项验证结果

### I-01：Prompt 模板未用 Jinja2
- **判定：✅ 确认存在**
- `src/` 全量 grep `jinja|Jinja` 返回 0 匹配
- `evaluator.py:64-94` 全程 `template.replace('{{var}}', value)`
- `analyzer.py:106-109` 同样 `str.replace`
- `prompts/evaluation.md`、`prompts/analysis.md` 只使用 `{{var}}` 占位符，无 Jinja2 控制流标签
- `requirements.txt` L5 列出 `jinja2>=3.0`，从未被 import
- TECHNICAL.md §3.4 的 `{% for %}` 代码示例与实际模板完全无关
- **纠正**：V1 说 `str.replace` 对同一占位符只替换首次——Python 的 `str.replace(old, new)` 默认替换**所有**出现，这个具体说法不准确
- 严重度：**维持 5**

### I-02：cookies 双写到 `~/.xueqiu_crawler/`
- **判定：✅ 确认存在（实际风险极低）**
- `crawler.py:336-348` `_save_cookies()` 写 `~/.xueqiu_crawler/cookies.json` + `config/cookies/xueqiu.json`
- `cli.py:232-241` `_import_cookies()` 同样双写
- `.gitignore` L27 已排除 `config/cookies/`，未排除 `~/.xueqiu_crawler/`
- 实际仓库根在 `/root/code/xueqiu-analyzer-skill`，家目录路径不在仓库内，不会进 Git
- 严重度：**5 → 3**（无真正泄露风险）

### I-03：`_js_click` 字符串拼接潜在 JS 注入
- **判定：✅ 确认存在（模式不安全，无实际攻击面）**
- `crawler.py:421-434` `page.evaluate(f'...{text}...')`
- 调用链全部硬编码常量：`'讨论'`/`'资讯'`/`'公告'`，无外部输入
- 严重度：**5 → 3**（纯理论安全模式问题）

### I-04：config.yaml 缺少 evaluator 和 notify 配置段
- **判定：✅ 确认存在**
- `config/config.yaml` 实际只有 `llm`/`crawler`/`storage`/`analysis` 四段
- `config.py` 为 evaluator/notify 提供硬编码默认值
- TECHNICAL.md:188-205 明确列出了配置结构
- 严重度：**维持 4**

### I-05：config.yaml crawler 缺少 max_pages，默认值不一致
- **判定：⚠️ 部分准确**
- `crawler.py:49` 函数签名默认 `max_pages=5`
- `cli.py:82` Click option 默认 `5`
- `config.py` fallback 默认 `max_pages: 10`
- TECHNICAL.md:185 设计值 `max_pages: 10`
- **V1 说"代码默认10"不够精确**——有两个地方定义，分别是 10 和 5
- 严重度：**维持 4**

### I-06：analyzer._format_content() 无截断
- **判定：✅ 确认存在**
- `evaluator.py:107` articles `[:2000]`, discussions `[:500]`, news `[:1500]`, notices `[:1000]`
- `analyzer.py:113-149` 无任何截断，全文输出
- 严重度：**维持 4**

### I-07：缺少 akshare/akshare_service 依赖声明
- **判定：✅ 确认存在**
- `requirements.txt` 不包含这两个包
- `financial_fetcher.py` 用 try/except 降级
- 严重度：**维持 4**

### I-08：run() 62行，略微超标
- **判定：✅ 确认存在**
- `orchestrator.py:32-93`，去除 docstring+空行后纯逻辑 ~45 行
- TECHNICAL.md:425 明确要求 ≤50 行
- 严重度：**3 → 2**（纯逻辑不超标，格式行数超标属风格问题）

### I-09：TECHNICAL.md 声称但实际不存在的文件
- **判定：✅ 确认存在**
- `cookie_manager.py`、`notifier.py`、`tests/test_analyzer.py`、`tests/test_models.py`、`tests/fixtures/sample_data.json` 均不存在
- 严重度：**维持 3**

### I-10：Token 统计用 `字符数×2` 过于粗糙
- **判定：✅ 确认存在**
- `evaluator.py:215-234` 对所有语言统一 ×2
- 中文 ≈1.5-2 char/token，英文 ≈4 char/token
- 严重度：**维持 3**

### I-11：SameSite 驼峰命名处理
- **判定：✅ 确认存在** — `cli.py:225` 硬编码驼峰
- 严重度：**维持 2**

### I-12：多处 import 放在函数内部
- **判定：⚠️ 需区分**
- **合理**（可选依赖懒加载）：financial_fetcher 的 akshare、crawler 的 yaml
- **不合理**（标准库）：cli.py 的 `import time`、orchestrator.py 的 `import subprocess` 和 `import os`（os 已在顶部导入）
- 严重度：**维持 2**

### I-13：financial_bonus 降级逻辑
- **判定：⚠️ 部分准确**
- `evaluator.py:189-192` 已覆盖 None/0/缺失，但 `data.get('financial_bonus', 0)` 返回 0 时与 LLM 真的给了 0 分无法区分
- 严重度：**维持 2**

### I-14：Discussion.content 正则可能误移除正文
- **判定：✅ 确认存在（误伤概率修正为"低"）**
- `crawler.py:490-493` `re.MULTILINE` 模式下 `$` 匹配行尾，只有以这些词**开头**的行才会被移除整行
- 如"公司计划展开海外业务"（展开在行中间）不会被匹配
- 严重度：**维持 2**

### I-15 ~ I-16：风格问题
- **判定：✅ 确认存在**
- 严重度：**维持 1**

### I-17：is_sufficient 硬编码阈值 150
- **判定：✅ 确认存在**
- `models.py:187` `is_sufficient` property 和 `evaluator.py:195` `_build_result()` 独立硬编码 150/100
- `config.py` 的 `score_threshold: 150` 仅被 `orchestrator.py` 使用
- 修改配置阈值不会改变 `is_sufficient` 的判定
- 严重度：**1 → 3**（配置驱动设计的实际漏洞）

---

## 二、新发现问题（CR V1 未覆盖）

### N-01：config.py `get_config()` 缓存永不刷新（严重度 4）
- `config.py:65-68` `get_config._cache` 首次调用后永久缓存
- `reload=True` 参数未实际使用
- 影响：运行时环境变量变化后配置不会更新

### N-02：notify 配置中 feishu_target 环境变量占位符未被解析（严重度 4）
- `config.py:90-93` `get_config()` 直接取 yaml 值，未调用 `_resolve_env()`
- `config.yaml` 中 `feishu_target: "${FEISHU_TARGET_USER}"` 会原样保留字符串
- 实际被 `orchestrator.py:263-265` 从 os.environ 直接读取掩盖

### N-03：evaluator._build_result 与 EvaluationResult.is_sufficient 双重硬编码（严重度 3）
- 阈值 150/100 在两处独立硬编码，修改需同步两处
- 与 I-17 相关但更具体指出故障模式

### N-04：orchestrator.py `_notify()` 中 `import os` 冗余（严重度 1）
- `os` 已在模块顶部导入

### N-05：prompts/ 模板用 `{{var}}` 而非 Jinja2 `{% %}` 语法（严重度 3）
- V1 的 I-01 指出代码没用 Jinja2；但模板文件本身也按纯字符串替换设计
- TECHNICAL.md §3.4 的 `{% for %}` 代码示例在两层上都是虚构的

### N-06：.gitignore 排除 `data/` 但文件已被 Git 跟踪（严重度 2）
- `data/reports/*.md` 和 `config/cookies/xueqiu.json` 仍出现在项目目录中
- 需 `git rm --cached` 清理

---

## 三、验证汇总

### 判定统计

| 判定 | 数量 | Issues |
|------|------|--------|
| ✅ 确认存在 | 13 | I-01, I-02, I-03, I-04, I-06, I-07, I-08, I-09, I-10, I-11, I-14, I-15, I-16 |
| ⚠️ 部分准确 | 4 | I-05, I-12, I-13, I-17 |
| ❌ 误报 | 0 | — |

### 严重度修正

| Issue | V1 | V2 | 理由 |
|-------|----|----|------|
| I-02 | 5 | 3 | 家目录不在 Git 仓库范围 |
| I-03 | 5 | 3 | 无外部输入路径 |
| I-08 | 3 | 2 | 纯逻辑不超标 |
| I-17 | 1 | 3 | 配置驱动的实际漏洞 |

### 修正后严重度分布

| 严重度 | V1 | V2 | 变化 |
|--------|----|----|------|
| 🔴 5 | 3 | 1 | I-01 仅剩一项 |
| 🟠 4 | 4 | 4 | 无变化 |
| 🟡 3 | 3 | 7 | +4（降级+升格+新增） |
| 🟢 2 | 4 | 5 | +1 |
| ⚪ 1 | 3 | 3 | 无变化 |
| **V1 Issues** | **17** | **17** | — |
| **新增 Issues** | — | **6** | N-01 ~ N-06 |

### 总体评价
V1 报告的 17 个 Issues **无一误报**，13 个完全准确，4 个细节需微调。严重度 4 处修正，新发现 6 个问题。核心结论与 V1 一致：文档漂移和配置完整性是最紧迫的改进方向。
