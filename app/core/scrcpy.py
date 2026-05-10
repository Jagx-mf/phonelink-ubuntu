"""scrcpy launcher."""

import subprocess
from typing import Optional

from app.utils.commands import is_installed, launch_background
from app.utils.logger import get_logger

logger = get_logger(__name__)

_scrcpy_proc: Optional[subprocess.Popen] = None


def is_scrcpy_installed() -> bool:
    return is_installed("scrcpy")


def launch(extra_args: Optional[list[str]] = None) -> tuple[bool, str]:
    """
    Launch scrcpy in background after verifying ADB connectivity.
    Returns (success, message).
    """
    global _scrcpy_proc

    if not is_scrcpy_installed():
        return False, (
            "scrcpy n'est pas installé.\n"
            "Installez-le : sudo apt install scrcpy"
        )

    from app.core.adb import is_device_connected
    if not is_device_connected():
        return False, (
            "Aucun appareil ADB connecté.\n\n"
            "• Activez le débogage USB sur le téléphone\n"
            "  (Paramètres → Options développeurs → Débogage USB)\n"
            "• Connectez le téléphone via USB\n"
            "• Acceptez la demande de confiance ADB sur le téléphone"
        )

    # Kill previous instance if still alive
    if _scrcpy_proc and _scrcpy_proc.poll() is None:
        logger.info("Terminating previous scrcpy (pid=%d)", _scrcpy_proc.pid)
        _scrcpy_proc.terminate()

    cmd = ["scrcpy", "--stay-awake"]
    if extra_args:
        cmd.extend(extra_args)

    proc = launch_background(cmd)
    if proc is None:
        return False, "Impossible de lancer scrcpy (commande introuvable)"

    _scrcpy_proc = proc
    return True, f"scrcpy lancé (pid {proc.pid})"


def is_running() -> bool:
    """Return True if the scrcpy process we launched is still alive."""
    return _scrcpy_proc is not None and _scrcpy_proc.poll() is None
