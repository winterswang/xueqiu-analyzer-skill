import json
import pytest
from unittest.mock import patch, MagicMock

from xueqiu_analyzer.content_grader import ContentGrader, DEFAULT_QUALITY_THRESHOLD
from xueqiu_analyzer.models import GraderItem, BatchGraderResult
from xueqiu_analyzer.llm_client import LLMClient


MOCK_GRADE_RESPONSE = json.dumps({
    "items": [
        {"item_id": 1, "density": 4, "cred": 3, "novelty": 5,
         "combined": 12, "summary": "OS HR=0.66 确立双抗优势"},
        {"item_id": 2, "density": 1, "cred": 1, "novelty": 1,
         "combined": 3, "summary": "纯情绪帖"},
    ],
    "themes": [
        {"name": "估值分歧", "bull_side": "投行目标价 162-224",
         "bear_side": "港股空头压力", "key_item_ids": [1]},
    ],
    "consensus_points": ["AK112 临床数据超预期"],
    "info_gaps": ["HARMONi-3 全球 III 期结果"],
})


class TestContentGrader:
    def test_batch_grading_with_mock_llm(self):
        """完整评分流程: 讨论 → LLM评分 → 结果解析"""
        with patch.object(LLMClient, 'simple_chat',
                          return_value=MOCK_GRADE_RESPONSE):
            grader = ContentGrader()
            discussions = [
                {"author": "分析师A", "content": "重要分析" * 50, "time": "1h"},
                {"author": "路人B", "content": "涨", "time": "2h"},
            ]
            result = grader.grade(discussions)

        assert result.total_items == 2
        assert result.quality_count == 1
        assert result.high_quality_items[0].combined == 12
        assert result.high_quality_items[0].is_high_quality is True
        assert len(result.themes) == 1
        assert result.themes[0].name == "估值分歧"
        assert len(result.consensus_points) == 1
        assert len(result.info_gaps) == 1

    def test_grade_empty_discussions(self):
        grader = ContentGrader()
        result = grader.grade([])
        assert result.total_items == 0
        assert result.quality_count == 0

    def test_grade_with_articles(self):
        """讨论+专栏混合评分"""
        with patch.object(LLMClient, 'simple_chat',
                          return_value=MOCK_GRADE_RESPONSE):
            grader = ContentGrader()
            result = grader.grade(
                discussions=[{"author": "A", "content": "讨论", "time": "1h"}],
                articles=[{"author": "B", "content": "专栏" * 100,
                            "title": "深度分析"}],
            )
        # 2 items total (1 discussion + 1 article)
        assert result.total_items == 2

    def test_threshold_configurable(self):
        with patch.object(LLMClient, 'simple_chat',
                          return_value=MOCK_GRADE_RESPONSE):
            grader = ContentGrader(threshold=13)
            result = grader.grade(
                [{"author": "A", "content": "x" * 50, "time": "1h"}])
        # combined=12 < threshold=13, filter_by_threshold returns 0
        assert len(result.filter_by_threshold(13)) == 0
        # default threshold=10 still has 1
        assert len(result.filter_by_threshold(10)) == 1

    def test_parse_response_no_json(self):
        grader = ContentGrader()
        result = grader._parse_response("纯文本无JSON", 10, 1)
        assert result.total_items == 10
        assert result.items == []

    def test_parse_response_json_in_text(self):
        grader = ContentGrader()
        resp = f"评分如下：```json\n{MOCK_GRADE_RESPONSE}\n```"
        result = grader._parse_response(resp, 2, 1)
        assert result.quality_count == 1

    def test_merge_multiple_batches(self):
        r1 = BatchGraderResult(
            items=[GraderItem(item_id=1, density=5, cred=4, novelty=5)],
            consensus_points=["共识A"],
            info_gaps=["缺失A"],
            total_items=1, batch_num=1,
        )
        r2 = BatchGraderResult(
            items=[GraderItem(item_id=2, density=1, cred=1, novelty=2)],
            consensus_points=["共识A"],  # duplicate
            info_gaps=["缺失B"],
            total_items=1, batch_num=2,
        )
        grader = ContentGrader()
        merged = grader._merge_results([r1, r2])
        assert merged.total_items == 2
        assert merged.quality_count == 1  # only r1's item
        assert len(merged.consensus_points) == 1  # deduped
        assert len(merged.info_gaps) == 2
