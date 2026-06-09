"""
xueqiu-analyzer V3 — LLM 客户端

统一的 LLM 调用接口，支持不同 system prompt 和参数。
"""

import json
import logging
import time
import urllib.request
import urllib.error
from typing import Dict, List, Optional

from .config import get_llm_config

logger = logging.getLogger(__name__)

# 重试配置
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0  # 秒
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


class LLMClient:
    """统一 LLM 调用客户端"""

    def __init__(self, config: dict = None):
        self.config = config or get_llm_config()

    @property
    def model(self) -> str:
        return self.config['model']

    def chat(self, messages: List[Dict], max_tokens: int = None,
             temperature: float = None, timeout: int = 300) -> str:
        """
        通用聊天接口（带自动重试 + exponential backoff）

        Args:
            messages: OpenAI 格式消息列表
            max_tokens: 最大 token 数（默认用配置值）
            temperature: 温度（默认用配置值）
            timeout: 请求超时秒数（默认 300）

        Returns:
            LLM 生成的文本

        Raises:
            RuntimeError: 重试次数耗尽后仍失败
        """
        data = {
            "model": self.config['model'],
            "messages": messages,
            "max_tokens": max_tokens if max_tokens is not None else self.config['max_tokens'],
            "temperature": temperature if temperature is not None
            else self.config['temperature'],
        }

        headers = {
            "Authorization": f"Bearer {self.config['api_key']}",
            "Content-Type": "application/json",
        }

        url = f"{self.config['base_url']}/chat/completions"
        body = json.dumps(data).encode('utf-8')

        for attempt in range(MAX_RETRIES + 1):
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method='POST')
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    result = json.loads(resp.read().decode('utf-8'))
                    return result['choices'][0]['message']['content']

            except urllib.error.HTTPError as e:
                error_body = e.read().decode('utf-8') if e.fp else ''
                code = e.code

                if code in RETRYABLE_HTTP_CODES and attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning(
                        f"LLM API {code} (attempt {attempt+1}/{MAX_RETRIES+1}), "
                        f"{wait:.0f}s 后重试: {error_body[:100]}"
                    )
                    time.sleep(wait)
                    continue

                logger.error(f"LLM API 错误 ({code}): {error_body[:500]}")
                raise RuntimeError(f"LLM API 错误 ({code}): {error_body[:200]}") from e

            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning(
                        f"LLM 网络异常 (attempt {attempt+1}/{MAX_RETRIES+1}): {e}, "
                        f"{wait:.0f}s 后重试"
                    )
                    time.sleep(wait)
                    continue
                logger.error(f"LLM 网络异常，重试耗尽: {e}")
                raise RuntimeError(f"LLM 调用失败: {e}") from e

            except Exception as e:
                logger.error(f"LLM 调用异常: {e}")
                raise RuntimeError(f"LLM 调用失败: {e}") from e

        # 不应该到达这里
        raise RuntimeError("LLM 调用失败: 未知错误")

    def evaluate(self, prompt: str, max_tokens: int = 4000) -> str:
        """评估专用（timeout 120s，低 temperature）"""
        messages = [
            {"role": "system",
             "content": "你是一位资深价值投资分析师，擅长评估投资信息的充分性和质量。请以JSON格式输出评估结果。"},
            {"role": "user", "content": prompt},
        ]
        return self.chat(messages, max_tokens=max_tokens, temperature=0.3, timeout=120)

    def analyze(self, prompt: str, max_tokens: int = 8000) -> str:
        """分析专用（timeout 300s）"""
        messages = [
            {"role": "system",
             "content": "你是一位专业的投资分析助手，擅长分析股票投资价值。请用中文回答，输出结构化的投资分析报告。"},
            {"role": "user", "content": prompt},
        ]
        return self.chat(messages, max_tokens=max_tokens, temperature=0.7, timeout=300)

    def simple_chat(self, prompt: str, max_tokens: int = 4000) -> str:
        """简单对话（无 system prompt，timeout 300s）"""
        return self.chat([{"role": "user", "content": prompt}],
                         max_tokens=max_tokens, timeout=300)
