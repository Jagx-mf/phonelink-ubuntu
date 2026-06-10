#!/usr/bin/env bash
# Installation locale (sans sudo) du lanceur PhoneLink Ubuntu :
#  - lien symbolique  ~/.local/bin/phonelink-ubuntu  → scripts/phonelink-ubuntu
#  - fichier desktop  ~/.local/share/applications/phonelink-ubuntu.desktop
#  - icône            ~/.local/share/icons/hicolor/scalable/apps/phonelink-ubuntu.svg
#
# Le lien symbolique (plutôt qu'une copie) garde le lanceur synchronisé avec le
# dépôt. Le champ Exec= du .desktop installé est réécrit avec le chemin ABSOLU
# du lanceur : le menu GNOME n'utilise pas toujours un shell de login, donc
# ~/.local/bin peut être absent de son PATH.
set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
PROJECT_ROOT="$(dirname "$(dirname "${SCRIPT_PATH}")")"

LAUNCHER_SRC="${PROJECT_ROOT}/scripts/phonelink-ubuntu"
DESKTOP_SRC="${PROJECT_ROOT}/packaging/linux/phonelink-ubuntu.desktop"
ICON_SRC="${PROJECT_ROOT}/assets/icons/phonelink-ubuntu.svg"

BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${HOME}/.local/share/applications"
ICONS_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"

LAUNCHER_DEST="${BIN_DIR}/phonelink-ubuntu"
DESKTOP_DEST="${APPS_DIR}/phonelink-ubuntu.desktop"
ICON_DEST="${ICONS_DIR}/phonelink-ubuntu.svg"

for src in "${LAUNCHER_SRC}" "${DESKTOP_SRC}" "${ICON_SRC}"; do
    [ -f "${src}" ] || { echo "Fichier manquant : ${src}" >&2; exit 1; }
done

mkdir -p "${BIN_DIR}" "${APPS_DIR}" "${ICONS_DIR}"

# 1) Lanceur : exécutable dans le dépôt + lien symbolique dans ~/.local/bin.
chmod +x "${LAUNCHER_SRC}"
ln -sfn "${LAUNCHER_SRC}" "${LAUNCHER_DEST}"

# 2) Fichier .desktop : copie avec Exec= réécrit en chemin absolu.
sed "s|^Exec=phonelink-ubuntu|Exec=${LAUNCHER_DEST}|" \
    "${DESKTOP_SRC}" > "${DESKTOP_DEST}"
chmod 644 "${DESKTOP_DEST}"

# 3) Icône.
install -m 644 "${ICON_SRC}" "${ICON_DEST}"

# 4) Rafraîchir les caches du bureau (best-effort).
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${APPS_DIR}" || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -t "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true
fi

echo "PhoneLink Ubuntu installé :"
echo "  lanceur : ${LAUNCHER_DEST} → ${LAUNCHER_SRC}"
echo "  desktop : ${DESKTOP_DEST}"
echo "  icône   : ${ICON_DEST}"
echo
echo "Lancez l'application depuis le menu Applications (« PhoneLink Ubuntu »)"
echo "ou avec la commande : phonelink-ubuntu"
case ":${PATH}:" in
    *":${BIN_DIR}:"*) ;;
    *) echo
       echo "Note : ${BIN_DIR} n'est pas dans votre PATH actuel — la commande"
       echo "fonctionnera après reconnexion (Ubuntu l'ajoute au login), ou"
       echo "immédiatement via : export PATH=\"\${HOME}/.local/bin:\${PATH}\"" ;;
esac
