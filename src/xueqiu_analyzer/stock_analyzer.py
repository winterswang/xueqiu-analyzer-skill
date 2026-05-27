"""
xueqiu-analyzer V4 — 深度舆情分析器（多 LLM 调用版）

策略：
- input_token_limit: 每次 LLM 调用输入上限（约 70k tokens，含充分 thinking space）
- 讨论按 50 条/组 分组 → 每组一次 LLM 调用 → 各组独立分析
- 专栏、新闻、公告各一组 → 最终合成
- 每次调用 output≈15k tokens → 充分 thinking + 结构化输出
"""

import json
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from .crawler import XueqiuCrawler
from .llm_client import LLMClient
from .models import CrawlResult

logger = logging.getLogger(__name__)

DEFAULT_STORAGE_DIR = Path('~/.xueqiu_stocks').expanduser()

# ─── LLM 输出格式标准化 ─────────────────────────────────────────
def _norm_confidence(v):
    if not isinstance(v, str): return "中"
    v = v.strip()
    if v in ("高", "high"): return "高"
    if v in ("低", "low"): return "低"
    return "中"

def _norm_bull_bear_balance(v):
    if not isinstance(v, str): return "均势"
    v = v.strip()
    if v in ("多方主导", "多方", "多头主导"): return "多方主导"
    if v in ("空方主导", "空方", "空头主导"): return "空方主导"
    return "均势"

def _norm_sentiment(v):
    if not isinstance(v, str): return "中性"
    v = v.strip()
    if v in ("看多", "多头", "正面"): return "看多"
    if v in ("看空", "空头", "负面"): return "看空"
    if v in ("分化", "分歧", "均势"): return "分化"
    return "中性"

def _norm_source_indices(indices):
    import re
    result = []
    if isinstance(indices, str): indices = [indices]
    for idx in indices:
        if isinstance(idx, int):
            result.append(idx)
        elif isinstance(idx, str):
            nums = re.findall(r'\d+', idx)
            result.extend([int(n) for n in nums])
        elif isinstance(idx, dict) and 'index' in idx:
            result.append(int(idx['index']))
    return sorted(set(result))

def _post_normalize_chunk(r):
    if 'summary' in r: r['summary'] = str(r['summary'])[:80]
    if 'signal_strength' in r: r['signal_strength'] = str(r.get('signal_strength', '中'))
    if 'overall_sentiment' in r: r['overall_sentiment'] = _norm_sentiment(r.get('overall_sentiment', ''))
    if 'cross_item_agreement' in r: r['cross_item_agreement'] = str(r.get('cross_item_agreement', '无明确信号'))
    for item in r.get('high_value_items', []):
        if 'sentiment' in item: item['sentiment'] = _norm_sentiment(item['sentiment'])
        if 'value_level' in item:
            item['value_level'] = "高" if item['value_level'] in ("高", "high") else "低" if item['value_level'] in ("低", "low") else "中"
    return r

def _post_normalize_synth(r):
    if 'summary' in r: r['summary'] = str(r['summary'])[:120]
    for pt in r.get('bull_points', []):
        if isinstance(pt, dict):
            pt['confidence'] = _norm_confidence(pt.get('confidence', '中'))
            pt['point'] = str(pt.get('point', ''))[:100]
            pt['source_indices'] = _norm_source_indices(pt.get('source_indices', []))
        else:
            r['bull_points'][r['bull_points'].index(pt)] = {
                'point': str(pt)[:100], 'confidence': '中', 'source_indices': []
            }
    for pt in r.get('bear_points', []):
        if isinstance(pt, dict):
            pt['confidence'] = _norm_confidence(pt.get('confidence', '中'))
            pt['point'] = str(pt.get('point', ''))[:100]
            pt['source_indices'] = _norm_source_indices(pt.get('source_indices', []))
        else:
            r['bear_points'][r['bear_points'].index(pt)] = {
                'point': str(pt)[:100], 'confidence': '中', 'source_indices': []
            }
    for topic in r.get('topics', []):
        topic['bull_bear_balance'] = _norm_bull_bear_balance(topic.get('bull_bear_balance', '均势'))
        topic['sentiment'] = _norm_sentiment(topic.get('sentiment', '中性'))
        if 'mentions' in topic:
            try: topic['mentions'] = int(topic['mentions'])
            except: topic['mentions'] = 0
    for d in r.get('high_value_discussions', []):
        d['sentiment'] = _norm_sentiment(d.get('sentiment', '中性'))
    for n in r.get('key_notices', []):
        r_v = str(n.get('relevance', '中')).strip()
        n['relevance'] = "高" if r_v in ("高", "high") else "低" if r_v in ("低", "low") else "中"
    return r



