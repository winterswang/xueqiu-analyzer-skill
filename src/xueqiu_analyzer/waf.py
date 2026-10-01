"""雪球风控页判定的唯一实现。

为什么需要这个模块
------------------
雪球被风控拦下时，返回的是一个「验证页」而不是 HTTP 错误。如果认不出来，
就会被当成「这只股票确实没有数据」—— 数据静默变少，而且没有任何报错。
这类事故已经发生过。

此前这套判定散落在 3 个仓库 8 处，各写各的，关键词集合已经漂移：

- ``crawler_nodriver`` 的 ``_is_content_error`` 大小写敏感，``opencli_extractor``
  的 ``_is_error_page`` 先 ``.lower()`` —— 于是 ``Request has been blocked``
  能被重试逻辑抓到，却写进了磁盘。
- ``opencli_extractor`` 把 ``"405"`` 当成正文子串匹配，任何开头 500 字里
  出现 ``405`` 的正常文章都会被误判为重试。
- ``crawler_nodriver`` 同一个文件里，``_is_waf_blocked`` 查 ``aliyun_waf``
  页面标记，``_is_content_error`` 不查，两个函数能把同一页判成不同结果。

所以模式表收在这里，改一次全生效。

三个问题，别混用
----------------
- :func:`is_error_page` —— 这页是错误页/验证页，还是真正文？（决定丢弃/过滤）
- :func:`is_waf_blocked` —— 浏览器是不是撞上 WAF 了？（决定重试/重启浏览器）
- :func:`classify_failure` —— 把失败原因归类（给失败日志与健康检查）

「登录态」是**另一个问题**，用 :data:`AUTH_REQUIRED_PATTERNS`，不要拿风控
关键词去判断登录态 —— 风控页会被误读成「未登录」，进而触发重新登录而不是退避等待。

JS 侧
-----
opencli 适配器（``xueqiu-crawler/opencli-adapters/*.js``）需要同一套模式，
但跑在 Node 里。那份由 ``xueqiu-crawler/scripts/sync_waf_patterns.py`` 从本模块
生成，并有漂移测试卡住两边不能各走各的。
"""

from __future__ import annotations

# ── 权威模式表 ──────────────────────────────────────────────
# 改这里会同时影响 crawler 的爬取/报表、analyzer 的抓取与失败归类、
# 以及 opencli 适配器的 BLOCK_GUARD（需重跑 sync_waf_patterns.py）。

# 整页标题精确等于这些值 → 错误页。注意「精确匹配」，不做子串。
TITLE_EXACT = frozenset({"405", "403", "滑动验证页面"})

# 正文开头出现任一 → 错误页/验证页。
CONTENT_PATTERNS = (
    "您的访问被阻断",
    "request has been blocked",
    "可能对网站造成安全威胁",
    "potential threats to the server",
    "访问被拦截",
    "滑动验证",
    "请按住滑块",
    "访问验证",
    "安全限制",
    "访问频繁",
    "website-login",
    # 裸「405」**不做**正文子串匹配 —— 「营收 405 亿元」这类正常文章会被误判成
    # 错误页并反复重试（旧 opencli_extractor 的写法）。只认下面这些具体形态，
    # 它们既能抓住「标题正常、正文写着 405 Forbidden」的错误页，又不会撞上数字。
    # （前 3 条来自 xueqiu-crawler PR #54 对同一个 bug 的收紧，合并时并入本表。）
    "405 forbidden",
    "http 405",
    "405 not allowed",
)

# 整页 HTML 里出现即判定（WAF 注入的标记）。
PAGE_MARKERS = ("aliyun_waf",)

# 登录墙。用于判断「未登录」，与风控分开。
AUTH_REQUIRED_PATTERNS = (
    "登录后查看",
    "请先登录",
    "立即登录",
)

# 失败原因归类时，命中这些即算「风控验证页」。
# = 内容模式 + 只在错误串里出现的几个词。
WAF_REASON_KEYWORDS = CONTENT_PATTERNS + ("风控", "SECURITY_BLOCK", "BLOCKED")

# 只看正文开头这么多字符：风控页的特征在头部，长文正文里的偶发词不算。
CONTENT_HEAD_CHARS = 500

