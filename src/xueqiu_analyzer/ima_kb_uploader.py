"""
xueqiu-analyzer V3 — IMA 知识库上传模块

将 CSV/PDF 文件上传到 IMA 知识库，支持：
- 4 个 CSV（discussions/articles/news/notices）
- 单个文件上传
- 批量上传
- 知识库列表查询

上传流程: check_repeated_names → create_media → COS upload → add_knowledge

参考: /root/code/unified-downloader/sync_to_ima.py
IMA API: https://ima.qq.com/openapi/wiki/v1/
"""

import json
import logging
import os
import ssl
import subprocess
import time as _time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 配置 ────────────────────────────────────────────────────────────────────

_HOME = Path.home()
_IMA_CONFIG_DIR = _HOME / ".config" / "ima"
_CTX = ssl.create_default_context()

COS_UPLOAD_SCRIPT = os.environ.get(
    "COS_UPLOAD_SCRIPT",
    str(_HOME / ".openclaw" / "workspace" / "skills" / "ima" /
        "knowledge-base" / "scripts" / "cos-upload.cjs"),
)

# 文件大小限制 (media_type=5: Excel/CSV → 10 MB)
MAX_CSV_SIZE = 10 * 1024 * 1024  # 10 MB

# API 重试配置
_MAX_API_RETRIES = 3
_API_RETRY_DELAY = 2.0
_API_RETRYABLE_CODES = (429, 110021)  # 频率限制, 知识库处理中


def _read_credential(filename: str) -> str:
    """从 ~/.config/ima/ 读取凭证文件."""
    path = _IMA_CONFIG_DIR / filename
    if path.exists():
        return path.read_text().strip()
    return ""


def _get_ima_credentials() -> tuple[str, str]:
    """获取 IMA 凭证 (client_id, api_key)."""
    client_id = os.environ.get("IMA_OPENAPI_CLIENTID") or _read_credential("client_id")
    api_key = os.environ.get("IMA_OPENAPI_APIKEY") or _read_credential("api_key")
    return client_id, api_key


def _api(path: str, body: dict, timeout: int = 30) -> dict:
    """调用 IMA OpenAPI（带自动重试）。

    对限频(429/110021)和网络异常自动重试，
    最多 3 次，指数退避(2/4/8s)。
    """
    client_id, api_key = _get_ima_credentials()
    if not client_id or not api_key:
        raise RuntimeError("IMA 凭证未配置。请设置环境变量或 ~/.config/ima/")

    url = f"https://ima.qq.com{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "ima-openapi-clientid": client_id,
        "ima-openapi-apikey": api_key,
        "Content-Type": "application/json; charset=utf-8",
    }

    for attempt in range(_MAX_API_RETRIES + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, context=_CTX, timeout=timeout) as r:
                result = json.loads(r.read().decode("utf-8"))
                code = result.get("code", -1)

                if code in _API_RETRYABLE_CODES and attempt < _MAX_API_RETRIES:
                    wait = _API_RETRY_DELAY ** (attempt + 1)
                    logger.warning(
                        f"IMA API {code} (attempt {attempt+1}/{_MAX_API_RETRIES+1}), "
                        f"{wait:.0f}s 后重试: {result.get('msg', '?')}"
                    )
                    _time.sleep(wait)
                    continue

                return result

        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < _MAX_API_RETRIES:
                wait = _API_RETRY_DELAY ** (attempt + 1)
                logger.warning(
                    f"IMA 网络异常 (attempt {attempt+1}/{_MAX_API_RETRIES+1}): {e}, "
                    f"{wait:.0f}s 后重试"
                )
                _time.sleep(wait)
                continue
            raise RuntimeError(f"IMA API 调用失败: {e}") from e

        except urllib.error.HTTPError as e:
            code = e.code
            if code in {429, 500, 502, 503, 504} and attempt < _MAX_API_RETRIES:
                wait = _API_RETRY_DELAY ** (attempt + 1)
                logger.warning(
                    f"IMA HTTP {code} (attempt {attempt+1}/{_MAX_API_RETRIES+1}), "
                    f"{wait:.0f}s 后重试"
                )
                _time.sleep(wait)
                continue
            raise RuntimeError(f"IMA HTTP {code}: {e}") from e

    raise RuntimeError(f"IMA API 重试耗尽: {path}")


def list_knowledge_bases() -> list[dict]:
    """获取可上传的知识库列表。

    Returns:
        [{"id": ..., "name": ...}, ...]
    """
    all_kbs = []
    cursor = ""
    while True:
        r = _api("/openapi/wiki/v1/get_addable_knowledge_base_list", {
            "cursor": cursor,
            "limit": 50,
        })
        if r.get("code") != 0:
            raise RuntimeError(f"获取知识库列表失败: {r}")
        data = r.get("data", {})
        kbs = data.get("addable_knowledge_base_list", [])
        all_kbs.extend(kbs)
        if data.get("is_end"):
            break
        cursor = data.get("next_cursor", "")
    return all_kbs


