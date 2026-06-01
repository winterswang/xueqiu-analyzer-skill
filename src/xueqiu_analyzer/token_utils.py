"""Token 估算与分批工具"""


def estimate_tokens(text: str) -> int:
    """保守估算 token 数: 字符数 × 2"""
    return len(text) * 2


def build_batches(items: list, max_content_tokens: int = 63000) -> list:
    """按 token 预算将 items 分批，保证每批内容 token 数不超过上限"""
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