# 估算：讨论 50 条 × 500 字 ≈ 25k chars ≈ 8-12k tokens
# 专栏 5 篇 × 2000 字 ≈ 10k chars ≈ 4-5k tokens
DISC_CHUNK_SIZE = 50
COL_CHUNK_SIZE = 5
NEWS_CHUNK_SIZE = 10
NOTICE_CHUNK_SIZE = 10

# 每次 LLM 调用 max_tokens
LLM_MAX_TOKENS = 16000

_ANALYZE_CHUNK_PROMPT = """你是一位专业、严谨的价值投资研究助手，专注于雪球舆情分析。

请分析以下雪球舆情数据，输出结构化 JSON。每条原文有 index 和 time 字段。

【数据来源类型】：{data_type}
【本组数据范围】：共 {total_items} 条中的第 {start_idx}-{end_idx} 条

━━━ 分析维度 ━━━━━━━━━━━━━━━━━━━━━━━
1. 识别具体事实 vs 主观感受（具体事实更有价值）
2. 关注含数据/数字的具体观点（股价、PE、增速、回购额等）
3. 识别主流与非主流观点（非主流但有逻辑的观点同样重要）
4. 区分"即时情绪反应"和"有依据的判断"
5. 注意时间信号：近期发帖权重略高

━━━ 输出格式 ━━━━━━━━━━━━━━━━━━━━━━━
严格输出 JSON，不要任何其他内容：
{{
  "summary": "本组核心观点（30字以内，归纳性描述）",
  "signal_strength": "强/中/弱（强=有数据支撑的判断，中=逻辑推理，弱=情绪表达）",
  "overall_sentiment": "看多/中性/看空/分化",
  "high_value_items": [
    {{
      "index": N,
      "author": "作者",
      "content": "原文摘要（80字以内，保留关键词和数字）",
      "sentiment": "看多/中性/看空",
      "signal_type": "数据型/逻辑型/情绪型/消息型",
      "value_level": "高/中/低",
      "specific_claims": ["具体主张或数据（如：股价<1000、PE<20、回购10亿）"],
      "why_valuable": "这条内容的核心价值说明（20-40字，说明数据来源和推断逻辑）"
    }}
  ],
  "group_topics": [
    {{
      "name": "话题名",
      "mentions_estimate": 本组内提及次数（估算整数）,
      "sentiment": "看多/中性/看空/分化",
      "bull_bear_balance": "多方主导/空方主导/均势"
    }}
  ],
  "bull_points": ["从原文提炼的看多具体依据（必须对应具体index）"],
  "bear_points": ["从原文提炼的看空具体依据（必须对应具体index）"],
  "cross_item_agreement": "统一/分歧/无明确信号（各条目观点是否一致）",
  "intra_group_conflicts": ["组内存在的重大观点矛盾（如有，否则写无）"]
}}

━━━ 负面约束（绝对禁止） ━━━━━━━━━━━━━━━━━━━
1. 禁止将多个 index 的内容合并成一条 high_value_items
2. 禁止在 specific_claims 中放入主观判断或无法溯源的主张
3. 禁止在 bull_points / bear_points 中写入与原文不符的内容
4. high_value_items 数量建议 3-8 条，不要把所有条目都放进去

━━━ index 引用规则 ━━━━━━━━━━━━━━━━━
- index 是下方【原文数据】中的序号
- 只引用真正有价值的 index，不必覆盖所有条目
- 无价值的条目（纯情绪发泄、无实质内容）应忽略

━━━ 原文数据 ━━━━━━━━━━━━━━━━━━━━━━━
{data_block}

请严格输出 JSON，不要输出任何任何内容。"""

