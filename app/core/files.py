"""Explorateur de fichiers Android — helpers côté Ubuntu (V1.0, Phase 1).

Le transport (endpoints ``/v1/files/*``) vit dans :mod:`app.core.android_bridge` ;
ce module porte la logique purement locale :

* dossier de destination des téléchargements (XDG ``DOWNLOAD`` →
  ``~/Téléchargements/PhoneLinkUbuntu`` ou ``~/Downloads/PhoneLinkUbuntu``) ;
* nom de fichier local sans collision (suffixe ``(1)``, ``(2)``, …) ;
* formatage lisible des tailles.

Aucune dépendance hors stdlib (le projet n'en utilise aucune).
"""

from __future__ import annotations

from pathlib import Path

from app.utils.commands import run, launch_background
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _get_downloads_dir() -> Path:
    """Dossier Téléchargements XDG, repli sur ~/Téléchargements puis ~/Downloads."""
    result = run(["xdg-user-dir", "DOWNLOAD"])
    if result.ok and result.output:
        return Path(result.output)
    for candidate in (Path.home() / "Téléchargements", Path.home() / "Downloads"):
        if candidate.is_dir():
            return candidate
    return Path.home() / "Downloads"


def get_download_folder() -> Path:
    """Dossier local des fichiers reçus du téléphone (créé si nécessaire)."""
    folder = _get_downloads_dir() / "PhoneLinkUbuntu"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def unique_local_path(name: str) -> Path:
    """Chemin local libre dans le dossier de téléchargement.

    ``photo.jpg`` → ``photo.jpg`` puis ``photo (1).jpg``, ``photo (2).jpg``…
    si le nom est déjà pris (on n'écrase jamais un fichier local).
    """
    folder = get_download_folder()
    base = Path(name).name or "fichier"  # jamais de chemin, juste le nom
    candidate = folder / base
    if not candidate.exists():
        return candidate
    stem, suffix = Path(base).stem, Path(base).suffix
    for i in range(1, 1000):
        candidate = folder / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
    raise OSError(f"Impossible de trouver un nom libre pour {base}")


def open_download_folder() -> tuple[bool, str]:
    """Ouvre le dossier de téléchargement dans le gestionnaire de fichiers."""
    folder = get_download_folder()
    proc = launch_background(["xdg-open", str(folder)])
    if proc is not None:
        return True, f"Ouverture de {folder}"
    return False, f"Impossible d'ouvrir {folder}"


def format_size(size: int) -> str:
    """Taille lisible : ``182,4 ko``, ``2,3 Mo``, ``1,1 Go``…"""
    if size < 0:
        return ""
    value = float(size)
    for unit in ("octets", "ko", "Mo", "Go", "To"):
        if value < 1000.0 or unit == "To":
            if unit == "octets":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}".replace(".", ",")
        value /= 1000.0
    return f"{int(size)} octets"
