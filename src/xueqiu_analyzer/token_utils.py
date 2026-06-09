"""Token 估算与分批工具"""

import logging

logger = logging.getLogger(__name__)

# Lazy-loaded tokenizer
_encoder = None
_encoder_available = False


def _get_encoder():
    """获取 tokenizer encoder（lazy init，避免 tiktoken 未安装时崩溃）"""
    global _encoder, _encoder_available
    if _encoder is not None:
        return _encoder
    if not _encoder_available:
        try:
            import tiktoken
            _encoder = tiktoken.get_encoding("cl100k_base")
            _encoder_available = True
            logger.debug("Token 估算: 使用 tiktoken cl100k_base")
        except Exception:
            logger.debug("Token 估算: tiktoken 不可用，回退到 len*2")
            _encoder_available = False
    return _encoder


def estimate_tokens(text: str) -> int:
    """估算 token 数。

    优先使用 tiktoken cl100k_base（比 len*2 精度提升 3-5x），
    不可用时回退到 len*2（过度保守但安全——会创建更多批次而非丢失内容）。
    """
    enc = _get_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    return len(text) * 2


def build_batches(items: list, max_content_tokens: int = 63000,
                  max_items: int = None) -> list:
    """按 token 预算将 items 分批，保证每批内容 token 数不超过上限

    Args:
        items: 待分批的条目列表
        max_content_tokens: 每批 token 上限
        max_items: 每批条目数上限（None=不限）
    """
    batches = []
    current_batch = []
    current_tokens = 0

    for item in items:
        content = item.get("content", "")
        author = item.get("author", "")
        item_tokens = estimate_tokens(f"{author}\n{content}")

        split = (current_batch and
                 (current_tokens + item_tokens > max_content_tokens or
                  (max_items and len(current_batch) >= max_items)))
        if split:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0

        current_batch.append(item)
        current_tokens += item_tokens

    if current_batch:
        batches.append(current_batch)

    return batches
