# Content Grader — LLM 驱动的内容质量分级器

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 在深度分析前，用 LLM 对雪球讨论帖和专栏文章按信息密度/可信度/增量价值三维评分，自动筛选高价值内容，解决「639条噪音覆盖核心信号」的问题。

**Architecture:** 新增 `ContentGrader` 模块，独立于现有 quality.py（保留纯代码硬指标）。按 Token 预算自动分批 → LLM 评分 → 合并 ≥阈值的结果 → 喂给下游分析。

**Tech Stack:** Python 3.11, DeepSeek API, 现有 `llm_client.py`/`models.py`/`config.py`

**设计决策 (已完成讨论):**
- 分批评分, 每批 ≤ 63K 内容 tokens (Prompt 开销 ~2K, 总计 ≤ 65K 安全线)
- 综合分 = density + cred + novelty, 阈值 ≥ 10 自动筛选
- 两轮 LLM: R1 评分+主题发现, R2 深度分析报告
- 不限制入选条数 — 5 条还是 50 条由内容质量决定

---

## Task 1: 创建 `ContentGrader` 数据模型

**Objective:** 定义评分结果和批量处理的数据结构

**Files:**
- Modify: `src/xueqiu_analyzer/models.py`

**Step 1: 在 models.py 末尾添加 GraderResult 和 BatchGraderResult**

```python
@dataclass
class GraderItem:
    """单条内容评分"""
    item_id: int
    density: int = 0       # 信息密度 1-5
    cred: int = 0          # 来源可信度 1-5
    novelty: int = 0       # 增量价值 1-5
    summary: str = ""      # 一句话概括

    @property
    def combined(self) -> int:
        return self.density + self.cred + self.novelty

    @property
    def is_high_quality(self) -> bool:
        return self.combined >= 10


@dataclass
class Theme:
    """争议主题"""
    name: str
    bull_side: str
    bear_side: str
    key_item_ids: list = field(default_factory=list)


@dataclass
class BatchGraderResult:
    """单批次评分结果"""
    items: list = field(default_factory=list)          # List[GraderItem]
    themes: list = field(default_factory=list)          # List[Theme]
    consensus_points: list = field(default_factory=list)
    info_gaps: list = field(default_factory=list)
    total_items: int = 0
    batch_num: int = 0

    @property
    def high_quality_items(self) -> list:
        return [i for i in self.items if i.is_high_quality]

    @property
    def quality_count(self) -> int:
        return len(self.high_quality_items)


@dataclass
class MergedGraderResult:
    """多批次合并结果"""
    batches: list = field(default_factory=list)
    all_items: list = field(default_factory=list)
    all_themes: list = field(default_factory=list)
    all_consensus: list = field(default_factory=list)
    all_info_gaps: list = field(default_factory=list)

    @property
    def high_quality_count(self) -> int:
        return sum(1 for i in self.all_items if i.is_high_quality)
```

**Step 2: 验证**
```bash
cd ~/code/claude_code/xueqiu-analyzer-skill
PYTHONPATH=src /Users/wangguangchao/.pyenv/versions/3.11.12/bin/python3 -c "
from xueqiu_analyzer.models import GraderItem, BatchGraderResult, MergedGraderResult
item = GraderItem(item_id=1, density=4, cred=3, novelty=5)
assert item.combined == 12
assert item.is_high_quality == True
result = BatchGraderResult(items=[item], total_items=100, batch_num=1)
assert result.quality_count == 1
print('✅ Models OK')
"
```

**Step 3: Commit**
```bash
git add src/xueqiu_analyzer/models.py
git commit -m "feat: add GraderItem, BatchGraderResult, MergedGraderResult models"
```

---

## Task 2: Token 估算工具

**Objective:** 创建 `estimate_tokens()` 函数，按 2x 字符数保守估算

**Files:**
- Create: `src/xueqiu_analyzer/token_utils.py`
- Create: `tests/test_token_utils.py`

**Step 1: 写测试**
```python
# tests/test_token_utils.py
import pytest
from xueqiu_analyzer.token_utils import estimate_tokens, build_batches

def test_estimate_chinese():
    """中文: 2x 字符数"""
    assert estimate_tokens("你好世界") == 8

def test_estimate_english():
    """英文也按 2x"""
    assert estimate_tokens("hello") == 10

def test_estimate_empty():
    assert estimate_tokens("") == 0

def test_estimate_mixed():
    text = "AK112 HR=0.66 降低死亡风险34%"
    assert estimate_tokens(text) == len(text) * 2
```

