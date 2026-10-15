"""打包自包含性（issue #47）。

本包按仓库布局运行：`config/config.yaml` 与 `prompts/` 在仓库根目录、不随 wheel
发布。这里钉两件事：

1. `[project].dependencies` 必须覆盖**无条件导入**的运行依赖 —— 缺 `requests`
   时 `pip install .` 装出的 `xueqiu` 会在导入阶段就崩（README 先装
   requirements.txt，把这个问题盖住了）。
2. 默认 config.yaml 找不到时要**出声**，不能静默退回内置默认值。
"""

import logging
import re
import tomllib
from pathlib import Path

from xueqiu_analyzer import config as cfg

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_requests_declared_in_project_dependencies():
    meta = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = " ".join(meta["project"]["dependencies"])

    assert "requests" in deps, "crawler 模块级导入 requests，必须在项目元数据里声明"


def test_crawler_still_imports_requests_at_module_level():
    """声明 requests 的理由就是这个模块级导入；它变了这条声明才有资格删。"""
    src = (REPO_ROOT / "src" / "xueqiu_analyzer" / "crawler.py").read_text(encoding="utf-8")

    assert re.search(r"(?m)^import requests$", src)


def test_readme_documents_repo_layout_requirement():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "只支持仓库布局" in readme


def test_missing_default_config_warns(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(cfg, "_DEFAULT_CONFIG_PATH", tmp_path / "nope" / "config.yaml")

    with caplog.at_level(logging.WARNING, logger=cfg.__name__):
        assert cfg._load_yaml_config() == {}

    assert "内置默认配置" in caplog.text


def test_explicit_path_does_not_warn(monkeypatch, caplog, tmp_path):
    """调用方显式指定路径时不算布局问题，不打扰。"""
    with caplog.at_level(logging.WARNING, logger=cfg.__name__):
        assert cfg._load_yaml_config(tmp_path / "nope.yaml") == {}

    assert caplog.text == ""
