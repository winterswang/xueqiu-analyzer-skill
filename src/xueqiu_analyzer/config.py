"""
xueqiu-analyzer V3 — 配置加载

优先级：环境变量 > config.yaml > openclaw.json fallback
"""

import os
import json
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

# 自动加载项目 .env（不依赖 shell 环境），已存在的环境变量优先
_PROJECT_ROOT = Path(__file__).parent.parent.parent
try:
    from dotenv import load_dotenv
    _dotenv_path = _PROJECT_ROOT / '.env'
    if _dotenv_path.exists():
        load_dotenv(_dotenv_path, override=False)
except ImportError:
    pass

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
        # openclaw.json 不可用或格式错误，使用 config.yaml + 环境变量即可
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
    """构建 LLM 配置

    API Key 优先级：
    1. config.yaml 中 api_key 指定的环境变量
    2. 通用 fallback: ARK_API_KEY > BAILIAN_API_KEY > DASHSCOPE_API_KEY
    3. OpenClaw provider 配置（仅当以上都为空时）

    当 key 来源变更时，base_url 自动跟随切换，避免 key/endpoint 不匹配。
    """
    llm_cfg = yaml_config.get('llm', {})

    base_url = _resolve_env(llm_cfg.get('base_url', ''))
    model = llm_cfg.get('model', 'doubao-seed-2.0-pro')
    max_tokens = llm_cfg.get('max_tokens', 8000)
    temperature = llm_cfg.get('temperature', 0.7)

    # API Key: yaml指定的env > 通用fallback > openclaw.json
    primary_key = _resolve_env(llm_cfg.get('api_key', ''))
    api_key = primary_key or ''

    # 通用 fallback：只有当 yaml 中的 key env 未设置时才检查
    if not api_key:
        _FALLBACK_KEYS = [
            ('ARK_API_KEY', {
                'base_url': 'https://ark.cn-beijing.volces.com/api/coding/v3',
            }),
            ('BAILIAN_API_KEY', {
                'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            }),
            ('DASHSCOPE_API_KEY', {
                'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            }),
        ]
        for env_name, defaults in _FALLBACK_KEYS:
            fallback_key = os.environ.get(env_name, '')
            if fallback_key:
                api_key = fallback_key
                # key 来源变更 → base_url 跟随切换
                base_url = defaults.get('base_url', base_url)
                break

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
