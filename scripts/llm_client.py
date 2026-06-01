#!/usr/bin/env python3
"""
统一的 LLM 调用客户端

功能：
- 多源 API Key 回退链（BAILIAN_API_KEY → DASHSCOPE_API_KEY → OPENAI_API_KEY → openclaw.json）
- base_url 自动发现
- 统一的超时、错误处理、traceback 保留
- 可配置模型名（默认 glm-5）

用法：
    from llm_client import LLMClient

    client = LLMClient()
    result = client.chat("分析这只股票", max_tokens=8000)
"""

import os
import json
import logging

# 自动加载项目 .env（不依赖 bash 环境）
try:
    from dotenv import load_dotenv
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _dotenv_path = os.path.join(_project_root, '.env')
    if os.path.exists(_dotenv_path):
        load_dotenv(_dotenv_path, override=False)
except ImportError:
    pass
import urllib.request
import urllib.error
from typing import Optional

DEFAULT_BASE_URL = 'https://coding.dashscope.aliyuncs.com/v1'
DEFAULT_MODEL = 'glm-5'

logger = logging.getLogger('LLMClient')


def _resolve_api_key() -> Optional[str]:
    """多源获取 API Key（按优先级）"""
    api_key = (
        os.environ.get('BAILIAN_API_KEY')
        or os.environ.get('DASHSCOPE_API_KEY')
        or os.environ.get('OPENAI_API_KEY', '')
    )

    if api_key:
        return api_key

    # 从 openclaw.json 读取配置（作为 fallback）
    config_path = os.path.expanduser('~/.openclaw/openclaw.json')
    if not os.path.exists(config_path):
        return None

    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        providers = config.get('models', {}).get('providers', {})
        for name in ['modelstudio', 'clawly-model-gateway', 'qwencode', 'qwen']:
            provider = providers.get(name, {})
            raw_key = provider.get('apiKey', '')
            if raw_key and not raw_key.startswith('${'):
                return raw_key
    except Exception:
        logger.debug("读取 openclaw.json 失败", exc_info=True)

    return None


def _resolve_base_url() -> str:
    """从 openclaw.json 读取 base_url"""
    config_path = os.path.expanduser('~/.openclaw/openclaw.json')
    if not os.path.exists(config_path):
        return DEFAULT_BASE_URL

    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        providers = config.get('models', {}).get('providers', {})
        for name in ['modelstudio', 'clawly-model-gateway', 'qwencode', 'qwen']:
            provider = providers.get(name, {})
            raw_url = provider.get('baseUrl', '')
            if raw_url and not raw_url.startswith('${'):
                return raw_url.rstrip('/')
    except Exception:
        logger.debug("读取 openclaw.json base_url 失败", exc_info=True)

    return DEFAULT_BASE_URL


class LLMError(Exception):
    """LLM 调用异常，保留原始异常链"""


class LLMClient:
    """统一的 LLM 调用客户端"""

    def __init__(self, api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 model: Optional[str] = None):
        """
        Args:
            api_key: API Key（默认自动回退发现）
            base_url: API 基础 URL（默认自动发现）
            model: 模型名（默认 glm-5）
        """
        self.api_key = api_key or _resolve_api_key()
        self.base_url = (base_url or _resolve_base_url()).rstrip('/')
        self.model = model or DEFAULT_MODEL

        if not self.api_key:
            raise LLMError(
                "未配置 API Key。请设置 BAILIAN_API_KEY、DASHSCOPE_API_KEY "
                "或 OPENAI_API_KEY 环境变量"
            )

    def chat(self, prompt: str, max_tokens: int = 4000,
             system_prompt: Optional[str] = None,
             temperature: float = 0.7,
             timeout: int = 1800) -> str:
        """
        调用 LLM chat 接口

        Args:
            prompt: 用户提示词
            max_tokens: 最大输出 token 数
            system_prompt: 系统提示词（可选）
            temperature: 采样温度
            timeout: 请求超时时间（秒）

        Returns:
            模型回复文本

        Raises:
            LLMError: API 调用失败
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        api_url = f"{self.base_url}/chat/completions"

        try:
            req = urllib.request.Request(
                api_url,
                data=json.dumps(data).encode('utf-8'),
                headers=headers,
                method='POST'
            )

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                return result['choices'][0]['message']['content']

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''
            raise LLMError(f"API 请求失败 ({e.code}): {error_body}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"API 网络错误: {e.reason}") from e
        except (json.JSONDecodeError, KeyError) as e:
            raise LLMError(f"API 响应解析失败: {e}") from e
        except Exception as e:
            raise LLMError(f"API 调用异常: {e}") from e
