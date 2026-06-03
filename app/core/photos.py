"""Photo import from phone via ADB."""

from pathlib import Path

from app.core.adb import pull_photos
from app.utils.commands import run, launch_background
from app.utils.logger import get_logger

logger = get_logger(__name__)

IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif"}
)


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


def list_photos() -> list[Path]:
    """Return image files in the import folder (recursively), newest first.

    `adb pull /sdcard/DCIM/Camera` drops files into a ``Camera/`` subfolder, so a
    recursive scan is required to find them.
    """
    folder = get_import_folder()
    if not folder.is_dir():
        return []
    photos = [
        p for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]
    photos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return photos


def open_photo(path: Path) -> tuple[bool, str]:
    """Open a single imported photo via xdg-open (no shell)."""
    folder = get_import_folder().resolve()
    try:
        resolved = path.resolve()
        resolved.relative_to(folder)
    except (OSError, ValueError):
        logger.warning("Refused to open photo outside import folder: %s", path)
        return False, "Fichier hors du dossier d'import"
    if not resolved.is_file():
        return False, f"Fichier introuvable : {resolved.name}"
    proc = launch_background(["xdg-open", str(resolved)])
    if proc is not None:
        return True, f"Ouverture de {resolved.name}"
    return False, f"Impossible d'ouvrir {resolved.name}"
