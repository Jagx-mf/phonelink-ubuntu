"""System dependency checker."""

from dataclasses import dataclass

from app.utils.commands import run, is_installed
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ToolStatus:
    name: str
    label: str
    installed: bool
    active: bool = False
    version: str = ""
    note: str = ""


def check_all() -> dict[str, ToolStatus]:
    """
    Check all required tools and services.
    Returns a dict keyed by tool name.
    """
    results: dict[str, ToolStatus] = {}

    tools = [
        ("bluetoothctl", "bluetoothctl"),
        ("pactl", "pactl (PipeWire/PulseAudio)"),
        ("wpctl", "wpctl (WirePlumber)"),
        ("pavucontrol", "pavucontrol"),
        ("adb", "ADB (Android Debug Bridge)"),
        ("scrcpy", "scrcpy"),
        ("xdg-open", "xdg-open"),
        ("gnome-control-center", "gnome-control-center"),
    ]

    for name, label in tools:
        installed = is_installed(name)
        version = _get_version(name) if installed else ""
        results[name] = ToolStatus(name=name, label=label, installed=installed, version=version)

    # Bluetooth service via systemd
    bt_result = run(["systemctl", "is-active", "bluetooth"])
    bt_active = bt_result.output == "active"
    results["bluetooth_service"] = ToolStatus(
        name="bluetooth_service",
        label="Service Bluetooth (systemd)",
        installed=True,
        active=bt_active,
        note="active" if bt_active else bt_result.output,
    )

    logger.debug("check_all: %s", {k: v.installed for k, v in results.items()})
    return results


def _get_version(name: str) -> str:
    """Try to retrieve a short version string for a tool."""
    try:
        result = run([name, "--version"], timeout=3)
        first_line = (result.stdout or result.stderr).strip().split("\n")[0]
        return first_line[:60]
    except Exception:
        return ""
