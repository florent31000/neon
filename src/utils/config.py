"""
Configuration loader for Neon.
Reads YAML settings and personality files.
"""

from pathlib import Path
from typing import Any, Dict

import yaml


_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
_config_cache: Dict[str, Any] = {}
_personality_cache: Dict[str, Any] = {}


def load_config(force_reload: bool = False) -> Dict[str, Any]:
    global _config_cache
    if _config_cache and not force_reload:
        return _config_cache

    settings_path = _CONFIG_DIR / "settings.yaml"
    if not settings_path.exists():
        raise FileNotFoundError(f"Settings file not found: {settings_path}")

    with open(settings_path, "r", encoding="utf-8") as f:
        _config_cache = yaml.safe_load(f) or {}
    return _config_cache


def load_personality(force_reload: bool = False) -> Dict[str, Any]:
    global _personality_cache
    if _personality_cache and not force_reload:
        return _personality_cache

    path = _CONFIG_DIR / "personality.yaml"
    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        _personality_cache = yaml.safe_load(f) or {}
    return _personality_cache


def get_api_key(provider: str) -> str:
    config = load_config()
    return config.get("api_keys", {}).get(provider, "")


def get_robot_name() -> str:
    config = load_config()
    return config.get("robot", {}).get("name", "Néon")
