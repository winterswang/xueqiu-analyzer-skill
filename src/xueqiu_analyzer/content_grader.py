"""
Content Grader — LLM 驱动的内容质量分级器

按信息密度/可信度/增量价值三维对雪球讨论帖和专栏文章评分，
自动筛选高价值内容，解决「大量噪音覆盖核心信号」的问题。
"""

import json
import re
import logging
from pathlib import Path
from typing import List

from .models import GraderItem, Theme, BatchGraderResult
from .llm_client import LLMClient
from .config import get_config
from .token_utils import estimate_tokens, build_batches

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

BATCH_TOKEN_LIMIT = 65000
PROMPT_TOKEN_OVERHEAD = 2000
MAX_CONTENT_TOKENS = BATCH_TOKEN_LIMIT - PROMPT_TOKEN_OVERHEAD
DEFAULT_QUALITY_THRESHOLD = 10


class ContentGrader:
    """LLM 驱动的内容质量分级器

    分批处理讨论帖和专栏文章，每批按 token 预算自动截断，
    对每条内容输出三维评分，合并后按阈值筛选高质量内容。
    """

    def __init__(self, llm: LLMClient = None, config: dict = None,
                 threshold: int = DEFAULT_QUALITY_THRESHOLD):
        self.llm = llm or LLMClient()
        self.config = config or get_config()
        self.threshold = threshold

    def grade(self, discussions: list,
              articles: list = None) -> BatchGraderResult:
        """评分全部内容。超过 token 预算自动分批，合并返回。

        Args:
            discussions: 讨论帖列表 (dict with author/content/time)
            articles: 专栏文章列表 (dict with author/content/title)

        Returns:
            BatchGraderResult with high_quality_items filtered by threshold
        """
        articles = articles or []

        # 1. 合并讨论 + 专栏, 统一格式化
        all_items = self._merge_items(discussions, articles)

        # 2. 按 token 预算分批
        batches = build_batches(all_items, MAX_CONTENT_TOKENS)
        if not batches:
            return BatchGraderResult(total_items=0, batch_num=0)

        logger.info("ContentGrader: %d 讨论 + %d 专栏 → %d 批次",
                     len(discussions), len(articles), len(batches))

        # 3. 逐批评分
        all_results = []
        for i, batch in enumerate(batches):
            logger.info("评分批次 %d/%d (%d 条)",
                         i + 1, len(batches), len(batch))
            result = self._grade_batch(batch, i + 1)
            all_results.append(result)

        # 4. 合并
        return self._merge_results(all_results)

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

    def _grade_batch(self, batch: list,
                     batch_num: int) -> BatchGraderResult:
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
                    f"作者: {item['author']}\n\n"
                    f"{item['content'][:800]}\n"
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
        # 提取 JSON
        match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if not match:
            match = re.search(r"\{.*\}", response, re.DOTALL)
        if not match:
            logger.warning("无法从 LLM 响应中提取 JSON")
            return BatchGraderResult(
                total_items=total, batch_num=batch_num)

        try:
            data = json.loads(
                match.group(1) if "```" in match.group(0)
                else match.group(0))
        except json.JSONDecodeError:
            logger.warning("JSON 解析失败")
            return BatchGraderResult(
                total_items=total, batch_num=batch_num)

        items = [GraderItem(
            item_id=i.get("item_id", i.get("id", 0)),
            density=i.get("density", 0),
            cred=i.get("cred", 0),
            novelty=i.get("novelty", 0),
            summary=i.get("summary", ""),
        ) for i in data.get("items", [])]

        themes = [
            Theme(
                name=t.get("name", ""),
                bull_side=t.get("bull_side", ""),
                bear_side=t.get("bear_side", ""),
                key_item_ids=t.get("key_item_ids", []),
            ) for t in data.get("themes", [])
        ]

        return BatchGraderResult(
            items=items,
            themes=themes,
            consensus_points=data.get("consensus_points", []),
            info_gaps=data.get("info_gaps", []),
            total_items=total,
            batch_num=batch_num,
        )

    def _merge_results(self,
                       results: List[BatchGraderResult]) -> BatchGraderResult:
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

        # 去重
        merged.consensus_points = list(dict.fromkeys(
            merged.consensus_points))
        merged.info_gaps = list(dict.fromkeys(merged.info_gaps))

        return merged
