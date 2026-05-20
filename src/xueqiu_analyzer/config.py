"""
xueqiu-analyzer V3 — 配置加载

优先级：环境变量 > config.yaml > openclaw.json fallback
"""

import os
import json
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / 'config' / 'config.yaml'


def _resolve_env(value) -> str:
    """解析 ${VAR_NAME} 格式的环境变量占位符"""
    if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
        env_name = value[2:-1]
        return os.environ.get(env_name, '')
    return value


def _load_yaml_config(path: Path = None) -> dict:
    """加载 YAML 配置文件"""
    config_path = path or _DEFAULT_CONFIG_PATH
    if config_path.exists():
        with open(config_path, 'r') as f:
            return yaml.safe_load(f) or {}
    return {}


def _load_openclaw_provider() -> Optional[Dict]:
    """从 openclaw.json 读取 provider 作为 fallback"""
    config_path = Path(os.path.expanduser('~/.openclaw/openclaw.json'))
    if not config_path.exists():
        return None
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        providers = config.get('models', {}).get('providers', {})
        for name in ['ark', 'modelstudio', 'clawly-model-gateway']:
            provider = providers.get(name, {})
            api_key = provider.get('apiKey', '')
            if api_key and not api_key.startswith('${'):
                return {
                    'api_key': api_key,
                    'base_url': provider.get('baseUrl', ''),
                    'models': [m.get('id', '') for m in provider.get('models', [])],
                }
    except Exception:
        pass
    return None


def get_config(reload: bool = False) -> dict:
    """
    获取完整配置（带缓存）

    Returns:
        dict: 完整配置，包含 llm/crawler/evaluator/analysis/storage/notify
    """
    if not reload and hasattr(get_config, '_cache') and get_config._cache:
        return get_config._cache

    yaml_config = _load_yaml_config()

    config = {
        'llm': _build_llm_config(yaml_config),
        'crawler': yaml_config.get('crawler', {
            'headless': True, 'delay_min': 3, 'delay_max': 8,
            'max_pages': 10, 'timeout': 30000,
        }),
        'evaluator': yaml_config.get('evaluator', {
            'score_threshold': 150, 'max_rounds': 10,
        }),
        'analysis': yaml_config.get('analysis', {
            'max_discussions': 30, 'max_news': 30, 'max_articles': 10,
        }),
        'storage': yaml_config.get('storage', {
            'data_dir': 'data', 'logs_dir': 'logs',
        }),
        'notify': yaml_config.get('notify', {
            'gist': True, 'feishu': True,
            'feishu_target': '${FEISHU_TARGET_USER}',
        }),
    }

    get_config._cache = config
    return config


def _build_llm_config(yaml_config: dict) -> dict:
    """构建 LLM 配置"""
    llm_cfg = yaml_config.get('llm', {})

    base_url = _resolve_env(llm_cfg.get('base_url', ''))
    model = llm_cfg.get('model', 'doubao-seed-2.0-pro')
    max_tokens = llm_cfg.get('max_tokens', 8000)
    temperature = llm_cfg.get('temperature', 0.7)

    # API Key: 环境变量 > yaml > openclaw.json
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

    return {
        'base_url': base_url.rstrip('/'),
        'model': model,
        'api_key': api_key,
        'max_tokens': max_tokens,
        'temperature': temperature,
    }


def get_llm_config() -> dict:
    """快捷方式：获取 LLM 配置"""
    return get_config()['llm']


def get_data_dir() -> Path:
    """获取数据输出目录"""
    config = get_config()
    data_dir = Path(config['storage']['data_dir'])
    if not data_dir.is_absolute():
        data_dir = _PROJECT_ROOT / data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
