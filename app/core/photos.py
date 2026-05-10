"""Photo import from phone via ADB."""

from pathlib import Path

from app.core.adb import pull_photos
from app.utils.commands import run, launch_background
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _get_pictures_dir() -> Path:
    """Return XDG Pictures directory, fallback to ~/Images."""
    result = run(["xdg-user-dir", "PICTURES"])
    if result.ok and result.output:
        return Path(result.output)
    return Path.home() / "Images"


def get_import_folder() -> Path:
    """Return the PhoneLinkUbuntu photo import folder path."""
    return _get_pictures_dir() / "PhoneLinkUbuntu"


def import_photos() -> tuple[bool, str]:
    """Import photos from the phone (blocking — run in thread)."""
    dest = get_import_folder()
    logger.info("Importing photos → %s", dest)
    return pull_photos(dest)


def open_local_folder() -> tuple[bool, str]:
    """Open the import folder in the file manager."""
    folder = get_import_folder()
    folder.mkdir(parents=True, exist_ok=True)
    proc = launch_background(["xdg-open", str(folder)])
    if proc is not None:
        return True, f"Ouverture de {folder}"
    return False, f"Impossible d'ouvrir {folder}"
