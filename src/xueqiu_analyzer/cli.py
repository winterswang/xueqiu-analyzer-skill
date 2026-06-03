"""
xueqiu-analyzer V3 — 统一 CLI 入口
"""

import json
import sys
import click
import logging
from pathlib import Path

# 确保项目根目录在 path 中
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / 'src'))

from xueqiu_analyzer.config import get_config, get_data_dir
from xueqiu_analyzer.models import CrawlResult
from xueqiu_analyzer.evaluator import Evaluator
from xueqiu_analyzer.analyzer import Analyzer
from xueqiu_analyzer.orchestrator import Orchestrator


def _setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )


@click.group()
@click.option('--verbose', '-v', is_flag=True, help='调试模式')
def cli(verbose):
    """雪球股票分析工具 V3"""
    _setup_logging(verbose)


@cli.command()
@click.argument('symbol')
@click.option('--max-rounds', default=10, help='最大爬取轮次')
@click.option('--data', default=None, help='已有数据文件路径（跳过爬取）')
@click.option('--template', default='analysis', help='分析模板名')
def analyze(symbol, max_rounds, data, template):
    """完整分析流程：爬取→评估→分析"""
    config = get_config()

    # 如果没有已有数据，需要加载爬虫
    crawl_fn = None
    if not data:
        try:
            from xueqiu_analyzer.crawler import XueqiuCrawler
            crawler = XueqiuCrawler(config.get('crawler', {}))
            crawl_fn = crawler.crawl
        except ImportError:
            click.echo("❌ 未安装爬虫模块，请提供 --data 参数", err=True)
            sys.exit(1)

    orchestrator = Orchestrator(config)
    result = orchestrator.run(
        symbol=symbol,
        max_rounds=max_rounds,
        data_path=data,
        template=template,
        crawl_fn=crawl_fn,
    )

    # 输出摘要
    click.echo(f"\n{'='*60}")
    click.echo(f"分析完成: {symbol}")
    click.echo(f"{'='*60}")
    if result.evaluation:
        click.echo(f"评分: {result.evaluation.effective_score}/"
                   f"{200 + result.evaluation.financial_bonus}")
        click.echo(f"充分性: {result.evaluation.sufficiency}")
    click.echo(f"模型: {result.model}")
    click.echo("报告: 见 data/ 目录")


@cli.command()
@click.argument('symbol')
@click.option('--output', '-o', default=None, help='输出文件路径')
@click.option('--max-pages', default=5, help='最大翻页数')
@click.option('--max-articles', default=10, help='最大文章数')
@click.option('--days', default=0, help='只看最近 N 天（0=不限）')
@click.option('--max-items', default=0, help='最大总内容条数（0=不限）')
@click.option('--max-news', default=10, help='最大新闻正文爬取数（0=只爬标题）')
@click.option('--max-notices', default=10, help='最大公告正文爬取数（0=只爬标题）')
def crawl(symbol, output, max_pages, max_articles, days, max_items, max_news, max_notices):
    """只爬取数据，保存为 JSON"""
    try:
        from xueqiu_analyzer.crawler import XueqiuCrawler
    except ImportError:
        click.echo("❌ 未安装爬虫模块", err=True)
        sys.exit(1)

    config = get_config()
    crawler = XueqiuCrawler(config.get('crawler', {}))

    click.echo(f"开始爬取: {symbol}")
    result = crawler.crawl(symbol, max_pages=max_pages,
                           max_articles=max_articles, days=days,
                           max_items=max_items,
                           max_news=max_news,
                           max_notices=max_notices)

    # 保存
    if output:
        out_path = Path(output)
    else:
        data_dir = get_data_dir()
        import time
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        out_path = data_dir / f'{symbol}_data_{timestamp}.json'

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)

    click.echo("✅ 爬取完成:")
    click.echo(f"  讨论: {len(result.discussions)}")
    click.echo(f"  资讯: {len(result.news)}")
    click.echo(f"  公告: {len(result.notices)}")
    click.echo(f"  文章: {len(result.articles)}")
    click.echo(f"  保存: {out_path}")


