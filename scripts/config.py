"""
配置模块
"""
import os
import logging
from pathlib import Path

# 自动加载项目 .env（不依赖 bash 环境）
try:
    from dotenv import load_dotenv
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _dotenv_path = os.path.join(_project_root, '.env')
    if os.path.exists(_dotenv_path):
        load_dotenv(_dotenv_path, override=False)
except ImportError:
    pass

# 日志配置
def setup_logging(name: str = __name__, level: int = logging.INFO) -> logging.Logger:
    """配置日志系统"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(level)
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        logger.addHandler(handler)
    return logger

PROJECT_ROOT = Path(__file__).parent.parent
WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", str(PROJECT_ROOT.parent))

# 常用路径
AKSHARE_DOCS_PATH = Path(WORKSPACE_DIR) / "akshare_docs"
CONFIG_DIR = PROJECT_ROOT / "config"
XUEQIU_ANALYZER_PATH = PROJECT_ROOT
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# Chrome 路径 (使用已安装的 Chrome)
CHROME_PATH = os.environ.get("CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