_ANALYZE_SYNTHESIZE_PROMPT = """你是一位专业、严谨的价值投资研究助手，专注于雪球舆情分析。

以下是同一只股票的多组舆情分析结果，请将其合成为一份完整的结构化投资报告。

━━━ 概念区分（重要） ━━━━━━━━━━━━━━━━━━━━━━━
- bear_points：雪球舆论中已确认的看空论点（来自原文，有 source_indices 溯源）
- concerns：LLM 推断的认知不确定性——即这条信息哪里不可靠、需要核实什么
  （与 bear_points 独立，不重复；关注的是"信度"而非"空方"）

━━━ 输入信息 ━━━━━━━━━━━━━━━━━━━━━━━━━
【股票】：{symbol}
【分析组数】：{num_groups} 组

【各组摘要】
{group_summaries}

【各组详细内容】
{group_details}

━━━ 跨组矛盾处理 ━━━━━━━━━━━━━━━━━━━━━━━━━
如果不同组分块结论存在重大矛盾（例如：一组说"AI进展强劲"，另一组说"AI无实质进展"），必须：
1. 在对应 topic 下同时呈现两种观点，不掩盖矛盾
2. 用 bull_bear_balance: "均势" 标注该 topic
3. 在 summary 中体现这种分歧，不强行统一

━━━ 输出格式 ━━━━━━━━━━━━━━━━━━━━━━━
严格输出 JSON，不要任何其他内容：
{{
  "summary": "股票舆情核心摘要（60字以内），必须体现多空分歧程度",
  "bull_points": [
    {{"point": "看多点", "source_indices": [index列表（整数）], "confidence": "高/中/低"}}
  ],
  "bear_points": [
    {{"point": "风险点", "source_indices": [index列表（整数）], "confidence": "高/中/低"}}
  ],
  "topics": [
    {{
      "name": "话题名",
      "mentions": 提及次数（估算整数）,
      "sentiment": "看多/中性/看空/分化",
      "key_views": ["核心观点1（附index）", "核心观点2（附index）"],
      "bull_bear_balance": "多方主导/空方主导/均势"
    }}
  ],
  "high_value_columns": [
    {{
      "index": 原文index（整数）,
      "author": "作者",
      "title": "标题",
      "key_points": "核心要点（100字以内）",
      "investment_thesis": "看多/看空/中性"
    }}
  ],
  "high_value_discussions": [
    {{
      "index": 原文index（整数）,
      "author": "作者",
      "content": "内容摘要（60字以内）",
      "sentiment": "看多/中性/看空",
      "signal_type": "数据型/逻辑型/情绪型/消息型"
    }}
  ],
  "key_notices": [
    {{
      "index": 原文index（整数）,
      "title": "公告标题",
      "time": "日期",
      "key_info": "关键信息（60字以内）",
      "relevance": "高/中/低"
    }}
  ],
  "actionable_insights": [
    {{"insight": "具体可执行洞见", "basis": "依据（附index）"}}
  ],
  "concerns": [
    {{
      "concern": "认知不确定性描述（这条信息哪里不可靠/需要核实什么）",
      "reason": "为什么不能直接相信（20-40字）",
      "verification": "需要查证的具体信息（10-20字）"
    }}
  ],
  "data_gaps": ["哪些信息不足需要补充"]
}}

━━━ 质量要求 ━━━━━━━━━━━━━━━━━━━━━━━
- bull_points / bear_points 必须有 source_indices（指向原文index，整数列表）
- topics 必须有 bull_bear_balance（多方/空方/均势）
- concerns 必须有 reason 和 verification（与 bear_points 独立，不重复）
- 所有重要结论需可溯源到具体 index（整数）
- 注意识别：各组之间的矛盾观点、分歧结论

请严格输出 JSON，不要输出任何其他内容。"""