@cli.command()
@click.option('--data', required=True, help='数据文件路径')
def evaluate(data):
    """评估数据充分性"""
    with open(data, 'r', encoding='utf-8') as f:
        raw = json.load(f)

    crawl_result = CrawlResult.from_dict(raw)
    evaluator = Evaluator()
    result = evaluator.evaluate(crawl_result)

    click.echo(f"\n{'='*40}")
    click.echo(f"评估结果: {crawl_result.symbol}")
    click.echo(f"{'='*40}")
    click.echo(f"总分: {result.effective_score}/"
               f"{200 + result.financial_bonus}")
    click.echo(f"充分性: {result.sufficiency}")
    click.echo(f"需继续爬取: {'是' if result.need_more_crawl else '否'}")
    click.echo()

    for topic, info in result.scores.items():
        if isinstance(info, dict):
            score = info.get('score', 0)
            bar = '█' * (score // 5)
            click.echo(f"  {topic}: {score:2d}分 {bar}")


@cli.command()
@click.option('--data', required=True, help='数据文件路径')
@click.option('--template', default='analysis', help='分析模板名')
def reanalyze(data, template):
    """用已有数据重新分析"""
    with open(data, 'r', encoding='utf-8') as f:
        raw = json.load(f)

    crawl_result = CrawlResult.from_dict(raw)
    evaluator = Evaluator()
    evaluation = evaluator.evaluate(crawl_result)

    analyzer = Analyzer(template=template)
    report = analyzer.analyze(crawl_result, evaluation)

    # 保存
    data_dir = get_data_dir()
    import time
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    report_path = data_dir / f'{crawl_result.symbol}_report_{timestamp}.md'
    report_path.write_text(report, encoding='utf-8')

    click.echo(f"✅ 分析完成: {report_path}")


@cli.command('sentiment')
@click.argument('symbol')
@click.option('--output-dir', '-o', default=None, help='输出目录（默认 ~/.xueqiu_stocks/{SYMBOL}/{timestamp}/）')
@click.option('--max-pages', default=10, help='最大分页数（硬上限兜底）')
@click.option('--days', default=0, help='时间窗口（天，0=不限）')
@click.option('--max-items', default=0, help='最大总内容条数（0=不限）')
@click.option('--max-articles', default=10, help='最大专栏文章详情数')
@click.option('--max-news', default=10, help='最大新闻正文爬取数（0=只爬标题）')
@click.option('--max-notices', default=10, help='最大公告正文爬取数（0=只爬标题）')
@click.option('--auto', is_flag=True, help='质量驱动模式：迭代爬取直到评分达标')
@click.option('--quality-score', default=150, help='auto 模式评分阈值')
def sentiment(symbol, output_dir, max_pages, days, max_items,
              max_articles, max_news, max_notices, auto, quality_score):
    """舆情扫描：爬取雪球社区数据，输出多空观点+主题分布+投资洞见。

    生成的是舆情快照（非投资建议），适合快速了解市场情绪。
    如需完整投资分析报告（含估值/仓位/止损），请使用 'analyze' 命令。

    数据规模参考：
    - max_pages=10, days=0  →  ~180 条讨论 + 20 条新闻 + 20 条公告
    - days=30               →  自动判断页数，通常 2-4 页
    """
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S',
    )

    from pathlib import Path
    from xueqiu_analyzer.config import get_config
    from xueqiu_analyzer.stock_analyzer import DeepAnalyzer as StockAnalyzer

    config = get_config()

    # storage_dir
    if output_dir:
        storage_dir = Path(output_dir)
    else:
        storage_dir = Path('~/.xueqiu_stocks').expanduser()

    click.echo(f"📊 开始舆情扫描: {symbol}")
    mode_info = f"auto={auto}" if auto else f"max_pages={max_pages}"
    click.echo(f"   {mode_info}, days={days}, max_items={max_items}, max_articles={max_articles}")
    click.echo(f"   输出目录: {storage_dir}")
    click.echo()

    analyzer = StockAnalyzer(storage_dir=storage_dir)

    import time
    t0 = time.time()
    result = analyzer.analyze(
        symbol=symbol.upper(),
        max_pages=max_pages,
        days=days,
        max_items=max_items,
        max_articles=max_articles,
        max_news=max_news,
        max_notices=max_notices,
        auto=auto,
        quality_score=quality_score,
    )
    t1 = time.time()

    click.echo()
    click.echo(f"✅ 分析完成 ({t1-t0:.0f}s)")
    click.echo(f"   原始数据: {result['raw_file']}")
    click.echo(f"   分析结果: {result['report_file']}")

    analysis = result['analysis']
    if 'error' not in analysis:
        click.echo()
        click.echo("📋 报告摘要:")
        click.echo(f"   摘要: {analysis.get('summary', '')}")
        click.echo(f"   看多: {len(analysis.get('bull_points', []))} 条")
        click.echo(f"   看空: {len(analysis.get('bear_points', []))} 条")
        click.echo(f"   主题: {len(analysis.get('topics', []))} 个")
        click.echo(f"   洞见: {len(analysis.get('actionable_insights', []))} 条")
    else:
        click.echo(f"   ⚠️ LLM 分析出错: {analysis['error']}")


