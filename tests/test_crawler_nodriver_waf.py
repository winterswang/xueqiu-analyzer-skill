"""crawler_nodriver._detect_waf 与 waf.PAGE_MARKERS 的接线回归测试。"""

import asyncio

import pytest

from xueqiu_analyzer.crawler_nodriver import XueqiuNodriverCrawler


class FakeTab:
    def __init__(self, title: str, html: str):
        self._title = title
        self._html = html

    async def evaluate(self, script: str):
        if "document.title" in script:
            return self._title
        return self._html


def make_crawler(tab: FakeTab) -> XueqiuNodriverCrawler:
    crawler = object.__new__(XueqiuNodriverCrawler)
    crawler.tab = tab
    return crawler


@pytest.mark.parametrize(
    "title,html,expected",
    [
        ("雪球", '<html data="aliyun_waf"></html>', True),
        ("雪球", "<html><script>var renderData = {};</script></html>", False),
        ("雪球", "<html><div class='_waf_'></div></html>", False),
        ("雪球", "<html><body>正常讨论页</body></html>", False),
        ("滑动验证", "<html></html>", True),
    ],
)
def test_detect_waf_uses_shared_page_markers(title, html, expected):
    crawler = make_crawler(FakeTab(title, html))
    assert asyncio.run(crawler._detect_waf()) is expected
