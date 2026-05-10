"""ADB device management."""

from pathlib import Path
from typing import Optional

from app.utils.commands import run
from app.utils.logger import get_logger

logger = get_logger(__name__)


def get_connected_devices() -> list[dict]:
    """Return list of ADB devices as dicts with 'serial' and 'state'."""
    result = run(["adb", "devices"])
    devices = []
    for line in result.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 2:
            devices.append({"serial": parts[0], "state": parts[1]})
    logger.debug("adb devices: %s", devices)
    return devices


def is_device_connected() -> bool:
    """Return True if at least one authorized ADB device is connected."""
    return any(d["state"] == "device" for d in get_connected_devices())


def get_first_device_serial() -> Optional[str]:
    """Return serial of first authorized ADB device, or None."""
    for d in get_connected_devices():
        if d["state"] == "device":
            return d["serial"]
    return None


def pull_photos(dest: Path) -> tuple[bool, str]:
    """
    Pull /sdcard/DCIM/Camera to dest (blocking — run in thread).
    Returns (success, message).
    """
    dest.mkdir(parents=True, exist_ok=True)
    logger.info("adb pull → %s", dest)
    result = run(["adb", "pull", "/sdcard/DCIM/Camera", str(dest)], timeout=300)
    if result.ok:
        return True, f"Photos importées dans {dest}"
    return False, f"Erreur ADB : {(result.error or result.output)[:300]}"


def get_device_model() -> Optional[str]:
    """Return the device model string, or None."""
    result = run(["adb", "shell", "getprop", "ro.product.model"])
    return result.output or None if result.ok else None
