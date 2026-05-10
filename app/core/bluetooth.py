"""Bluetooth control via bluetoothctl."""

import re
import time
from dataclasses import dataclass

from app.utils.commands import run, launch_background
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BluetoothDevice:
    mac: str
    name: str
    connected: bool = False
    paired: bool = True


def get_paired_devices() -> list[BluetoothDevice]:
    """Return all paired Bluetooth devices with live connection state."""
    result = run(["bluetoothctl", "devices", "Paired"])
    devices = []
    for line in result.stdout.splitlines():
        m = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s+(.+)", line.strip())
        if not m:
            continue
        mac, name = m.group(1).upper(), m.group(2)
        devices.append(BluetoothDevice(mac=mac, name=name, connected=is_connected(mac)))
    logger.debug("paired: %s", [d.mac for d in devices])
    return devices


def get_all_known_devices() -> list[BluetoothDevice]:
    """Return all known (paired + cached) devices."""
    result = run(["bluetoothctl", "devices"])
    devices, seen = [], set()
    for line in result.stdout.splitlines():
        m = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s+(.+)", line.strip())
        if not m:
            continue
        mac = m.group(1).upper()
        if mac in seen:
            continue
        seen.add(mac)
        devices.append(BluetoothDevice(mac=mac, name=m.group(2), connected=is_connected(mac)))
    return devices


def get_device_info(mac: str) -> dict:
    """Return a dict of info fields from `bluetoothctl info <mac>`."""
    result = run(["bluetoothctl", "info", mac])
    info: dict = {"mac": mac, "raw": result.stdout}
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("Name:"):
            info["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Alias:"):
            info["alias"] = line.split(":", 1)[1].strip()
        elif line.startswith("Connected:"):
            info["connected"] = "yes" in line
        elif line.startswith("Paired:"):
            info["paired"] = "yes" in line
        elif line.startswith("UUID:"):
            info.setdefault("uuids", []).append(line.split(":", 1)[1].strip())
    return info


def is_connected(mac: str) -> bool:
    """Return True if the device is currently connected."""
    result = run(["bluetoothctl", "info", mac])
    for line in result.stdout.splitlines():
        if "Connected:" in line:
            return "yes" in line
    return False


def connect_device(mac: str) -> tuple[bool, str]:
    """
    Attempt to connect to the BT device.
    Returns (success, message).
    """
    logger.info("Connecting to %s", mac)
    result = run(["bluetoothctl", "connect", mac], timeout=20)
    if "Connection successful" in result.stdout:
        return True, "Connexion réussie ✓"
    if "Failed to connect" in result.stdout or not result.ok:
        err = (result.stderr or result.stdout or "Erreur inconnue").strip()[:200]
        return False, f"Échec de connexion : {err}"
    return True, "Commande de connexion envoyée"


def scan_start(duration: int = 6) -> bool:
    """Scan for BT devices for `duration` seconds (blocking — run in thread)."""
    logger.info("BT scan start (%ds)", duration)
    run(["bluetoothctl", "scan", "on"])
    time.sleep(duration)
    run(["bluetoothctl", "scan", "off"])
    return True


def open_bluetooth_settings() -> None:
    launch_background(["gnome-control-center", "bluetooth"])
