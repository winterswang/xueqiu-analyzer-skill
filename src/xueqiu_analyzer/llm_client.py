"""
xueqiu-analyzer V3 — LLM 客户端

统一的 LLM 调用接口，支持不同 system prompt 和参数。
"""

import json
import logging
import urllib.request
import urllib.error
from typing import Dict, List, Optional

from .config import get_llm_config

logger = logging.getLogger(__name__)


class LLMClient:
    """统一 LLM 调用客户端"""

    def __init__(self, config: dict = None):
        self.config = config or get_llm_config()

    @property
    def model(self) -> str:
        return self.config['model']

    def chat(self, messages: List[Dict], max_tokens: int = None,
             temperature: float = None) -> str:
        """
        通用聊天接口

        Args:
            messages: OpenAI 格式消息列表
            max_tokens: 最大 token 数（默认用配置值）
            temperature: 温度（默认用配置值）

        Returns:
            LLM 生成的文本
        """
        data = {
            "model": self.config['model'],
            "messages": messages,
            "max_tokens": max_tokens or self.config['max_tokens'],
            "temperature": temperature if temperature is not None
            else self.config['temperature'],
        }

        headers = {
            "Authorization": f"Bearer {self.config['api_key']}",
            "Content-Type": "application/json",
        }

        url = f"{self.config['base_url']}/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST',
        )

        try:
            with urllib.request.urlopen(req, timeout=1800) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                return result['choices'][0]['message']['content']
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''
            logger.error(f"LLM API 错误 ({e.code}): {error_body[:500]}")
            raise RuntimeError(f"LLM API 错误 ({e.code}): {error_body[:200]}")
        except Exception as e:
            logger.error(f"LLM 调用异常: {e}")
            raise RuntimeError(f"LLM 调用失败: {e}") from e

    def evaluate(self, prompt: str, max_tokens: int = 4000) -> str:
        """评估专用"""
        messages = [
            {"role": "system",
             "content": "你是一位资深价值投资分析师，擅长评估投资信息的充分性和质量。请以JSON格式输出评估结果。"},
            {"role": "user", "content": prompt},
        ]
        return self.chat(messages, max_tokens=max_tokens, temperature=0.3)

    def analyze(self, prompt: str, max_tokens: int = 8000) -> str:
        """分析专用"""
        messages = [
            {"role": "system",
             "content": "你是一位专业的投资分析助手，擅长分析股票投资价值。请用中文回答，输出结构化的投资分析报告。"},
            {"role": "user", "content": prompt},
        ]
        return self.chat(messages, max_tokens=max_tokens, temperature=0.7)

    def simple_chat(self, prompt: str, max_tokens: int = 4000) -> str:
        """简单对话（无 system prompt）"""
        return self.chat([{"role": "user", "content": prompt}],
                         max_tokens=max_tokens)
