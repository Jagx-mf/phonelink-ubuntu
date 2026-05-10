"""Audio status detection via pactl (PulseAudio / PipeWire-pulse)."""

from typing import Optional

from app.utils.commands import run, is_installed, launch_background
from app.utils.logger import get_logger

logger = get_logger(__name__)


def get_active_source() -> Optional[str]:
    """Return the name of the default audio source (microphone)."""
    result = run(["pactl", "get-default-source"])
    return result.output or None if result.ok else None


def get_active_sink() -> Optional[str]:
    """Return the name of the default audio sink (speaker/output)."""
    result = run(["pactl", "get-default-sink"])
    return result.output or None if result.ok else None


def get_sources() -> list[dict]:
    """Return all audio sources (name + index)."""
    result = run(["pactl", "list", "short", "sources"])
    sources = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            sources.append({"index": parts[0], "name": parts[1]})
    return sources


def get_sinks() -> list[dict]:
    """Return all audio sinks (name + index)."""
    result = run(["pactl", "list", "short", "sinks"])
    sinks = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            sinks.append({"index": parts[0], "name": parts[1]})
    return sinks


def get_bluetooth_card_profile() -> tuple[Optional[str], Optional[str]]:
    """
    Parse `pactl list cards` and return (card_name, active_profile)
    for the first Bluetooth audio card found.
    Returns (None, None) if no BT card is detected.
    """
    result = run(["pactl", "list", "cards"], timeout=5)
    if not result.ok:
        logger.warning("pactl list cards failed: %s", result.error)
        return None, None

    current_card: Optional[str] = None
    is_bt_card = False

    for line in result.stdout.splitlines():
        stripped = line.strip()

        # New card block
        if stripped.startswith("Card #"):
            current_card = None
            is_bt_card = False
            continue

        if stripped.startswith("Name:"):
            name = stripped.split(":", 1)[1].strip()
            current_card = name
            if "bluez" in name.lower():
                is_bt_card = True

        if is_bt_card and "Active Profile:" in stripped:
            profile = stripped.split("Active Profile:", 1)[1].strip()
            logger.debug("BT card %s active profile: %s", current_card, profile)
            return current_card, profile

    return None, None


def get_bluetooth_profile_type() -> Optional[str]:
    """
    Return 'a2dp', 'hsp_hfp', or None based on the active BT card profile.
    """
    _, profile = get_bluetooth_card_profile()
    if profile is None:
        return None
    pl = profile.lower()
    if "a2dp" in pl:
        return "a2dp"
    if any(x in pl for x in ("hsp", "hfp", "headset")):
        return "hsp_hfp"
    return profile


def open_pavucontrol() -> tuple[bool, str]:
    """Open pavucontrol. Returns (success, message)."""
    if not is_installed("pavucontrol"):
        return False, "pavucontrol n'est pas installé.\nInstallez-le : sudo apt install pavucontrol"
    launch_background(["pavucontrol"])
    return True, "pavucontrol lancé"
