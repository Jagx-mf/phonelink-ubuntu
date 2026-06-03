"""ADB device management."""

from pathlib import Path
from typing import Optional

from app.utils.commands import run
from app.utils.logger import get_logger

logger = get_logger(__name__)


def get_connected_devices() -> list[dict]:
    """Return list of ADB devices as dicts with 'serial' and 'state'.

    Parsing is content-based rather than positional: the header, blank lines and
    daemon messages (``* daemon started …``) are skipped by content, and fields
    are split on any whitespace so a stray ``\\r`` or extra spaces can't make a
    state like ``device`` fail to match.
    """
    result = run(["adb", "devices"])
    devices = []
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith("*") or line.startswith("adb:"):
            continue
        if line.lower().startswith("list of devices"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
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


def enable_tcpip(port: int = 5555) -> tuple[bool, str]:
    """
    Switch the USB-connected device to ADB TCP/IP mode on `port`.
    Requires an ADB device already reachable over USB.
    """
    logger.info("adb tcpip %d", port)
    result = run(["adb", "tcpip", str(port)], timeout=15)
    if result.ok:
        return True, f"ADB TCP/IP activé sur le port {port}"
    return False, f"Erreur ADB tcpip : {(result.error or result.output)[:300]}"


def connect_wifi(host: str, port: int = 5555) -> tuple[bool, str]:
    """Connect to a device over ADB Wi-Fi at host:port."""
    host = (host or "").strip()
    if not host:
        return False, "Adresse IP/hôte manquante"
    target = f"{host}:{port}"
    logger.info("adb connect %s", target)
    result = run(["adb", "connect", target], timeout=15)
    # `adb connect` exits 0 even on failure, so inspect its output.
    out = result.output or result.error
    if result.ok and "connected" in out.lower():
        return True, f"Connecté à {target}"
    return False, f"Échec de connexion à {target} : {out[:300]}"


def disconnect_wifi(host: str | None = None, port: int = 5555) -> tuple[bool, str]:
    """Disconnect one ADB Wi-Fi device (host:port), or all if host is None."""
    if host and host.strip():
        target = f"{host.strip()}:{port}"
        cmd = ["adb", "disconnect", target]
        label = target
    else:
        cmd = ["adb", "disconnect"]
        label = "tous les appareils"
    logger.info("adb disconnect %s", label)
    result = run(cmd, timeout=10)
    if result.ok:
        return True, f"Déconnecté ({label})"
    return False, f"Erreur ADB disconnect : {(result.error or result.output)[:300]}"


def get_device_ip() -> Optional[str]:
    """Return the device's wlan0 IPv4 address, or None if unavailable."""
    result = run(["adb", "shell", "ip", "-f", "inet", "addr", "show", "wlan0"])
    if not result.ok:
        return None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            addr = line.split()[1]  # e.g. "192.168.1.42/24"
            return addr.split("/")[0]
    return None