**Step 2: 验证测试失败**
```bash
PYTHONPATH=src pytest tests/test_token_utils.py -v
# Expected: FAIL — module not found
```

**Step 3: 实现**
```python
# src/xueqiu_analyzer/token_utils.py
def estimate_tokens(text: str) -> int:
    """保守估算 token 数: 字符数 × 2"""
    return len(text) * 2
```

**Step 4: 验证测试通过 + Commit**

---

## Task 3: Token 预算分批器

**Objective:** 实现 `build_batches()` 按 63K token 上限自动分批

**Files:**
- Modify: `src/xueqiu_analyzer/token_utils.py`

**Step 1: 写测试**
```python
# 追加到 tests/test_token_utils.py
def test_build_batches_single():
    items = [{"content": "短帖" * 10}]  # ~300 tokens
    batches = build_batches(items, max_content_tokens=63000)
    assert len(batches) == 1
    assert len(batches[0]) == 1

def test_build_batches_split():
    # 每条 ~10K tokens, 7条会超过 63K 触发第二个 batch
    long = "长" * 5000  # ~10K tokens
    items = [{"content": long} for _ in range(7)]
    batches = build_batches(items, max_content_tokens=63000)
    assert len(batches) == 2

def test_build_batches_empty():
    assert build_batches([], max_content_tokens=63000) == []
```

**Step 2: 实现**
```python
# 追加到 src/xueqiu_analyzer/token_utils.py
def build_batches(items: list, max_content_tokens: int = 63000) -> list:
    """按 token 预算分批"""
    batches = []
    current_batch = []
    current_tokens = 0

    for item in items:
        content = item.get("content", "")
        author = item.get("author", "")
        item_tokens = estimate_tokens(f"{author}\n{content}")

        if current_batch and current_tokens + item_tokens > max_content_tokens:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0

        current_batch.append(item)
        current_tokens += item_tokens

    if current_batch:
        batches.append(current_batch)

    return batches
```

**Step 3: 验证 + Commit**

---

## Task 4: ContentGrader 核心类

**Objective:** 实现 LLM 驱动的评分器，接收一批讨论帖返回结构化评分

**Files:**
- Create: `src/xueqiu_analyzer/content_grader.py`
- Create: `tests/test_content_grader.py`

