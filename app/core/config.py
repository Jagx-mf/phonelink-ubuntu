"""Persistent user configuration for PhoneLink Ubuntu."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)

CONFIG_DIR = Path.home() / ".config" / "phonelink-ubuntu"
CONFIG_FILE = CONFIG_DIR / "config.json"


#: Base URL par défaut de l'app compagnon Android (cf. android_bridge).
DEFAULT_ANDROID_BRIDGE_URL = "http://127.0.0.1:8765"


@dataclass
class PhoneLinkConfig:
    phone_mac: str = ""
    phone_name: str = ""
    adb_wifi_host: str = ""
    adb_wifi_port: int = 5555
    # App compagnon Android (SMS) — cf. docs/android-backend-v0.4.md
    android_bridge_base_url: str = DEFAULT_ANDROID_BRIDGE_URL
    android_bridge_token: str = ""
    android_bridge_mode: str = "mock"  # "mock" | "http"


def get_config_path() -> Path:
    """Return the user configuration file path."""
    return CONFIG_FILE


def load_config() -> PhoneLinkConfig:
    """Load configuration, returning defaults if the file is absent or invalid."""
    path = get_config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return PhoneLinkConfig()
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Cannot load config %s: %s", path, exc)
        return PhoneLinkConfig()

    if not isinstance(data, dict):
        logger.warning("Invalid config format in %s", path)
        return PhoneLinkConfig()

    return PhoneLinkConfig(
        phone_mac=_as_str(data.get("phone_mac")).upper(),
        phone_name=_as_str(data.get("phone_name")),
        adb_wifi_host=_as_str(data.get("adb_wifi_host")),
        adb_wifi_port=_as_port(data.get("adb_wifi_port")),
        android_bridge_base_url=_as_str(data.get("android_bridge_base_url"))
        or DEFAULT_ANDROID_BRIDGE_URL,
        android_bridge_token=_as_str(data.get("android_bridge_token")),
        android_bridge_mode=_as_bridge_mode(data.get("android_bridge_mode")),
    )


def save_config(config: PhoneLinkConfig | dict[str, Any]) -> None:
    """Persist configuration as JSON, creating the parent directory if needed."""
    path = get_config_path()
    if isinstance(config, PhoneLinkConfig):
        data = asdict(config)
    else:
        data = {
            "phone_mac": _as_str(config.get("phone_mac")).upper(),
            "phone_name": _as_str(config.get("phone_name")),
            "adb_wifi_host": _as_str(config.get("adb_wifi_host")),
            "adb_wifi_port": _as_port(config.get("adb_wifi_port")),
            "android_bridge_base_url": _as_str(config.get("android_bridge_base_url"))
            or DEFAULT_ANDROID_BRIDGE_URL,
            "android_bridge_token": _as_str(config.get("android_bridge_token")),
            "android_bridge_mode": _as_bridge_mode(config.get("android_bridge_mode")),
        }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError as exc:
        logger.warning("Cannot save config %s: %s", path, exc)


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _as_bridge_mode(value: Any) -> str:
    """Coerce a value into a valid bridge mode, defaulting to 'mock'."""
    return value if value in ("mock", "http") else "mock"


def _as_port(value: Any) -> int:
    """Coerce a value into a valid TCP port, defaulting to 5555."""
    if isinstance(value, bool):
        return 5555
    if isinstance(value, int):
        return value if 1 <= value <= 65535 else 5555
    if isinstance(value, str) and value.strip().isdigit():
        port = int(value.strip())
        return port if 1 <= port <= 65535 else 5555
    return 5555
