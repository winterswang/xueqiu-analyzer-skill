"""
LLM 配置加载器 - 统一从 config/config.yaml 读取 LLM 配置

优先级：
1. 环境变量 (ARK_API_KEY / BAILIAN_API_KEY / DASHSCOPE_API_KEY)
2. config/config.yaml 的 llm 节
3. openclaw.json 的 ark provider (fallback)
"""

import os
import json
import yaml


def _resolve_env(value):
    """解析 ${VAR_NAME} 格式的环境变量占位符"""
    if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
        env_name = value[2:-1]
        resolved = os.environ.get(env_name, '')
        if resolved:
            return resolved
        # 环境变量未设置，返回空串，后续会用 fallback
        return ''
    return value


def _load_yaml_config():
    """加载 config/config.yaml"""
    config_paths = [
        os.path.join(os.path.dirname(__file__), '..', 'config', 'config.yaml'),
        os.path.expanduser('~/.xueqiu_crawler/config.yaml'),
    ]
    for path in config_paths:
        path = os.path.abspath(path)
        if os.path.exists(path):
            with open(path, 'r') as f:
                return yaml.safe_load(f) or {}
    return {}


def _load_openclaw_provider():
    """从 openclaw.json 读取 ark provider 作为 fallback"""
    config_path = os.path.expanduser('~/.openclaw/openclaw.json')
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        providers = config.get('models', {}).get('providers', {})
        # 优先找 ark，兼容旧的百炼配置
        for name in ['ark', 'modelstudio', 'clawly-model-gateway', 'qwencode', 'qwen']:
            provider = providers.get(name, {})
            api_key = provider.get('apiKey', '')
            base_url = provider.get('baseUrl', '')
            if api_key and not api_key.startswith('${'):
                return {
                    'api_key': api_key,
                    'base_url': base_url if base_url and not base_url.startswith('${') else '',
                    'model': '',
                }
    except Exception:
        pass
    return None


def get_llm_config():
    """
    获取 LLM 配置，返回 dict:
      - base_url: str
      - model: str
      - api_key: str
      - max_tokens: int
      - temperature: float
    """
    yaml_config = _load_yaml_config()
    llm_cfg = yaml_config.get('llm', {})

    # 基础值从 yaml 读
    base_url = _resolve_env(llm_cfg.get('base_url', ''))
    model = llm_cfg.get('model', 'doubao-seed-2.0-pro')
    max_tokens = llm_cfg.get('max_tokens', 8000)
    temperature = llm_cfg.get('temperature', 0.7)

    # API Key: 环境变量 > yaml > openclaw.json fallback
    api_key = (
        os.environ.get('ARK_API_KEY') or
        os.environ.get('BAILIAN_API_KEY') or
        os.environ.get('DASHSCOPE_API_KEY') or
        _resolve_env(llm_cfg.get('api_key', ''))
    )

    if not api_key:
        fallback = _load_openclaw_provider()
        if fallback:
            api_key = fallback['api_key']
            if not base_url and fallback['base_url']:
                base_url = fallback['base_url']

    if not base_url:
        base_url = 'https://ark.cn-beijing.volces.com/api/coding/v3'

    if not api_key:
        raise ValueError(
            "未找到 LLM API Key。请通过以下任一方式配置：\n"
            "  1. 设置环境变量: export ARK_API_KEY=xxx\n"
            "  2. 在 config/config.yaml 的 llm.api_key 中配置\n"
            "  3. 在 openclaw.json 的 ark provider 中配置"
        )

    return {
        'base_url': base_url.rstrip('/'),
        'model': model,
        'api_key': api_key,
        'max_tokens': max_tokens,
        'temperature': temperature,
    }


def call_llm(prompt: str, max_tokens: int = None, system_prompt: str = None) -> str:
    """
    调用 LLM 的统一入口，供各脚本直接使用。

    Args:
        prompt: 用户提示词
        max_tokens: 最大 token 数（可选，默认用配置值）
        system_prompt: 系统提示词（可选）

    Returns:
        LLM 生成的文本
    """
    import urllib.request

    cfg = get_llm_config()
    url = f"{cfg['base_url']}/chat/completions"

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    data = {
        "model": cfg['model'],
        "messages": messages,
        "max_tokens": max_tokens or cfg['max_tokens'],
        "temperature": cfg['temperature'],
    }

    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers=headers,
        method='POST',
    )

    with urllib.request.urlopen(req, timeout=1800) as resp:
        result = json.loads(resp.read().decode('utf-8'))
        return result['choices'][0]['message']['content']