**Step 1: 写核心逻辑**
```python
# src/xueqiu_analyzer/content_grader.py
import json
import logging
from pathlib import Path
from typing import List

from .models import GraderItem, Theme, BatchGraderResult
from .llm_client import LLMClient
from .config import get_config
from .token_utils import build_batches

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

BATCH_TOKEN_LIMIT = 65000
PROMPT_TOKEN_OVERHEAD = 2000
MAX_CONTENT_TOKENS = BATCH_TOKEN_LIMIT - PROMPT_TOKEN_OVERHEAD
QUALITY_THRESHOLD = 10


class ContentGrader:
    """LLM 驱动的内容质量分级器"""

    def __init__(self, llm: LLMClient = None, config: dict = None,
                 threshold: int = QUALITY_THRESHOLD):
        self.llm = llm or LLMClient()
        self.config = config or get_config()
        self.threshold = threshold

    def grade_discussions(self, discussions: list,
                          articles: list = None) -> BatchGraderResult:
        """
        评分全部讨论。超过 token 预算自动分批。
        """
        # 1. 合并讨论 + 专栏, 统一格式化
        all_items = self._merge_items(discussions, articles or [])

        # 2. 分批
        batches = build_batches(all_items, MAX_CONTENT_TOKENS)
        if not batches:
            return BatchGraderResult(total_items=0, batch_num=0)

        logger.info(f"讨论 {len(discussions)} + 专栏 {len(articles or [])} "
                    f"→ {len(batches)} 批次")

        # 3. 逐批评分
        all_batch_results = []
        for i, batch in enumerate(batches):
            logger.info(f"评分批次 {i+1}/{len(batches)} ({len(batch)} 条)")
            result = self._grade_batch(batch, i + 1)
            all_batch_results.append(result)

        # 4. 合并结果
        return self._merge_results(all_batch_results)

    def _merge_items(self, discussions: list, articles: list) -> list:
        items = []
        for d in discussions:
            items.append({
                "id": len(items) + 1,
                "type": "discussion",
                "author": d.get("author", ""),
                "content": d.get("content", ""),
                "time": d.get("time", ""),
                "raw": d,
            })
        for a in articles:
            items.append({
                "id": len(items) + 1,
                "type": "article",
                "author": a.get("author", ""),
                "content": a.get("content", ""),
                "title": a.get("title", ""),
                "raw": a,
            })
        return items

    def _grade_batch(self, batch: list, batch_num: int) -> BatchGraderResult:
        # 构建 prompt
        prompt = self._build_prompt(batch)
        response = self.llm.simple_chat(prompt, max_tokens=8000)
        return self._parse_response(response, len(batch), batch_num)

    def _build_prompt(self, batch: list) -> str:
        template_path = _PROMPTS_DIR / "content_grader.md"
        template = template_path.read_text(encoding="utf-8")

        parts = []
        for item in batch:
            if item["type"] == "article":
                parts.append(
                    f"### 专栏{item['id']}: {item['title']}\n"
                    f"作者: {item['author']}\n\n{item['content'][:800]}\n"
                )
            else:
                parts.append(
                    f"### 帖子{item['id']}\n"
                    f"作者: {item['author']} | 时间: {item['time']}\n\n"
                    f"{item['content'][:600]}\n"
                )
        return template.replace("{{content}}", "\n".join(parts))

    def _parse_response(self, response: str, total: int,
                        batch_num: int) -> BatchGraderResult:
        import re
        # 提取 JSON
        match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if not match:
            match = re.search(r"\{.*\}", response, re.DOTALL)
        if not match:
            logger.warning("无法从 LLM 响应中提取 JSON")
            return BatchGraderResult(total_items=total, batch_num=batch_num)

        try:
            data = json.loads(match.group(1) if "```" in match.group(0)
                              else match.group(0))
        except json.JSONDecodeError:
            logger.warning("JSON 解析失败")
            return BatchGraderResult(total_items=total, batch_num=batch_num)

        items = [GraderItem(**i) for i in data.get("items", [])]
        themes = [Theme(**t) for t in data.get("themes", [])]

        return BatchGraderResult(
            items=items,
            themes=themes,
            consensus_points=data.get("consensus_points", []),
            info_gaps=data.get("info_gaps", []),
            total_items=total,
            batch_num=batch_num,
        )

    def _merge_results(self, results: list) -> BatchGraderResult:
        """合并多个批次的评分结果"""
        if len(results) == 1:
            return results[0]

        merged = BatchGraderResult(
            items=[],
            themes=[],
            consensus_points=[],
            info_gaps=[],
            total_items=sum(r.total_items for r in results),
            batch_num=0,
        )
        for r in results:
            merged.items.extend(r.items)
            merged.themes.extend(r.themes)
            merged.consensus_points.extend(r.consensus_points)
            merged.info_gaps.extend(r.info_gaps)

        # 去重 consensus 和 info_gaps
        merged.consensus_points = list(dict.fromkeys(merged.consensus_points))
        merged.info_gaps = list(dict.fromkeys(merged.info_gaps))

        return merged
```

**Step 2: Commit**
```bash
git add src/xueqiu_analyzer/content_grader.py
git commit -m "feat: add ContentGrader — LLM-driven discussion quality scoring"
```

---

## Task 5: 集成到 orchestrator.py

**Objective:** 在 analyze 流程中插入 ContentGrader，用精选讨论替代全量

**Files:**
- Modify: `src/xueqiu_analyzer/orchestrator.py`

**Step 1: 修改 `run()` 方法**

在 `_iterative_crawl` 返回后、`evaluate` 之前插入：

```python
# orchestrator.py, run() 方法中, _iterative_crawl 之后:

# 1.6 内容分级 — 用 LLM 筛选高价值讨论和专栏
grader_config = self.config.get('grader', {})
if grader_config.get('enabled', True):
    from .content_grader import ContentGrader
    grader = ContentGrader(
        config=self.config,
        threshold=grader_config.get('threshold', 10)
    )
    grade_result = grader.grade_discussions(
        discussions=crawl_result.discussions,
        articles=crawl_result.articles
    )
    logger.info(
        f"内容分级: {len(crawl_result.discussions)}条讨论 + "
        f"{len(crawl_result.articles)}篇专栏 → "
        f"{grade_result.quality_count}条高质量内容"
    )
    # 用精选内容替换全量
    # 保留公告和资讯不变 (它们已经是相对高质量的信源)
```

**Step 2: 更新 config.yaml**
```yaml
# 追加到 config/config.yaml
grader:
  enabled: true
  threshold: 10  # combined ≥ 10 入选
