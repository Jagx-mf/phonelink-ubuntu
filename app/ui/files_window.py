"""Fenêtre « Fichiers Android » pour PhoneLink Ubuntu (V1.0, Phase 1).

Explorateur des dossiers publics du téléphone (Download, DCIM, Pictures,
Movies, Music, Documents) via les endpoints ``/v1/files/*`` de l'app compagnon :

* navigation racines → dossiers → sous-dossiers, bouton retour parent ;
* téléchargement d'un fichier vers ``~/Téléchargements/PhoneLinkUbuntu`` ;
* envoi d'un fichier Ubuntu vers le dossier Android affiché ;
* nouveau dossier, renommage, suppression (avec confirmation).

Tout accès réseau passe par un thread d'arrière-plan + ``GLib.idle_add`` :
le thread GTK n'est jamais bloqué. Les erreurs (permission « Tous les
fichiers » manquante, téléphone déconnecté, chemin refusé…) s'affichent en
message clair, jamais en crash.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from app.core import android_bridge
from app.core import files as files_core
from app.ui.widgets import show_dialog
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Icônes GTK par grande famille MIME (repli : fichier générique).
_MIME_ICONS = (
    ("image/", "image-x-generic-symbolic"),
    ("video/", "video-x-generic-symbolic"),
    ("audio/", "audio-x-generic-symbolic"),
    ("text/", "text-x-generic-symbolic"),
    ("application/pdf", "x-office-document-symbolic"),
)


class FilesWindow(Gtk.Window):
    """Explorateur de fichiers Android (lecture + opérations de base)."""

    def __init__(self, parent: Gtk.Window):
        super().__init__(transient_for=parent, modal=False)
        self.set_title("Fichiers Android")
        self.set_default_size(720, 640)

        #: Dossier affiché (None = liste des racines).
        self._path: Optional[str] = None
        #: Chemin du parent du dossier courant ("" = revenir aux racines).
        self._parent: str = ""
        #: Compteur de génération : ignore les chargements obsolètes.
        self._load_seq = 0
        #: True pendant une opération d'écriture (désactive les boutons).
        self._busy = False

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(outer)

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        title = Gtk.Label(label="Fichiers Android")
        title.add_css_class("title")
        header.set_title_widget(title)

        self._back_btn = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        self._back_btn.set_tooltip_text("Dossier parent")
        self._back_btn.set_sensitive(False)
        self._back_btn.connect("clicked", self._on_back)
        header.pack_start(self._back_btn)

        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Rafraîchir")
        refresh_btn.connect("clicked", lambda _b: self._reload())
        header.pack_end(refresh_btn)

        local_btn = Gtk.Button.new_from_icon_name("folder-download-symbolic")
        local_btn.set_tooltip_text(
            "Ouvrir le dossier local des téléchargements (PhoneLinkUbuntu)"
        )
        local_btn.connect("clicked", self._on_open_local)
        header.pack_end(local_btn)

        outer.append(header)

        self._path_label = Gtk.Label(label="Racines du téléphone")
        self._path_label.set_xalign(0)
        self._path_label.set_ellipsize(3)  # Pango.EllipsizeMode.END
        self._path_label.add_css_class("dim-label")
        self._path_label.set_margin_top(8)
        self._path_label.set_margin_start(12)
        self._path_label.set_margin_end(12)
        outer.append(self._path_label)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        outer.append(scroll)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        # Un simple clic doit SÉLECTIONNER (y compris un dossier, pour pouvoir
        # le renommer/supprimer) ; l'activation (= entrer dans le dossier) se
        # fait au double-clic, via Entrée ou le bouton « Ouvrir ». Sans cela,
        # le défaut GTK (activation au simple clic) naviguait immédiatement et
        # rendait les dossiers insélectionnables.
        self._list.set_activate_on_single_click(False)
        self._list.add_css_class("boxed-list")
        self._list.set_margin_top(8)
        self._list.set_margin_bottom(8)
        self._list.set_margin_start(12)
        self._list.set_margin_end(12)
        self._list.connect("row-activated", self._on_row_activated)
        self._list.connect("row-selected", self._on_row_selected)
        scroll.set_child(self._list)

        outer.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        outer.append(self._build_action_bar())

        self._status = Gtk.Label(label="")
        self._status.set_xalign(0)
        self._status.set_wrap(True)
        self._status.add_css_class("dim-label")
        self._status.set_margin_top(4)
        self._status.set_margin_bottom(8)
        self._status.set_margin_start(12)
        self._status.set_margin_end(12)
        outer.append(self._status)

        self._reload()

    # ── barre d'actions ──────────────────────────────

    def _build_action_bar(self) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.set_margin_top(8)
        bar.set_margin_bottom(4)
        bar.set_margin_start(12)
        bar.set_margin_end(12)

        self._open_btn = Gtk.Button(label="Ouvrir")
        self._open_btn.set_tooltip_text(
            "Entrer dans le dossier sélectionné (ou double-clic)"
        )
        self._open_btn.connect("clicked", self._on_open_selected)
        bar.append(self._open_btn)

        self._download_btn = Gtk.Button(label="Télécharger")
        self._download_btn.set_tooltip_text(
            "Copier le fichier sélectionné vers le dossier PhoneLinkUbuntu"
        )
        self._download_btn.add_css_class("suggested-action")
        self._download_btn.connect("clicked", self._on_download)
        bar.append(self._download_btn)

        self._upload_btn = Gtk.Button(label="Envoyer un fichier…")
        self._upload_btn.set_tooltip_text("Copier un fichier Ubuntu dans ce dossier")
        self._upload_btn.connect("clicked", self._on_upload)
        bar.append(self._upload_btn)

        self._mkdir_btn = Gtk.Button(label="Nouveau dossier")
        self._mkdir_btn.connect("clicked", self._on_mkdir)
        bar.append(self._mkdir_btn)

        self._rename_btn = Gtk.Button(label="Renommer")
        self._rename_btn.connect("clicked", self._on_rename)
        bar.append(self._rename_btn)

        self._delete_btn = Gtk.Button(label="Supprimer")
        self._delete_btn.add_css_class("destructive-action")
        self._delete_btn.connect("clicked", self._on_delete)
        bar.append(self._delete_btn)

        self._update_buttons()
        return bar

    def _update_buttons(self) -> None:
        """Active/désactive les boutons selon la vue, la sélection et _busy."""
        in_dir = self._path is not None
        entry = self._selected_entry()
        writable = in_dir and not self._busy
        self._upload_btn.set_sensitive(writable)
        self._mkdir_btn.set_sensitive(writable)
        self._open_btn.set_sensitive(
            not self._busy and entry is not None and entry.is_dir
        )
        # Télécharger : fichiers seulement (pas de téléchargement récursif de
        # dossier pour l'instant).
        self._download_btn.set_sensitive(
            not self._busy and entry is not None and not entry.is_dir
        )
        self._rename_btn.set_sensitive(writable and entry is not None)
        self._delete_btn.set_sensitive(writable and entry is not None)

    def _selected_entry(self) -> Optional["android_bridge.AndroidFileEntry"]:
        row = self._list.get_selected_row()
        return getattr(row, "_entry", None) if row is not None else None

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self._status.set_text(message)
        self._update_buttons()

    # ── navigation ───────────────────────────────────

    def _on_back(self, _btn: Gtk.Button) -> None:
        if self._path is None:
            return
        # parent vide = racine d'un dossier autorisé → retour aux racines.
        self._navigate(self._parent or None)

    def _on_row_activated(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        """Double-clic ou Entrée sur un dossier : on y entre."""
        entry = getattr(row, "_entry", None)
        if entry is not None and entry.is_dir:
            self._navigate(entry.path)

    def _on_open_selected(self, _btn: Gtk.Button) -> None:
        """Bouton « Ouvrir » : entre dans le dossier sélectionné."""
        entry = self._selected_entry()
        if entry is not None and entry.is_dir:
            self._navigate(entry.path)

    def _on_row_selected(self, _list: Gtk.ListBox, _row) -> None:
        self._update_buttons()

    def _navigate(self, path: Optional[str]) -> None:
        self._path = path
        self._reload()

    def _reload(self) -> None:
        """(Re)charge la vue courante (racines ou dossier) en arrière-plan."""
        self._load_seq += 1
        seq = self._load_seq
        path = self._path
        self._render_message("Chargement…")
        self._back_btn.set_sensitive(path is not None)
        self._path_label.set_text(path or "Racines du téléphone")

        def worker() -> None:
            try:
                if path is None:
                    roots = android_bridge.list_file_roots()
                    listing = android_bridge.AndroidFileListing(
                        path="", parent="", items=roots
                    )
                else:
                    listing = android_bridge.list_files(path)
                err: Exception | None = None
            except Exception as exc:  # transport : jamais de crash UI
                listing, err = None, exc
            GLib.idle_add(self._on_loaded, seq, listing, err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_loaded(self, seq: int, listing, err: Exception | None) -> bool:
        if seq != self._load_seq:
            return False  # navigation plus récente entre-temps
        if err is not None:
            logger.warning("Fichiers: chargement échoué: %s", err)
            self._render_message(_friendly_error(err))
            return False
        self._parent = listing.parent
        if not listing.items:
            self._render_message(
                "Dossier vide." if self._path else
                "Aucune racine disponible.\n\nVérifiez que le téléphone est "
                "appairé et que l'accès aux fichiers est accordé dans l'app "
                "PhoneLink Companion."
            )
            return False
        self._render_entries(listing.items)
        return False  # one-shot

    # ── rendu ────────────────────────────────────────

    def _clear(self) -> None:
        child = self._list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._list.remove(child)
            child = nxt

    def _render_message(self, text: str) -> None:
        self._clear()
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        lbl = Gtk.Label(label=text)
        lbl.set_wrap(True)
        lbl.set_justify(Gtk.Justification.CENTER)
        lbl.set_margin_top(24)
        lbl.set_margin_bottom(24)
        lbl.add_css_class("dim-label")
        row.set_child(lbl)
        self._list.append(row)
        self._update_buttons()

    def _render_entries(self, entries: list) -> None:
        self._clear()
        for entry in entries:
            self._list.append(self._entry_row(entry))
        self._status.set_text(f"{len(entries)} élément(s)")
        self._update_buttons()

    def _entry_row(self, entry) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row._entry = entry  # relu par la sélection/activation

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(8)
        box.set_margin_end(8)

        box.append(Gtk.Image.new_from_icon_name(_icon_for(entry)))

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        col.set_hexpand(True)
        name = Gtk.Label(label=entry.name)
        name.set_xalign(0)
        name.set_ellipsize(3)  # END
        col.append(name)

        details: list[str] = []
        if entry.is_dir:
            details.append("Dossier")
        else:
            if entry.size:
                details.append(files_core.format_size(entry.size))
            if entry.mime:
                details.append(entry.mime)
        if entry.modified is not None:
            details.append(_fmt_time(entry.modified))
        if details:
            sub = Gtk.Label(label="  ·  ".join(details))
            sub.set_xalign(0)
            sub.add_css_class("dim-label")
            sub.add_css_class("caption")
            col.append(sub)
        box.append(col)

        if entry.is_dir:
            box.append(Gtk.Image.new_from_icon_name("go-next-symbolic"))

        row.set_child(box)
        return row

    # ── opérations (threads + idle_add) ──────────────

    def _run_operation(
        self,
        busy_message: str,
        operation: Callable[[], str],
        reload_after: bool = True,
    ) -> None:
        """Exécute une opération bridge en arrière-plan avec gestion d'erreur.

        ``operation`` renvoie le message de succès à afficher ; toute exception
        est convertie en dialogue d'erreur lisible.
        """
        self._set_busy(True, busy_message)

        def worker() -> None:
            try:
                message = operation()
                err: Exception | None = None
            except Exception as exc:
                message, err = "", exc
            GLib.idle_add(on_done, message, err)

        def on_done(message: str, err: Exception | None) -> bool:
            self._set_busy(False, message if err is None else "")
            if err is not None:
                logger.warning("Fichiers: opération échouée: %s", err)
                show_dialog(self, "Fichiers Android", _friendly_error(err), error=True)
            elif reload_after:
                self._reload()
            return False  # one-shot

        threading.Thread(target=worker, daemon=True).start()

    def _on_download(self, _btn: Gtk.Button) -> None:
        entry = self._selected_entry()
        if entry is None or entry.is_dir:
            return
        dest = files_core.unique_local_path(entry.name)

        def operation() -> str:
            android_bridge.download_file(entry.path, str(dest))
            return f"Téléchargé : {dest}"

        self._run_operation(
            f"Téléchargement de {entry.name}…", operation, reload_after=False
        )

    def _on_upload(self, _btn: Gtk.Button) -> None:
        if self._path is None:
            return
        remote_dir = self._path

        def on_picked(local_path: str) -> None:
            def operation() -> str:
                android_bridge.upload_file(local_path, remote_dir)
                return f"Envoyé vers le téléphone : {local_path}"

            self._run_operation("Envoi du fichier vers le téléphone…", operation)

        self._pick_local_file(on_picked)

    def _pick_local_file(self, callback: Callable[[str], None]) -> None:
        """Sélecteur de fichier local (Gtk.FileDialog, repli FileChooserNative)."""
        if hasattr(Gtk, "FileDialog"):
            dialog = Gtk.FileDialog()
            dialog.set_title("Fichier à envoyer vers le téléphone")

            def on_open(dlg, res) -> None:
                try:
                    gfile = dlg.open_finish(res)
                except GLib.Error:
                    return  # annulé
                path = gfile.get_path() if gfile is not None else None
                if path:
                    callback(path)

            dialog.open(self, None, on_open)
            return

        chooser = Gtk.FileChooserNative.new(
            "Fichier à envoyer vers le téléphone", self,
            Gtk.FileChooserAction.OPEN, "Envoyer", "Annuler",
        )

        def on_response(dlg, response) -> None:
            if response == Gtk.ResponseType.ACCEPT:
                gfile = dlg.get_file()
                path = gfile.get_path() if gfile is not None else None
                if path:
                    callback(path)
            dlg.destroy()

        chooser.connect("response", on_response)
        chooser.show()

    def _on_mkdir(self, _btn: Gtk.Button) -> None:
        if self._path is None:
            return
        parent = self._path

        def on_name(name: str) -> None:
            def operation() -> str:
                android_bridge.make_dir(parent, name)
                return f"Dossier créé : {name}"

            self._run_operation("Création du dossier…", operation)

        self._prompt_text("Nouveau dossier", "Nom du dossier :", "", on_name)

    def _on_rename(self, _btn: Gtk.Button) -> None:
        entry = self._selected_entry()
        if entry is None:
            return

        def on_name(name: str) -> None:
            if name == entry.name:
                return

            def operation() -> str:
                android_bridge.rename_path(entry.path, name)
                return f"Renommé en : {name}"

            self._run_operation("Renommage…", operation)

        self._prompt_text("Renommer", "Nouveau nom :", entry.name, on_name)

    def _on_delete(self, _btn: Gtk.Button) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        kind = "le dossier (et tout son contenu)" if entry.is_dir else "le fichier"
        dialog = Gtk.AlertDialog()
        dialog.set_modal(True)
        dialog.set_message(f"Supprimer « {entry.name} » ?")
        dialog.set_detail(
            f"Cette action supprime définitivement {kind} sur le téléphone."
        )
        dialog.set_buttons(["Annuler", "Supprimer"])
        dialog.set_cancel_button(0)
        dialog.set_default_button(0)

        def on_response(dlg: Gtk.AlertDialog, res) -> None:
            try:
                choice = dlg.choose_finish(res)
            except GLib.Error:
                return  # fermé/annulé
            if choice != 1:
                return

            def operation() -> str:
                android_bridge.delete_path(entry.path)
                return f"Supprimé : {entry.name}"

            self._run_operation("Suppression…", operation)

        dialog.choose(self, None, on_response)

    def _on_open_local(self, _btn: Gtk.Button) -> None:
        ok, msg = files_core.open_download_folder()
        if not ok:
            show_dialog(self, "Fichiers Android", msg, error=True)

    # ── petites boîtes de dialogue ───────────────────

    def _prompt_text(
        self,
        title: str,
        label: str,
        initial: str,
        callback: Callable[[str], None],
    ) -> None:
        """Petite fenêtre modale : un champ texte + Valider/Annuler."""
        win = Gtk.Window(title=title, transient_for=self, modal=True)
        win.set_default_size(360, -1)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)

        lbl = Gtk.Label(label=label)
        lbl.set_xalign(0)
        box.append(lbl)

        entry = Gtk.Entry()
        entry.set_text(initial)
        box.append(entry)

        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btns.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label="Annuler")
        cancel.connect("clicked", lambda _b: win.destroy())
        ok_btn = Gtk.Button(label="Valider")
        ok_btn.add_css_class("suggested-action")
        btns.append(cancel)
        btns.append(ok_btn)
        box.append(btns)
        win.set_child(box)

        def submit(_w=None) -> None:
            text = entry.get_text().strip()
            if not text or "/" in text:
                return  # nom invalide : on attend une correction
            win.destroy()
            callback(text)

        ok_btn.connect("clicked", submit)
        entry.connect("activate", submit)
        win.present()


# ──────────────────────────────────────────────
# Helpers module
# ──────────────────────────────────────────────


def _icon_for(entry) -> str:
    if entry.is_dir:
        return "folder-symbolic"
    for prefix, icon in _MIME_ICONS:
        if entry.mime.startswith(prefix):
            return icon
    return "text-x-generic-symbolic"


def _friendly_error(exc: Exception) -> str:
    """Message clair selon le type d'échec (permission, connexion, refus)."""
    text = str(exc)
    status = getattr(exc, "status", None)
    if "files_permission_missing" in text:
        return (
            "Accès aux fichiers non accordé sur le téléphone.\n\n"
            "Ouvrez l'app PhoneLink Companion et touchez « Autoriser l'accès "
            "aux fichiers » (Android 11+ : réglage « Accès à tous les "
            "fichiers »)."
        )
    if status in (401, 403):
        return (
            "Accès refusé (token invalide ou permission manquante).\n"
            "Ré-appairez l'app compagnon depuis la fenêtre principale."
        )
    if status is None and "démo" not in text:
        return (
            "Téléphone injoignable.\n\n"
            "Vérifiez que l'app PhoneLink Companion tourne et que la "
            f"connexion est active.\n\nDétail : {text}"
        )
    return text


def _fmt_time(ts: datetime) -> str:
    now = datetime.now()
    if ts.date() == now.date():
        return ts.strftime("%H:%M")
    return ts.strftime("%d/%m/%Y %H:%M")
