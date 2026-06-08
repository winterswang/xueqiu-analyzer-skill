"""
xueqiu-analyzer — IMA 笔记发布模块

将分析报告发布为 IMA 笔记，自动提取标题并关联到指定笔记本。
"""

import json
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 默认笔记本配置
DEFAULT_FOLDER_ID = "folder48942b2ec00057d0"   # 价值投资研究
DEFAULT_FOLDER_NAME = "价值投资研究"

# IMA API base
IMA_BASE_URL = "https://ima.qq.com"


def _read_credential(env_key: str, file_path: str) -> str:
    """读取凭证：环境变量优先，回退到文件"""
    import os
    value = os.environ.get(env_key)
    if value:
        return value
    cred_file = Path(file_path).expanduser()
    if cred_file.exists():
        return cred_file.read_text().strip()
    return ""


def _get_ima_credentials() -> tuple[str, str]:
    """获取 IMA 凭证 (client_id, api_key)"""
    client_id = _read_credential("IMA_OPENAPI_CLIENTID", "~/.config/ima/client_id")
    api_key = _read_credential("IMA_OPENAPI_APIKEY", "~/.config/ima/api_key")
    return client_id, api_key


def extract_title(markdown: str) -> str:
    """从 Markdown 提取标题（第一个 heading，去除 # 前缀）"""
    for line in markdown.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            # 去除所有开头的 # 和空格
            return stripped.lstrip("# ").strip()
    # fallback: 第一行非空内容
    for line in markdown.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith(">"):
            return stripped[:100]
    return "未命名报告"


def publish_report(
    content: str,
    folder_id: str = DEFAULT_FOLDER_ID,
    folder_name: str = DEFAULT_FOLDER_NAME,
) -> Optional[str]:
    """发布报告到 IMA 笔记，返回 note_id

    Args:
        content: Markdown 格式报告正文
        folder_id: 目标笔记本 ID（默认：价值投资研究）
        folder_name: 目标笔记本名称

    Returns:
        note_id 或 None
    """
    client_id, api_key = _get_ima_credentials()
    if not client_id or not api_key:
        logger.warning("IMA 凭证未配置，跳过发布")
        return None

    # 确保内容为合法 UTF-8
    try:
        content.encode('utf-8')
    except UnicodeEncodeError:
        content = content.encode('utf-8', errors='ignore').decode('utf-8')
        logger.warning("报告包含非法 UTF-8 字符，已清洗")

    title = extract_title(content)
    logger.info(f"发布 IMA 笔记: {title} → {folder_name}")

    url = f"{IMA_BASE_URL}/openapi/note/v1/import_doc"
    body = {
        "content_format": 1,   # Markdown
        "content": content,
        "folder_id": folder_id,
        "folder_name": folder_name,
    }

    headers = {
        "ima-openapi-clientid": client_id,
        "ima-openapi-apikey": api_key,
        "Content-Type": "application/json",
    }

    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            code = result.get("code")
            if code == 0:
                note_id = result.get("data", {}).get("note_id")
                logger.info(f"IMA 笔记发布成功: note_id={note_id}")
                return note_id
            else:
                logger.error(
                    f"IMA 发布失败: code={code}, "
                    f"msg={result.get('msg', result.get('message', 'N/A'))}"
                )
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        logger.error(f"IMA HTTP {e.code}: {body}")
    except Exception as e:
        logger.error(f"IMA 请求异常: {e}")

    return None
