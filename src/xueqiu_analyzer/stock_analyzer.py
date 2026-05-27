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

# 估算：讨论 50 条 × 500 字 ≈ 25k chars ≈ 8-12k tokens
# 专栏 5 篇 × 2000 字 ≈ 10k chars ≈ 4-5k tokens
DISC_CHUNK_SIZE = 50
COL_CHUNK_SIZE = 5
NEWS_CHUNK_SIZE = 10
NOTICE_CHUNK_SIZE = 10

# 每次 LLM 调用 max_tokens
LLM_MAX_TOKENS = 16000

_ANALYZE_CHUNK_PROMPT = """你是一位专业、严谨的价值投资研究助手。

请分析以下雪球舆情数据，输出结构化 JSON。每条原文有 index 字段（从1开始），请在输出中引用有价值的条目。

【数据来源类型】：{data_type}
【本组数据范围】：共 {total_items} 条中的第 {start_idx}-{end_idx} 条

【输出格式】（严格输出 JSON，不要任何其他内容）：
{{
  "summary": "本组数据核心观点（30字以内）",
  "high_value_items": [
    {{
      "index": N,
      "author": "作者",
      "content": "内容摘要（80字以内）",
      "sentiment": "正面/中性/负面",
      "value_level": "高/中/低",
      "reason": "为什么这条有价值（10字以内）"
    }}
  ],
  "key_themes": ["主题词1", "主题词2"],
  "sentiment": "整体情绪：正面/中性/负面/分化",
  "bull_points": ["看多点（从原文提炼）"],
  "bear_points": ["看空点（从原文提炼）"],
  "notable_mentions": ["值得注意的具体事实或数据"]
}}

【index 引用规则】
- index 是在下方【原文数据】中分配的序号
- high_value_items 中必须包含真正有价值的条目 index
- 没用到的 index 不要写

【原文数据】
{data_block}

请严格输出 JSON，不要输出任何其他内容。"""


_ANALYZE_SYNTHESIZE_PROMPT = """你是一位专业、严谨的价值投资研究助手。

以下是同一只股票的多组舆情分析结果，请将其合成为一份完整的结构化投资报告。

【股票】：{symbol}
【分析组数】：{num_groups} 组

【各组摘要】
{group_summaries}

【各组详细内容】
{group_details}

【输出格式】（严格输出 JSON，不要任何其他内容）：
{{
  "summary": "股票舆情核心摘要（50字以内）",
  "bull_points": ["看多点1", "看多点2", "看多点3"],
  "bear_points": ["风险点1", "风险点2"],
  "topics": [
    {{
      "name": "话题名",
      "mentions": 提及次数估算,
      "sentiment": "正面/中性/负面",
      "key_views": ["核心观点1", "核心观点2"]
    }}
  ],
  "high_value_columns": [
    {{
      "index": "原文index",
      "author": "作者",
      "title": "标题",
      "key_points": "核心要点（100字以内）"
    }}
  ],
  "high_value_discussions": [
    {{
      "index": "原文index",
      "author": "作者",
      "content": "内容摘要（80字以内）",
      "sentiment": "正面/中性/负面"
    }}
  ],
  "key_notices": [
    {{
      "index": "原文index",
      "title": "公告标题",
      "time": "日期",
      "key_info": "关键信息（50字以内）"
    }}
  ],
  "actionable_insights": ["可执行洞见1", "可执行洞见2"],
  "concerns": ["需进一步确认的风险1"]
}}

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
                max_articles: int = 10) -> dict:
        """
        完整分析流程：爬取 → 本地存储 → 分组 LLM 分析 → 合成报告
        """
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        stock_dir = self.storage_dir / symbol / ts
        stock_dir.mkdir(parents=True, exist_ok=True)

        # Phase 1: 爬取
        logger.info(f"[{symbol}] 开始爬取... max_pages={max_pages}, days={days}, max_articles={max_articles}")
        crawl_result = self.crawler.crawl(
            symbol, max_pages=max_pages, max_articles=max_articles, days=days
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

        # 1. 讨论分组
        disc_groups = self._chunk_list(raw_data['discussions'], DISC_CHUNK_SIZE)
        logger.info(f"[{symbol}] 讨论分 {len(disc_groups)} 组，每组 ~{DISC_CHUNK_SIZE} 条")
        for i, group in enumerate(disc_groups):
            data_block = self._serialize_chunk(group, max_content_len=600)
            group_label = f"讨论组{i+1}/{len(disc_groups)}"
            result = self._call_llm_group(
                data_block, group, '讨论', i + 1, len(disc_groups),
                len(raw_data['discussions'])
            )
            group_results.append({'label': group_label, 'type': 'discussions', 'data': result})
            logger.info(f"[{symbol}] {group_label} 完成")

        # 2. 专栏分组
        col_groups = self._chunk_list(raw_data['columns'], COL_CHUNK_SIZE)
        if col_groups:
            logger.info(f"[{symbol}] 专栏分 {len(col_groups)} 组，每组 ~{COL_CHUNK_SIZE} 篇")
            for i, group in enumerate(col_groups):
                data_block = self._serialize_chunk(group, max_content_len=2000)
                group_label = f"专栏组{i+1}/{len(col_groups)}"
                result = self._call_llm_group(
                    data_block, group, '专栏文章', i + 1, len(col_groups),
                    len(raw_data['columns'])
                )
                group_results.append({'label': group_label, 'type': 'columns', 'data': result})
                logger.info(f"[{symbol}] {group_label} 完成")

        # 3. 新闻（全部一组，API 只返回标题，内容少）
        if raw_data['news']:
            group = raw_data['news']
            data_block = self._serialize_chunk(group, max_content_len=300)
            result = self._call_llm_group(
                data_block, group, '资讯', 1, 1, len(raw_data['news'])
            )
            group_results.append({'label': '资讯组1/1', 'type': 'news', 'data': result})
            logger.info(f"[{symbol}] 资讯组完成")

        # 4. 公告（全部一组）
        if raw_data['notices']:
            group = raw_data['notices']
            data_block = self._serialize_chunk(group, max_content_len=500)
            result = self._call_llm_group(
                data_block, group, '公告', 1, 1, len(raw_data['notices'])
            )
            group_results.append({'label': '公告组1/1', 'type': 'notices', 'data': result})
            logger.info(f"[{symbol}] 公告组完成")

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
            result_text = self.llm.chat(messages, max_tokens=LLM_MAX_TOKENS)
            result_text = result_text.strip()
            if result_text.startswith('```'):
                lines = result_text.split('\n')
                result_text = '\n'.join(lines[1:] if lines[0].startswith('```') else lines)
                result_text = result_text.rstrip('```')
            return json.loads(result_text)
        except json.JSONDecodeError as e:
            logger.warning(f"LLM 返回非 JSON（第{group_idx}组）: {e}")
            return {'error': str(e), 'raw': result_text[:500]}

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
            messages = [{"role": "user", "content": prompt}]
            result_text = self.llm.chat(messages, max_tokens=LLM_MAX_TOKENS)
            result_text = result_text.strip()
            if result_text.startswith('```'):
                lines = result_text.split('\n')
                result_text = '\n'.join(lines[1:] if lines[0].startswith('```') else lines)
                result_text = result_text.rstrip('```')
            return json.loads(result_text)
        except json.JSONDecodeError as e:
            logger.warning(f"[{symbol}] 合成 LLM 返回非 JSON: {e}")
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