def _detect_media_type(file_path: str) -> tuple[int, str]:
    """根据文件扩展名检测 media_type 和 content_type."""
    ext = Path(file_path).suffix.lower().lstrip(".")
    if ext == "csv":
        return 5, "text/csv"
    elif ext == "pdf":
        return 1, "application/pdf"
    elif ext in ("xlsx", "xls"):
        return 5, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif ext in ("doc", "docx"):
        return 3, "application/msword"
    elif ext == "txt":
        return 13, "text/plain"
    else:
        return 5, "application/octet-stream"  # fallback


def upload_file(
    file_path: str,
    knowledge_base_id: str,
    folder_id: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """上传单个文件到 IMA 知识库。

    Args:
        file_path: 本地文件路径
        knowledge_base_id: IMA 知识库 ID
        folder_id: 目标文件夹 ID（可选，默认根目录）
        title: 文件标题（可选，默认使用文件名）

    Returns:
        media_id

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: 文件过大或空文件
        RuntimeError: API 调用失败
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    file_size = path.stat().st_size
    if file_size == 0:
        raise ValueError(f"空文件: {file_path}")
    if file_size > MAX_CSV_SIZE and path.suffix.lower() == ".csv":
        raise ValueError(
            f"CSV 文件过大: {file_size:,} bytes (限制 {MAX_CSV_SIZE:,} bytes)"
        )

    file_name = title or path.name
    media_type, content_type = _detect_media_type(str(path))
    file_ext = path.suffix.lower().lstrip(".")

    logger.info(f"上传 IMA: {path.name} ({file_size:,} bytes) → KB {knowledge_base_id}")

    # Step 1: 检查重名 (optional, non-blocking)
    try:
        r = _api("/openapi/wiki/v1/check_repeated_names", {
            "params": [{"name": file_name, "media_type": media_type}],
            "knowledge_base_id": knowledge_base_id,
            "folder_id": folder_id or "",
        }, timeout=10)
        repeated = r.get("data", {}).get("results", [])
        if repeated and repeated[0].get("is_repeated"):
            logger.warning(f"知识库中已存在同名文件: {file_name}，将覆盖")
    except Exception as e:
        logger.warning(f"重名检查失败（继续上传）: {e}")

    # Step 2: 创建媒体
    r = _api("/openapi/wiki/v1/create_media", {
        "file_name": file_name,
        "file_size": file_size,
        "content_type": content_type,
        "file_ext": file_ext,
        "knowledge_base_id": knowledge_base_id,
    })
    if r.get("code") != 0:
        raise RuntimeError(f"create_media 失败: {r}")

    data = r["data"]
    media_id = data["media_id"]
    cos = data["cos_credential"]

    # Step 3: COS 上传 (via node.js script)
    if not os.path.exists(COS_UPLOAD_SCRIPT):
        raise RuntimeError(
            f"COS 上传脚本未找到: {COS_UPLOAD_SCRIPT}\n"
            f"请安装 ima-skills 或设置 COS_UPLOAD_SCRIPT 环境变量"
        )

    proc = subprocess.Popen(
        ["node", COS_UPLOAD_SCRIPT,
         "--file", str(path),
         "--secret-id", cos["secret_id"],
         "--secret-key", cos["secret_key"],
         "--token", cos["token"],
         "--bucket", cos["bucket_name"],
         "--region", cos["region"],
         "--cos-key", cos["cos_key"],
         "--content-type", content_type],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stdout, stderr = proc.communicate()
    if proc.returncode != 0 or "successful" not in stdout.decode().lower():
        err = stderr.decode()[:200] if stderr else stdout.decode()[:200]
        raise RuntimeError(f"COS 上传失败: {err}")

    logger.info(f"COS 上传完成: {file_name}")

    # Step 4: 添加知识
    kb_body = {
        "knowledge_base_id": knowledge_base_id,
        "media_type": media_type,
        "media_id": media_id,
        "title": file_name,
        "file_info": {
            "cos_key": cos["cos_key"],
            "file_name": file_name,
            "file_size": file_size,
            "last_modify_time": int(path.stat().st_mtime),
        },
    }
    if folder_id:
        kb_body["folder_id"] = folder_id

    r = _api("/openapi/wiki/v1/add_knowledge", kb_body)
    if r.get("code") != 0:
        raise RuntimeError(f"add_knowledge 失败: {r}")

    logger.info(f"✅ IMA 入库完成: {file_name} media_id={media_id[:40]}...")
    return media_id


def upload_csv_set(
    csv_files: dict,
    knowledge_base_id: str,
    folder_id: Optional[str] = None,
) -> dict:
    """批量上传 CSV 文件到 IMA 知识库。

    Args:
        csv_files: export_csv() 返回的 {type: path} 字典
        knowledge_base_id: IMA 知识库 ID
        folder_id: 目标文件夹 ID

    Returns:
        {'success': [media_id, ...], 'failed': {'type': error, ...}}
        即使部分失败也返回结果（不抛异常）
    """
    if not csv_files:
        logger.warning("没有 CSV 文件可上传")
        return {"success": [], "failed": {}}

    success = []
    failed = {}

    for csv_type in ["discussions", "articles", "news", "notices"]:
        path_str = csv_files.get(csv_type)
        if not path_str:
            continue
        try:
            mid = upload_file(path_str, knowledge_base_id, folder_id)
            success.append(mid)
        except Exception as e:
            logger.error(f"上传失败 {csv_type}: {e}")
            failed[csv_type] = str(e)

    return {"success": success, "failed": failed}