@cli.command()
@click.option('--import-file', help='导入 cookies JSON 文件')
@click.option('--check', is_flag=True, help='检查 cookies 状态')
def cookies(import_file, check):
    """管理登录状态"""
    if check:
        _check_cookies()
    elif import_file:
        _import_cookies(import_file)
    else:
        click.echo("请指定 --import-file 或 --check")


def _check_cookies():
    """检查 cookies 状态"""
    import time as _time

    project_cookies = _PROJECT_ROOT / 'config' / 'cookies' / 'xueqiu.json'
    default_cookies = Path.home() / '.xueqiu_crawler' / 'cookies.json'

    for path in [project_cookies, default_cookies]:
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            now = _time.time()
            expired = sum(1 for c in data
                          if c.get('expiry', 0) > 0 and c['expiry'] < now)
            valid = len(data) - expired
            has_token = any(c['name'] == 'xq_a_token' for c in data)
            status = "✅" if has_token and valid > 5 else "❌"
            click.echo(f"{status} {path}: {len(data)} cookies, "
                       f"{valid} 有效, {expired} 过期")
        else:
            click.echo(f"❌ {path}: 不存在")


def _import_cookies(filepath: str):
    """导入 cookies"""
    with open(filepath, 'r') as f:
        cookies = json.load(f)

    # 标准化格式
    normalized = []
    for c in cookies:
        if isinstance(c, dict) and 'name' in c:
            item = {
                'name': c['name'],
                'value': c.get('value', ''),
                'domain': c.get('domain', '.xueqiu.com'),
                'path': c.get('path', '/'),
            }
            for key in ('expiry', 'httpOnly', 'secure', 'sameSite'):
                if key in c:
                    item[key] = c[key]
            if c.get('expirationDate'):
                item['expiry'] = int(c['expirationDate'])
            normalized.append(item)

    # 双写
    project_path = _PROJECT_ROOT / 'config' / 'cookies' / 'xueqiu.json'
    project_path.parent.mkdir(parents=True, exist_ok=True)
    with open(project_path, 'w') as f:
        json.dump(normalized, f, indent=2)

    default_path = Path.home() / '.xueqiu_crawler' / 'cookies.json'
    default_path.parent.mkdir(parents=True, exist_ok=True)
    with open(default_path, 'w') as f:
        json.dump(normalized, f, indent=2)

    click.echo(f"✅ 已导入 {len(normalized)} 个 cookies")


@cli.command()
@click.option("--data", required=True, help="数据文件路径 (JSON)")
@click.option("--threshold", default=10, help="高质量综合分阈值")
def grade(data, threshold):
    """对已爬取数据进行内容质量评分"""
    import json as _json
    from xueqiu_analyzer.models import CrawlResult
    from xueqiu_analyzer.content_grader import ContentGrader

    with open(data, "r", encoding="utf-8") as f:
        raw = _json.load(f)

    crawl_result = CrawlResult.from_dict(raw)
    grader = ContentGrader(threshold=threshold)

    # 将 dataclass 对象转为 dict
    discussions = [
        {"author": d.author, "content": d.content, "time": d.time}
        for d in crawl_result.discussions
    ]
    articles = [
        {"author": a.author, "content": a.content, "title": a.title}
        for a in crawl_result.articles
    ]

    result = grader.grade(discussions=discussions, articles=articles)

    click.echo(f"\n{'='*50}")
    click.echo(f"内容质量评分: {crawl_result.symbol}")
    click.echo(f"{'='*50}")
    click.echo(f"总内容: {result.total_items} 条")
    click.echo(f"高质量 (combined≥{threshold}): "
               f"{len(result.filter_by_threshold(threshold))} 条")

    if result.themes:
        click.echo(f"\n争议主题 ({len(result.themes)}):")
        for t in result.themes[:5]:
            click.echo(f"  📌 {t.name}")
            click.echo(f"     看多: {t.bull_side[:80]}")
            click.echo(f"     看空: {t.bear_side[:80]}")

    if result.consensus_points:
        click.echo(f"\n共识 ({len(result.consensus_points)}):")
        for p in result.consensus_points[:5]:
            click.echo(f"  ✅ {p}")

    if result.info_gaps:
        click.echo(f"\n缺失信息 ({len(result.info_gaps)}):")
        for g in result.info_gaps[:5]:
            click.echo(f"  ❓ {g}")

    # 输出 Top 5 高质量帖子
    high = sorted(
        result.filter_by_threshold(threshold),
        key=lambda x: x.combined, reverse=True
    )[:5]
    if high:
        click.echo(f"\nTop {len(high)} 高质量内容:")
        for h in high:
            click.echo(f"  ⭐ [{h.combined}分] {h.summary[:80]}")


def main():
    cli()

# 向后兼容：deep-analyze → sentiment
cli.add_command(cli.commands['sentiment'], 'deep-analyze')


if __name__ == '__main__':
    main()