class DeepAnalyzer:
    """深度舆情分析器（多 LLM 调用版）"""

    def __init__(self, crawler: XueqiuCrawler = None,
                 llm_client: LLMClient = None,
                 storage_dir: Path = None):
        self.crawler = crawler or XueqiuCrawler()
        self.llm = llm_client or LLMClient()
        self.storage_dir = storage_dir or DEFAULT_STORAGE_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def analyze(self, symbol: str,
                max_pages: int = 10,
                days: int = 0,
                max_articles: int = 10,
                max_news: int = 10,
                max_notices: int = 10) -> dict:
        """
        完整分析流程：爬取 → 本地存储 → 分组 LLM 分析 → 合成报告
        """
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        stock_dir = self.storage_dir / symbol / ts
        stock_dir.mkdir(parents=True, exist_ok=True)

        # Phase 1: 爬取
        logger.info(f"[{symbol}] 开始爬取... max_pages={max_pages}, days={days}, max_articles={max_articles}")
        crawl_result = self.crawler.crawl(
            symbol, max_pages=max_pages, max_articles=max_articles,
            days=days, max_news=max_news, max_notices=max_notices
        )

        # Phase 2: 组装原文数据（带 index）
        raw_data = self._build_raw_data(crawl_result)
        raw_file = stock_dir / 'raw.json'
        with open(raw_file, 'w', encoding='utf-8') as f:
            json.dump(raw_data, f, ensure_ascii=False, indent=2)
        logger.info(f"[{symbol}] 原始数据已存储: {raw_file}")

        # Phase 3: 分组分析
        logger.info(f"[{symbol}] 开始分组 LLM 分析...")
        group_results = self._analyze_groups(raw_data, symbol)

        # Phase 4: 合成报告
        logger.info(f"[{symbol}] 合成最终报告...")
        final_analysis = self._synthesize(group_results, symbol, raw_data)
        analysis_file = stock_dir / 'analysis.json'
        with open(analysis_file, 'w', encoding='utf-8') as f:
            json.dump(final_analysis, f, ensure_ascii=False, indent=2)
        logger.info(f"[{symbol}] 分析结果已存储: {analysis_file}")

        # Phase 5: 生成 Markdown 报告
        report_md = self._build_report_md(symbol, raw_data, final_analysis, crawl_result)
        report_file = stock_dir / 'report.md'
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report_md)
        logger.info(f"[{symbol}] 报告已生成: {report_file}")

        return {
            'symbol': symbol,
            'crawl_result': crawl_result,
            'raw_data': raw_data,
            'analysis': final_analysis,
            'report_md': report_md,
            'raw_file': str(raw_file),
            'report_file': str(report_file),
            'group_count': len(group_results),
            'group_results': group_results,
        }

    def _build_raw_data(self, result: CrawlResult) -> dict:
        """给每条数据分配全局 index"""
        idx = 1
        discussions = []
        for disc in sorted(result.discussions, key=lambda x: x.time, reverse=True):
            discussions.append({
                'index': idx,
                'type': 'discussion',
                'author': disc.author,
                'content': disc.content,
                'time': disc.time,
                'link': disc.link,
                'is_column': disc.is_column,
                '_time': disc.time,  # 带发布时间方便引用
            })
            idx += 1

        columns = []
        for art in sorted(result.articles, key=lambda x: x.time, reverse=True):
            columns.append({
                'index': idx,
                'type': 'column',
                'author': art.author,
                'title': art.title,
                'content': art.content,
                'time': art.time,
                'link': art.link,
            })
            idx += 1

        news_list = []
        for n in sorted(result.news, key=lambda x: x.time, reverse=True):
            news_list.append({
                'index': idx,
                'type': 'news',
                'title': n.title,
                'content': n.content or n.title,
                'time': n.time,
                'link': n.link,
            })
            idx += 1

        notices = []
        for nt in sorted(result.notices, key=lambda x: x.time, reverse=True):
            notices.append({
                'index': idx,
                'type': 'notice',
                'title': nt.title,
                'content': nt.content,
                'time': nt.time,
                'link': nt.link,
            })
            idx += 1

        return {
            'discussions': discussions,
            'columns': columns,
            'news': news_list,
            'notices': notices,
            'meta': {
                'total_discussions': len(discussions),
                'total_columns': len(columns),
                'total_news': len(news_list),
                'total_notices': len(notices),
            }
        }

    def _serialize_chunk(self, items: List[dict], max_content_len: int = 500) -> str:
        """将一组数据序列化为 JSON 字符串（截断超长 content）"""
        def truncate(obj, max_len=max_content_len):
            if isinstance(obj, dict):
                return {k: truncate(v, max_len) for k, v in obj.items()}
            if isinstance(obj, str) and len(obj) > max_len:
                return obj[:max_len] + '...[截断]'
            return obj
        truncated = json.loads(json.dumps(items))
        return json.dumps([truncate(item) for item in items], ensure_ascii=False, indent=2)

    def _analyze_groups(self, raw_data: dict, symbol: str) -> List[dict]:
        """分组调用 LLM，分析所有数据"""
        group_results = []
        t0_total = datetime.now()

        # ── 数据流日志 ────────────────────────────────────────────
        meta = raw_data['meta']
        logger.info(f"[{symbol}] ═══════════════════════════════════════════")
        logger.info(f"[{symbol}] 📊 数据规模汇总")
        logger.info(f"[{symbol}]   讨论: {meta['total_discussions']} 条")
        logger.info(f"[{symbol}]   专栏: {meta['total_columns']} 篇")
        logger.info(f"[{symbol}]   资讯: {meta['total_news']} 条")
        logger.info(f"[{symbol}]   公告: {meta['total_notices']} 条")
        logger.info(f"[{symbol}] ═══════════════════════════════════════════")

        # 估算总 token 量
        est_chars = (
            meta['total_discussions'] * 500 +
            meta['total_columns'] * 2000 +
            meta['total_news'] * 1000 +
            meta['total_notices'] * 2000
        )
        est_tokens = est_chars // 4
        logger.info(f"[{symbol}] 🔢 估算总字符: ~{est_chars:,} chars | ~{est_tokens:,} tokens")
        logger.info(f"[{symbol}] 📦 分组策略")
        logger.info(f"[{symbol}]   讨论: {DISC_CHUNK_SIZE}条/组 → {len(self._chunk_list(raw_data['discussions'], DISC_CHUNK_SIZE))} 组")
        logger.info(f"[{symbol}]   专栏: {COL_CHUNK_SIZE}篇/组 → {len(self._chunk_list(raw_data['columns'], COL_CHUNK_SIZE))} 组")
        logger.info(f"[{symbol}]   资讯: 全量 1 组")
        logger.info(f"[{symbol}]   公告: 全量 1 组")
        logger.info(f"[{symbol}] ═══════════════════════════════════════════")

        # 1. 讨论分组
        disc_groups = self._chunk_list(raw_data['discussions'], DISC_CHUNK_SIZE)
        logger.info(f"[{symbol}] ┌─ 讨论: {len(disc_groups)} 组")
        for i, group in enumerate(disc_groups):
            t_group = datetime.now()
            data_block = self._serialize_chunk(group, max_content_len=600)
            chars_in = len(data_block)
            tokens_est = chars_in // 4
            group_label = f"讨论组{i+1}/{len(disc_groups)}"
            logger.info(f"[{symbol}] │ ├─ {group_label} [{len(group)}条] input≈{tokens_est:,}tokens")
            result = self._call_llm_group(
                data_block, group, '讨论', i + 1, len(disc_groups),
                len(raw_data['discussions'])
            )
            t_elapsed = (datetime.now() - t_group).total_seconds()
            if 'error' in result:
                logger.error(f"[{symbol}] │ └─ {group_label} ❌ ERROR: {result['error']}")
            else:
                hvi = len(result.get('high_value_items', []))
                themes = [t['name'] for t in result.get('group_topics', [])]
                logger.info(f"[{symbol}] │ └─ {group_label} ✅ ({t_elapsed:.1f}s) hvi={hvi} themes={themes}")
            group_results.append({'label': group_label, 'type': 'discussions', 'data': result})

        # 2. 专栏分组
        col_groups = self._chunk_list(raw_data['columns'], COL_CHUNK_SIZE)
        if col_groups:
            logger.info(f"[{symbol}] ┌─ 专栏: {len(col_groups)} 组")
            for i, group in enumerate(col_groups):
                t_group = datetime.now()
                data_block = self._serialize_chunk(group, max_content_len=2000)
                chars_in = len(data_block)
                tokens_est = chars_in // 4
                group_label = f"专栏组{i+1}/{len(col_groups)}"
                logger.info(f"[{symbol}] │ ├─ {group_label} [{len(group)}篇] input≈{tokens_est:,}tokens")
                result = self._call_llm_group(
                    data_block, group, '专栏文章', i + 1, len(col_groups),
                    len(raw_data['columns'])
                )
                t_elapsed = (datetime.now() - t_group).total_seconds()
                if 'error' in result:
                    logger.error(f"[{symbol}] │ └─ {group_label} ❌ ERROR: {result['error']}")
                else:
                    hvi = len(result.get('high_value_items', []))
                    themes = result.get('group_topics', [])
                    logger.info(f"[{symbol}] │ └─ {group_label} ✅ ({t_elapsed:.1f}s) hvi={hvi} themes={themes}")
                group_results.append({'label': group_label, 'type': 'columns', 'data': result})
        else:
            logger.info(f"[{symbol}] ┌─ 专栏: 0 篇（跳过）")

        # 3. 新闻
        if raw_data['news']:
            t_group = datetime.now()
            group = raw_data['news']
            data_block = self._serialize_chunk(group, max_content_len=1000)
            chars_in = len(data_block)
            tokens_est = chars_in // 4
            logger.info(f"[{symbol}] ┌─ 资讯: 1组 [{len(group)}条] input≈{tokens_est:,}tokens")
            result = self._call_llm_group(data_block, group, '资讯', 1, 1, len(raw_data['news']))
            t_elapsed = (datetime.now() - t_group).total_seconds()
            if 'error' in result:
                logger.error(f"[{symbol}] │ └─ 资讯组1/1 ❌ ERROR: {result['error']}")
            else:
                hvi = len(result.get('high_value_items', []))
                themes = [t['name'] for t in result.get('group_topics', [])]
                logger.info(f"[{symbol}] │ └─ 资讯组1/1 ✅ ({t_elapsed:.1f}s) hvi={hvi} themes={themes}")
            group_results.append({'label': '资讯组1/1', 'type': 'news', 'data': result})
        else:
            logger.info(f"[{symbol}] ┌─ 资讯: 0条（跳过）")

        # 4. 公告
        if raw_data['notices']:
            t_group = datetime.now()
            group = raw_data['notices']
            data_block = self._serialize_chunk(group, max_content_len=2000)
            chars_in = len(data_block)
            tokens_est = chars_in // 4
            logger.info(f"[{symbol}] ┌─ 公告: 1组 [{len(group)}条] input≈{tokens_est:,}tokens")
            result = self._call_llm_group(data_block, group, '公告', 1, 1, len(raw_data['notices']))
            t_elapsed = (datetime.now() - t_group).total_seconds()
            if 'error' in result:
                logger.error(f"[{symbol}] │ └─ 公告组1/1 ❌ ERROR: {result['error']}")
            else:
                hvi = len(result.get('high_value_items', []))
                themes = [t['name'] for t in result.get('group_topics', [])]
                logger.info(f"[{symbol}] │ └─ 公告组1/1 ✅ ({t_elapsed:.1f}s) hvi={hvi} themes={themes}")
            group_results.append({'label': '公告组1/1', 'type': 'notices', 'data': result})
        else:
            logger.info(f"[{symbol}] ┌─ 公告: 0条（跳过）")

        t_total = (datetime.now() - t0_total).total_seconds()
        success_groups = sum(1 for g in group_results if 'error' not in g.get('data', {}))
        logger.info(f"[{symbol}] ═══════════════════════════════════════════")
        logger.info(f"[{symbol}] ✅ 分组分析完成: {success_groups}/{len(group_results)} 组成功 ({t_total:.0f}s)")

        return group_results

    def _chunk_list(self, items: List[dict], chunk_size: int) -> List[List[dict]]:
        """将列表分成多个 chunk"""
        chunks = []
        for i in range(0, len(items), chunk_size):
            chunks.append(items[i:i + chunk_size])
        return chunks

    def _call_llm_group(self, data_block: str, items: List[dict],
                        data_type: str, group_idx: int, total_groups: int,
                        total_items: int) -> dict:
        """单次调用 LLM 分析一组数据"""
        start_idx = items[0]['index']
        end_idx = items[-1]['index']

        prompt = _ANALYZE_CHUNK_PROMPT.format(
            data_type=data_type,
            total_items=total_items,
            start_idx=start_idx,
            end_idx=end_idx,
            data_block=data_block,
        )

        try:
            messages = [{"role": "user", "content": prompt}]
            logger.debug(f"[LLM] prompt_len={len(prompt):,}chars, max_tokens={LLM_MAX_TOKENS}")
            result_text = self.llm.chat(messages, max_tokens=LLM_MAX_TOKENS)
            result_text = result_text.strip()
            if result_text.startswith('```'):
                lines = result_text.split('\n')
                result_text = '\n'.join(lines[1:] if lines[0].startswith('```') else lines)
                result_text = result_text.rstrip('```')
            resp_len = len(result_text)
            logger.debug(f"[LLM] response_len={resp_len:,}chars")
            parsed = json.loads(result_text)
            return parsed
        except json.JSONDecodeError as e:
            logger.warning(f"[LLM] ❌ JSON解析失败（第{group_idx}组）: {e}")
            logger.warning(f"[LLM] raw_response[:200]: {result_text[:200]}")
            return {'error': f'JSON解析失败: {e}', 'raw': result_text[:500]}

    def _synthesize(self, group_results: List[dict], symbol: str,
                    raw_data: dict) -> dict:
        """最终合成：将各组分析合成为完整报告"""
        # 收集各组 summary
        summaries = []
        details = []
        for gr in group_results:
            d = gr['data']
            if 'error' in d:
                continue
            summaries.append(f"【{gr['label']}】{d.get('summary', '')}")
            details.append(f"=== {gr['label']} ===\n{json.dumps(d, ensure_ascii=False, indent=2)}")

        prompt = _ANALYZE_SYNTHESIZE_PROMPT.format(
            symbol=symbol,
            num_groups=len(group_results),
            group_summaries='\n'.join(summaries),
            group_details='\n\n'.join(details),
        )

        try:
            prompt_len = len(prompt)
            messages = [{"role": "user", "content": prompt}]
            logger.info(f"[{symbol}] 🔄 合成阶段: 合并 {len(group_results)} 组, prompt={prompt_len:,}chars")
            result_text = self.llm.chat(messages, max_tokens=LLM_MAX_TOKENS)
            result_text = result_text.strip()
            if result_text.startswith('```'):
                lines = result_text.split('\n')
                result_text = '\n'.join(lines[1:] if lines[0].startswith('```') else lines)
                result_text = result_text.rstrip('```')
            logger.info(f"[{symbol}] 🔄 合成响应: {len(result_text):,}chars")
            return json.loads(result_text)
        except json.JSONDecodeError as e:
            logger.warning(f"[{symbol}] ❌ 合成失败: {e}")
            return {
                'error': f'合成失败: {e}',
                'raw': result_text[:500],
                'group_summaries': summaries,
            }

    def _build_report_md(self, symbol: str, raw_data: dict,
                          analysis: dict, crawl_result) -> str:
        """生成 Markdown 报告"""
        meta = raw_data['meta']
        now = datetime.now().strftime('%Y-%m-%d %H:%M')

        lines = [
            f"# {crawl_result.name or symbol}（{symbol}）深度舆情分析",
            f"",
            f"**分析时间**: {now}",
            f"**数据规模**: {meta['total_discussions']} 条讨论 / "
            f"{meta['total_columns']} 篇专栏 / "
            f"{meta['total_news']} 条新闻 / "
            f"{meta['total_notices']} 条公告",
            f"",
            "---",
            "",
        ]

        if 'summary' in analysis and 'error' not in analysis:
            lines += ["## 一、核心舆情摘要", "", analysis['summary'], "", "---", ""]

        if analysis.get('bull_points'):
            lines += ["## 二、多方观点（看多理由）", ""]
            for pt in analysis['bull_points']:
                lines.append(f"- {pt}")
            lines += ["", "---", ""]

        if analysis.get('bear_points'):
            lines += ["## 三、空方观点（风险因素）", ""]
            for pt in analysis['bear_points']:
                lines.append(f"- {pt}")
            lines += ["", "---", ""]

        if analysis.get('topics'):
            lines += ["## 四、主题分布", "", "| 话题 | 提及次数 | 情绪 | 核心观点 |",
                     "|------|---------|------|---------|"]
            for t in analysis['topics']:
                key_views = '；'.join(t.get('key_views', [])[:2])
                lines.append(f"| {t['name']} | {t.get('mentions', '-')} | {t.get('sentiment', '-')} | {key_views} |")
            lines += ["", "---", ""]

        if analysis.get('high_value_columns'):
            lines += ["## 五、高价值专栏文章", ""]
            for col in analysis['high_value_columns']:
                idx = str(col.get('index', ''))
                link = ''
                for c in raw_data.get('columns', []):
                    if str(c['index']) == idx:
                        link = c.get('link', '')
                        break
                link_str = f" [原文]({link})" if link else ""
                lines.append(f"- **[@index={idx}]** {col.get('author', '')}：{col.get('title', '')}{link_str}")
                if col.get('key_points'):
                    lines.append(f"  - 要点：{col['key_points']}")
            lines += ["", "---", ""]

        if analysis.get('high_value_discussions'):
            lines += ["## 六、高价值讨论", ""]
            for disc in analysis['high_value_discussions']:
                idx = str(disc.get('index', ''))
                link = ''
                for d in raw_data.get('discussions', []):
                    if str(d['index']) == idx:
                        link = d.get('link', '')
                        break
                link_str = f" [原文]({link})" if link else ""
                sentiment = disc.get('sentiment', '中性')
                lines.append(f"- **[@index={idx}]** [{sentiment}] {disc.get('author', '')}：{disc.get('content', '')}{link_str}")
            lines += ["", "---", ""]

        if analysis.get('key_notices'):
            lines += ["## 七、关键公告", ""]
            for notice in analysis['key_notices']:
                idx = str(notice.get('index', ''))
                link = ''
                for n in raw_data.get('notices', []):
                    if str(n['index']) == idx:
                        link = n.get('link', '')
                        break
                link_str = f" [PDF]({link})" if link else ""
                lines.append(f"- **[@index={idx}]** [{notice.get('time', '')}] {notice.get('title', '')}{link_str}")
                if notice.get('key_info'):
                    lines.append(f"  - {notice['key_info']}")
            lines += ["", "---", ""]

        if analysis.get('actionable_insights'):
            lines += ["## 八、可执行的投资洞见", ""]
            for ins in analysis['actionable_insights']:
                lines.append(f"- {ins}")
            lines += ["", "---", ""]

        if analysis.get('concerns'):
            lines += ["## 九、需进一步确认的风险", ""]
            for c in analysis['concerns']:
                if isinstance(c, dict):
                    concern_text = c.get('concern', str(c))
                    reason_text = c.get('reason', '')
                    if reason_text:
                        lines.append(f"- {concern_text}")
                        lines.append(f"  → 原因：{reason_text}")
                    else:
                        lines.append(f"- {concern_text}")
                else:
                    lines.append(f"- {c}")
            lines += ["", "---", ""]

        lines += ["## 附录：原文索引", "", "点击 index 可在本地 raw.json 中找到对应原文", ""]
        for c in raw_data.get('columns', []):
            if c.get('link'):
                lines.append(f"- [@index={c['index']}] 专栏：{c.get('title','')[:60]} — {c['link']}")
        for d in raw_data.get('discussions', []):
            if d.get('link') and len(d['content']) > 30:
                lines.append(f"- [@index={d['index']}] 讨论：{d['content'][:40]}... — {d['link']}")

        lines += ["", f"_报告生成时间: {now}_"]
        return '\n'.join(lines)