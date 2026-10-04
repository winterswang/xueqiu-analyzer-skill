"""Tests for waf — 风控页判定的唯一实现。

其中几条是**回归测试**：它们固化的正是重构前各仓库判定不一致的地方，
见 waf.py 模块文档。
"""

import re

import pytest

from xueqiu_analyzer import waf


# ── is_error_page：标题 ─────────────────────────────────────

@pytest.mark.parametrize("title", ["405", "403", "滑动验证页面"])
def test_error_title_exact_match(title):
    assert waf.is_error_page(title=title) is True


@pytest.mark.parametrize("title", [" 405 ", "滑 动 验 证 页 面"])
def test_error_title_is_stripped_but_not_substring(title):
    # " 405 " strip 后命中；"滑 动 验 证 页 面" 不是精确匹配 → 不命中
    assert waf.is_error_page(title=title) is (title.strip() in waf.TITLE_EXACT)


def test_empty_title_is_error_page():
    # 抓不到标题通常意味着页面没正常渲染
    assert waf.is_error_page(title="") is True
    assert waf.is_error_page(title="   ") is True


def test_normal_article_is_not_error_page():
    assert waf.is_error_page(title="贵州茅台发布三季报", content="公司前三季度营收…") is False


def test_content_only_calls_must_not_use_is_error_page():
    """回归：is_error_page 的「空标题算错误页」规则只在显式传 title 时生效。

    只查正文的调用若图省事写 is_error_page(content=...)，title 默认空串
    会让它恒为 True，把所有正常页面判成风控页。正文-only 用 contains_waf_text。
    """
    normal = "贵州茅台发布三季报，前三季度营收增长 11%。" * 30
    assert waf.is_error_page(title="", content=normal) is True   # 显式空标题 → 错误页
    assert waf.contains_waf_text(normal) is False                # 只看正文 → 正常


# ── is_error_page：正文 ─────────────────────────────────────

@pytest.mark.parametrize("pattern", waf.CONTENT_PATTERNS)
def test_every_content_pattern_is_detected(pattern):
    assert waf.is_error_page(title="正常标题", content="前缀 " + pattern + " 后缀") is True


def test_content_match_is_case_insensitive():
    """回归：crawler_nodriver 的旧实现大小写敏感，opencli_extractor 的先 .lower()。

    统一为大小写不敏感 —— 否则 'Request has been blocked' 会被重试逻辑抓到、
    却写进磁盘。
    """
    assert waf.is_error_page(title="正常", content="Request Has Been Blocked") is True


def test_405_in_body_is_not_an_error_page():
    """回归：opencli_extractor 旧实现把 '405' 当正文子串匹配，
    任何开头 500 字里出现 405 的正常文章都被误判并重试。
    统一后 405 只做标题精确匹配。
    """
    body = "贵州茅台 405 亿元营收，同比增长 11%。" + "正文" * 300
    assert waf.is_error_page(title="贵州茅台三季报", content=body) is False


def test_specific_405_forms_detected_but_bare_digits_are_not():
    """回归：裸「405」不能做正文子串匹配 —— 「营收 405 亿元」这类正常文章会误判。

    但具体的 405 错误页形态（来自 xueqiu-crawler PR #54 对同一 bug 的收紧）
    必须仍然认得出，否则「标题正常、正文写着 405 Forbidden」的页面会漏掉。
    """
    assert waf.contains_waf_text("405 Forbidden") is True
    assert waf.contains_waf_text("HTTP 405") is True
    assert waf.contains_waf_text("405 Not Allowed") is True
    assert waf.contains_waf_text("贵州茅台 405 亿元营收，同比增长 11%") is False


def test_xueqiu_human_verification_page_detected():
    """2026-10-04 实测：check.xueqiu.com/captcha 的文案未命中旧模式。"""
    content = "访问触发保护，请完成人机验证 检测到当前网络环境的访问频率异常"
    assert waf.contains_waf_text(content) is True
    assert waf.is_waf_blocked(title="访问提示 - 雪球", content=content) is True


def test_only_head_is_scanned():
    body = "正" * (waf.CONTENT_HEAD_CHARS + 50) + "滑动验证"
    assert waf.is_error_page(title="正常标题", content=body) is False