# 正文短于这个长度就不判 —— 沿用 opencli_extractor 的原有直觉，
# 空/极短内容另有「无内容」分支处理，不该在这里被当成风控。
MIN_CONTENT_CHARS = 100


# ── 判定 ────────────────────────────────────────────────────

def _head(text: str) -> str:
    return (text or "")[:CONTENT_HEAD_CHARS]


def contains_waf_text(text: str) -> bool:
    """正文开头是否命中风控内容模式。大小写不敏感。"""
    head = _head(text).lower()
    return any(p in head for p in CONTENT_PATTERNS)


def has_waf_marker(html: str) -> bool:
    """整页 HTML 是否含 WAF 注入的标记（如 ``aliyun_waf``）。"""
    page = (html or "").lower()
    return any(m in page for m in PAGE_MARKERS)


def is_error_title(title: str) -> bool:
    """标题本身是不是错误页标题（精确匹配）。"""
    return (title or "").strip() in TITLE_EXACT


def is_error_page(title: str, content: str = "") -> bool:
    """这页是不是错误页/验证页，而不是真正文。

    标题命中精确集合、或标题为空、或正文开头命中内容模式 → True。
    标题为空也算：抓到空标题通常意味着页面没正常渲染。

    ``title`` 是必传参数，**而且只有显式传入才会走「空标题算错误页」这条规则**。
    如果手上只有正文（没有可信标题），请用 :func:`contains_waf_text` 或
    :func:`looks_like_waf_content` —— 否则 ``title=""`` 会让它恒为 True。
    """
    if is_error_title(title) or not (title or "").strip():
        return True
    return contains_waf_text(content)


def is_waf_blocked(title: str, content: str = "") -> bool:
    """浏览器是不是撞上 WAF 了。比 :func:`is_error_page` 多查整页标记。

    ``content`` 可以传整页 HTML（用于查 :data:`PAGE_MARKERS`），也可以只传正文。
    同样，``title`` 必传，只有正文时用 :func:`contains_waf_text`。
    """
    if is_error_page(title, content):
        return True
    return has_waf_marker(content)


def looks_like_waf_content(content: str, min_chars: int = MIN_CONTENT_CHARS) -> bool:
    """只有正文、没有可信标题时的判定（如 opencli extract 的输出）。

    太短的内容不判 —— 那是「没取到内容」，不是风控。
    """
    if len(content or "") < min_chars:
        return False
    return contains_waf_text(content)


def needs_login(content: str) -> bool:
    """页面是不是登录墙（与风控无关，别用风控关键词）。"""
    head = _head(content)
    return any(p in head for p in AUTH_REQUIRED_PATTERNS)


def classify_failure(err: str) -> str:
    """把一次失败的描述归类，供失败日志与健康检查使用。

    返回：风控验证页 / 登录态失效 / 无数据 / 接口异常 / 其他
    """
    e = err or ""
    if any(k in e for k in WAF_REASON_KEYWORDS):
        return "风控验证页"
    if "AUTH_REQUIRED" in e or "未登录" in e or "登录态" in e:
        return "登录态失效"
    if "EMPTY_RESULT" in e or "no data" in e:
        return "无数据"
    if "HTTP 4" in e or "HTTP 5" in e or "timeout" in e.lower():
        return "接口异常"
    return "其他"


# 会被直接拼进 JS 正则字面量 /.../ 的字符，模式里不允许出现。
_REGEX_METACHARS = frozenset(r".*+?^${}()|[]\/")


def block_guard_js() -> str:
    """生成 opencli 适配器用的 BLOCK_GUARD 正则源码（不含 / 定界符）。

    与 :data:`CONTENT_PATTERNS` 同源 —— 由 ``sync_waf_patterns.py`` 写入
    ``xueqiu-crawler/opencli-adapters/*.js``。

    模式含正则元字符时直接抛错：宁可同步脚本当场失败，
    也不要让一个模式悄悄变成通配符、把正常页面全判成风控。
    """
    bad = sorted(p for p in CONTENT_PATTERNS if set(p) & _REGEX_METACHARS)
    if bad:
        raise ValueError(
            "CONTENT_PATTERNS 含正则元字符，无法原样拼进 JS 正则: %r" % bad
        )
    return "|".join(CONTENT_PATTERNS)
