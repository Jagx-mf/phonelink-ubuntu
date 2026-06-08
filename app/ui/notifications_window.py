"""Fenêtre « Notifications Android » pour PhoneLink Ubuntu (V0.8).

Lecture seule, proche de l'idée Microsoft Phone Link : liste des notifications
Android actives (application, titre, texte, heure). Aucune réponse, aucune
action ``RemoteInput``.

Le chargement se fait dans un thread d'arrière-plan (le backend réel fait du
HTTP) et le résultat repasse par ``GLib.idle_add`` pour ne jamais bloquer le
thread GTK. Si le téléphone n'est pas connecté ou le token invalide, un message
clair est affiché plutôt qu'une erreur.
"""

from __future__ import annotations

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from app.core import android_bridge
from app.utils.logger import get_logger

logger = get_logger(__name__)


class NotificationsWindow(Gtk.Window):
    """Liste en lecture seule des notifications Android actives."""

    def __init__(self, parent: Gtk.Window):
        super().__init__(transient_for=parent, modal=False)
        self.set_title("Notifications Android")
        self.set_default_size(460, 640)

        # Compteur de génération : un chargement async obsolète est ignoré si un
        # rafraîchissement plus récent s'est terminé entre-temps.
        self._load_seq = 0

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(outer)

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        title = Gtk.Label(label="Notifications Android")
        title.add_css_class("title")
        header.set_title_widget(title)

        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Rafraîchir les notifications")
        refresh_btn.connect("clicked", lambda _b: self._reload())
        header.pack_end(refresh_btn)
        outer.append(header)

        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_vexpand(True)
        outer.append(self._scroll)

        self._list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._list.set_margin_top(12)
        self._list.set_margin_bottom(12)
        self._list.set_margin_start(12)
        self._list.set_margin_end(12)
        self._scroll.set_child(self._list)

        self._reload()

    # ── API publique (temps réel V0.9) ───────────────

    def reload_async(self) -> None:
        """Recharge la liste des notifications (déclenché par un événement
        ``notification_changed``). Sûr à appeler à répétition : le compteur de
        génération interne ignore les chargements obsolètes."""
        self._reload()

    # ── chargement (thread + GLib.idle_add) ──────────

    def _reload(self) -> None:
        self._load_seq += 1
        seq = self._load_seq
        self._render_message("Chargement…")

        def worker() -> None:
            try:
                notifications = android_bridge.list_notifications()
                err: Exception | None = None
            except Exception as exc:  # transport : ne jamais crasher l'UI
                notifications, err = [], exc
            GLib.idle_add(self._on_loaded, seq, notifications, err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_loaded(
        self,
        seq: int,
        notifications: list,
        err: Exception | None,
    ) -> bool:
        if seq != self._load_seq:
            return False  # un rafraîchissement plus récent a pris le relais
        if err is not None:
            logger.warning("Notifications: chargement échoué: %s", err)
            self._render_message(
                "Impossible de récupérer les notifications.\n\n"
                "Vérifiez que le téléphone est connecté, que l'app compagnon "
                "est appairée et que l'accès aux notifications est accordé."
            )
            return False
        logger.info("Notifications: %d notification(s) chargée(s)", len(notifications))
        if not notifications:
            self._render_message(
                "Aucune notification active.\n\n"
                "Les notifications Android récentes apparaîtront ici."
            )
            return False
        self._render_notifications(notifications)
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
        lbl = Gtk.Label(label=text)
        lbl.set_wrap(True)
        lbl.set_justify(Gtk.Justification.CENTER)
        lbl.set_margin_top(24)
        lbl.add_css_class("dim-label")
        self._list.append(lbl)

    def _render_notifications(self, notifications: list) -> None:
        self._clear()
        for notif in notifications:
            self._list.append(self._notification_card(notif))

    def _notification_card(self, notif) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.set_margin_top(8)
        card.set_margin_bottom(8)
        card.set_margin_start(10)
        card.set_margin_end(10)
        card.add_css_class("card")

        # Ligne du haut : application + heure.
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        app_lbl = Gtk.Label(label=notif.app_name or notif.package or "Application")
        app_lbl.set_xalign(0)
        app_lbl.set_hexpand(True)
        app_lbl.set_ellipsize(3)  # Pango.EllipsizeMode.END
        app_lbl.add_css_class("caption-heading")
        top.append(app_lbl)
        if notif.timestamp is not None:
            time_lbl = Gtk.Label(label=_fmt_time(notif.timestamp))
            time_lbl.set_xalign(1)
            time_lbl.add_css_class("dim-label")
            time_lbl.add_css_class("caption")
            top.append(time_lbl)
        card.append(top)

        if notif.title:
            title_lbl = Gtk.Label(label=notif.title)
            title_lbl.set_xalign(0)
            title_lbl.set_wrap(True)
            title_lbl.add_css_class("heading")
            card.append(title_lbl)

        body = notif.big_text or notif.text
        if body:
            body_lbl = Gtk.Label(label=body)
            body_lbl.set_xalign(0)
            body_lbl.set_wrap(True)
            card.append(body_lbl)

        return card


def _fmt_time(ts: datetime) -> str:
    """Heure courte : 'HH:MM' aujourd'hui, sinon 'JJ/MM HH:MM'."""
    now = datetime.now()
    if ts.date() == now.date():
        return ts.strftime("%H:%M")
    return ts.strftime("%d/%m %H:%M")