# ── is_waf_blocked ──────────────────────────────────────────

def test_page_marker_only_counts_for_waf_blocked():
    """回归：旧 crawler_nodriver 里 _detect_waf 查 aliyun_waf 标记，
    同文件的 _is_content_error 不查 —— 同一页两个函数结论不同。
    现在两者的关系是显式的：is_waf_blocked ⊃ is_error_page。
    """
    html = "<html><script>window.aliyun_waf=1</script>正常正文</html>"
    assert waf.is_waf_blocked(title="正常标题", content=html) is True
    assert waf.is_error_page(title="正常标题", content=html) is False


def test_waf_blocked_covers_error_page():
    assert waf.is_waf_blocked(title="405") is True
    assert waf.is_waf_blocked(title="正常", content="请按住滑块") is True


def test_has_waf_marker_is_page_wide_and_case_insensitive():
    """页面标记查的是整页 HTML（不只是头部），且大小写不敏感。"""
    deep = "x" * 5000 + "ALIYUN_WAF"
    assert waf.has_waf_marker(deep) is True
    assert waf.has_waf_marker("这里没有标记") is False
    # 头部扫描（is_error_page）看不到 5000 字之后的标记，页面标记检查能看到
    assert waf.contains_waf_text(deep) is False


# ── looks_like_waf_content ──────────────────────────────────

def test_short_content_is_never_waf():
    """太短 = 没取到内容，不是风控。沿用 opencli_extractor 的原行为。"""
    assert waf.looks_like_waf_content("滑动验证") is False
    assert waf.looks_like_waf_content("") is False


def test_long_content_with_pattern_is_waf():
    assert waf.looks_like_waf_content("滑动验证" + "填充" * 100) is True


# ── needs_login ─────────────────────────────────────────────

def test_waf_page_is_not_reported_as_needs_login():
    """回归：analyzer/crawler.py 的 _check_login_status 用风控关键词判断登录态，
    遇到风控页会返回「未登录」→ 触发重新登录而不是退避。
    风控与登录态是两个问题，这里断言它们不互相误伤。
    """
    waf_page = "请按住滑块，拖动完成验证"
    assert waf.is_error_page(title="", content=waf_page) is True
    assert waf.needs_login(waf_page) is False


def test_login_wall_detected():
    assert waf.needs_login("登录后查看该用户的全部动态") is True


# ── classify_failure ────────────────────────────────────────

@pytest.mark.parametrize("err,expected", [
    ("opencli: 滑动验证", "风控验证页"),
    ("SECURITY_BLOCK", "风控验证页"),
    ("访问频繁，请稍后再试", "风控验证页"),
    ("AUTH_REQUIRED: 未登录", "登录态失效"),
    ("EMPTY_RESULT", "无数据"),
    ("HTTP 500 from upstream", "接口异常"),
    ("something else", "其他"),
    ("", "其他"),
])
def test_classify_failure(err, expected):
    assert waf.classify_failure(err) == expected


# ── block_guard_js ──────────────────────────────────────────

def test_block_guard_js_contains_every_pattern():
    js = waf.block_guard_js()
    for p in waf.CONTENT_PATTERNS:
        assert p in js.split("|")


def test_block_guard_patterns_are_regex_safe():
    """这些串会被直接拼进 JS 正则字面量，必须不含元字符 —— 否则会改变语义。

    注意判断标准是「正则里是否特殊」，不是 re.escape 是否原样返回：
    re.escape 连空格都转义，而空格在正则里是普通字符。
    """
    metachars = set(r".*+?^${}()|[]\/")
    for p in waf.CONTENT_PATTERNS:
        assert not (set(p) & metachars), f"{p!r} 含正则元字符，需要转义"


def test_block_guard_raises_on_metachar_pattern(monkeypatch):
    """加错模式要当场炸，而不是悄悄把正常页面全判成风控。"""
    monkeypatch.setattr(waf, "CONTENT_PATTERNS", ("正常", "a.*b"))
    with pytest.raises(ValueError, match="正则元字符"):
        waf.block_guard_js()
