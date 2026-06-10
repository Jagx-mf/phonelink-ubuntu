#!/usr/bin/env bash
# Désinstallation locale du lanceur PhoneLink Ubuntu (l'inverse exact de
# install-desktop-launcher.sh). Ne touche pas au dépôt ni à la configuration
# (~/.config/phonelink-ubuntu) ni aux données téléchargées.
set -euo pipefail

LAUNCHER="${HOME}/.local/bin/phonelink-ubuntu"
DESKTOP="${HOME}/.local/share/applications/phonelink-ubuntu.desktop"
ICON="${HOME}/.local/share/icons/hicolor/scalable/apps/phonelink-ubuntu.svg"

removed=0
for f in "${LAUNCHER}" "${DESKTOP}" "${ICON}"; do
    if [ -e "${f}" ] || [ -L "${f}" ]; then
        rm -f "${f}"
        echo "Supprimé : ${f}"
        removed=1
    fi
done

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${HOME}/.local/share/applications" || true
fi

if [ "${removed}" -eq 0 ]; then
    echo "Rien à désinstaller (lanceur non installé)."
else
    echo "PhoneLink Ubuntu désinstallé du menu Applications."
fi