```

**Step 3: Commit**

---

## Task 6: 新增 CLI 命令 `grade`

**Objective:** 独立运行的评分命令，用于调试和手动验证

**Files:**
- Modify: `src/xueqiu_analyzer/cli.py`

**Step 1: 添加命令**
```python
@cli.command()
@click.option("--data", required=True, help="数据文件路径")
@click.option("--threshold", default=10, help="高质量阈值")
def grade(data, threshold):
    """对已爬取数据进行内容质量评分"""
    with open(data, "r", encoding="utf-8") as f:
        raw = json.load(f)

    crawl_result = CrawlResult.from_dict(raw)
    grader = ContentGrader(threshold=threshold)
    result = grader.grade_discussions(
        discussions=crawl_result.discussions,
        articles=crawl_result.articles,
    )

    click.echo(f"\n{'='*50}")
    click.echo(f"内容质量评分: {crawl_result.symbol}")
    click.echo(f"{'='*50}")
    click.echo(f"总内容: {result.total_items} 条")
    click.echo(f"高质量(≥{threshold}): {result.quality_count} 条")
    click.echo(f"批次: {result.batch_num}")

    if result.themes:
        click.echo(f"\n争议主题 ({len(result.themes)}):")
        for t in result.themes:
            click.echo(f"  📌 {t.name}")
            click.echo(f"     看多: {t.bull_side[:80]}...")
            click.echo(f"     看空: {t.bear_side[:80]}...")

    if result.consensus_points:
        click.echo(f"\n共识 ({len(result.consensus_points)}):")
        for p in result.consensus_points:
            click.echo(f"  ✅ {p}")

    if result.info_gaps:
        click.echo(f"\n缺失信息 ({len(result.info_gaps)}):")
        for g in result.info_gaps:
            click.echo(f"  ❓ {g}")
```

**Step 2: Commit**

---

## Task 7: 编写集成测试

**Objective:** 验证完整的评分流程

**Files:**
- Modify: `tests/test_content_grader.py`

```python
def test_batch_grading_with_mock_llm():
    from unittest.mock import patch
    from xueqiu_analyzer.content_grader import ContentGrader

    mock_response = json.dumps({
        "items": [
            {"item_id": 1, "density": 4, "cred": 3, "novelty": 5, "combined": 12,
             "summary": "OS HR=0.66 确立双抗优势"},
            {"item_id": 2, "density": 1, "cred": 1, "novelty": 1, "combined": 3,
             "summary": "纯情绪帖"}
        ],
        "themes": [],
        "consensus_points": [],
        "info_gaps": []
    })

    with patch.object(LLMClient, 'simple_chat', return_value=mock_response):
        grader = ContentGrader()
        discussions = [
            {"author": "A", "content": "重要分析" * 50, "time": "1h"},
            {"author": "B", "content": "涨", "time": "2h"},
        ]
        result = grader.grade_discussions(discussions)

    assert result.total_items == 2
    assert result.quality_count == 1
    high = result.high_quality_items[0]
    assert high.combined == 12
    assert high.is_high_quality is True
```

---

## Task 8: 文档更新 + 最终验证

**Objective:** 更新 README + 运行全量测试

```bash
# 运行全部测试
PYTHONPATH=src pytest tests/ -v

# 手动验证
PYTHONPATH=src python -m xueqiu_analyzer.cli grade --data data/09926_data.json
```

---

## 任务依赖图

```
Task 1 (models) ──► Task 2 (token_utils) ──► Task 3 (build_batches)
                                                    │
                                                    ▼
Task 4 (ContentGrader) ◄────────────────────  Task 2 + Task 3
        │
        ├──► Task 5 (orchestrator 集成)
        ├──► Task 6 (CLI grade 命令)
        └──► Task 7 (集成测试)

Task 8 (文档 + 最终验证) ← 全部完成后
```

---

## 新增文件清单

| 文件 | 说明 |
|------|------|
| `prompts/content_grader.md` | ✅ 已创建 (本次会话) |
| `src/xueqiu_analyzer/content_grader.py` | ContentGrader 核心类 |
| `src/xueqiu_analyzer/token_utils.py` | estimate_tokens + build_batches |
| `tests/test_content_grader.py` | 评分器测试 |
| `tests/test_token_utils.py` | Token 工具测试 |

## 修改文件清单

| 文件 | 改动 |
|------|------|
| `src/xueqiu_analyzer/models.py` | 新增 GraderItem, Theme, BatchGraderResult |
| `src/xueqiu_analyzer/orchestrator.py` | 插入 ContentGrader 调用 |
| `src/xueqiu_analyzer/cli.py` | 新增 `grade` 命令 |
| `config/config.yaml` | 新增 `grader` 配置节 |
