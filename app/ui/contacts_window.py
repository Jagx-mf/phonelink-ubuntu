"""Fenêtre « Contacts » pour PhoneLink Ubuntu (V1.0, Phase 2).

Carnet d'adresses Android via ``GET /v1/contacts`` :

* barre de recherche (nom ou numéro, filtrage local instantané) ;
* liste des contacts à gauche, fiche détaillée à droite ;
* par numéro : bouton « SMS » (ouvre la fenêtre Messages préremplie) et
  bouton « Appeler » (ouvre le dialer sur le téléphone via ACTION_DIAL —
  l'appel est confirmé sur le téléphone, jamais lancé à distance).

Le chargement passe par un thread + ``GLib.idle_add`` (pas de blocage GTK).
La recherche filtre la liste déjà chargée (pas d'aller-retour réseau à chaque
frappe) ; le bouton « Rafraîchir » recharge depuis le téléphone.
"""

from __future__ import annotations

import threading
import unicodedata
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from app.core import android_bridge
from app.ui.widgets import show_dialog
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Signature du callback fourni par la fenêtre principale pour ouvrir la
#: fenêtre Messages préremplie : (phone_number, contact_name) -> None.
OpenSmsCallback = Callable[[str, str], None]


class ContactsWindow(Gtk.Window):
    """Liste + fiche des contacts Android, avec actions SMS et appel."""

    def __init__(self, parent: Gtk.Window, open_sms: Optional[OpenSmsCallback] = None):
        super().__init__(transient_for=parent, modal=False)
        self.set_title("Contacts")
        self.set_default_size(820, 620)

        self._open_sms = open_sms
        self._contacts: list[android_bridge.AndroidContact] = []
        self._load_seq = 0

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(outer)

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        title = Gtk.Label(label="Contacts")
        title.add_css_class("title")
        header.set_title_widget(title)

        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Recharger les contacts du téléphone")
        refresh_btn.connect("clicked", lambda _b: self._reload())
        header.pack_end(refresh_btn)
        outer.append(header)

        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Rechercher un nom ou un numéro…")
        self._search.set_margin_top(8)
        self._search.set_margin_start(12)
        self._search.set_margin_end(12)
        self._search.connect("search-changed", lambda _e: self._apply_filter())
        outer.append(self._search)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        paned.set_position(300)
        paned.set_margin_top(8)
        outer.append(paned)

        # ── gauche : liste des contacts ──
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list.add_css_class("navigation-sidebar")
        self._list.connect("row-selected", self._on_selected)
        scroll.set_child(self._list)
        paned.set_start_child(scroll)
        paned.set_resize_start_child(False)

        # ── droite : fiche contact ──
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self._detail.set_margin_top(16)
        self._detail.set_margin_bottom(16)
        self._detail.set_margin_start(16)
        self._detail.set_margin_end(16)
        detail_scroll.set_child(self._detail)
        paned.set_end_child(detail_scroll)

        self._reload()

    # ── chargement ───────────────────────────────────

    def _reload(self) -> None:
        self._load_seq += 1
        seq = self._load_seq
        self._render_list_message("Chargement…")
        self._render_detail_message("")

        def worker() -> None:
            try:
                contacts = android_bridge.list_contacts()
                err: Exception | None = None
            except Exception as exc:  # transport : jamais de crash UI
                contacts, err = [], exc
            GLib.idle_add(self._on_loaded, seq, contacts, err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_loaded(self, seq: int, contacts: list, err: Exception | None) -> bool:
        if seq != self._load_seq:
            return False
        if err is not None:
            logger.warning("Contacts: chargement échoué: %s", err)
            self._render_list_message(_friendly_error(err))
            return False
        logger.info("Contacts: %d contact(s) chargé(s)", len(contacts))
        self._contacts = contacts
        self._apply_filter()
        return False  # one-shot

    def _apply_filter(self) -> None:
        """Filtre local (insensible casse/accents) sur nom et numéros."""
        needle = _normalise(self._search.get_text())
        if needle:
            matches = [
                c for c in self._contacts
                if needle in _normalise(c.display_name)
                or any(needle in _normalise(p) for p in c.phones)
            ]
        else:
            matches = list(self._contacts)

        self._clear(self._list)
        if not matches:
            self._render_list_message(
                "Aucun contact." if not self._contacts else "Aucun résultat."
            )
            return
        for contact in matches:
            self._list.append(self._contact_row(contact))
        first = self._list.get_row_at_index(0)
        if first is not None:
            self._list.select_row(first)

    # ── rendu liste ──────────────────────────────────

    def _contact_row(self, contact) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row._contact = contact

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)

        name = Gtk.Label(label=contact.display_name or "(sans nom)")
        name.set_xalign(0)
        name.set_ellipsize(3)  # END
        name.add_css_class("heading")
        box.append(name)

        if contact.phones:
            sub = Gtk.Label(label=contact.phones[0])
            sub.set_xalign(0)
            sub.set_ellipsize(3)
            sub.add_css_class("dim-label")
            sub.add_css_class("caption")
            box.append(sub)

        row.set_child(box)
        return row

    def _render_list_message(self, text: str) -> None:
        self._clear(self._list)
        if not text:
            return
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

    # ── fiche contact ────────────────────────────────

    def _on_selected(self, _list: Gtk.ListBox, row) -> None:
        contact = getattr(row, "_contact", None) if row is not None else None
        if contact is None:
            self._render_detail_message("Sélectionnez un contact.")
            return
        self._render_detail(contact)

    def _render_detail_message(self, text: str) -> None:
        self._clear(self._detail)
        if not text:
            return
        lbl = Gtk.Label(label=text)
        lbl.set_wrap(True)
        lbl.add_css_class("dim-label")
        lbl.set_margin_top(24)
        self._detail.append(lbl)

    def _render_detail(self, contact) -> None:
        self._clear(self._detail)

        name = Gtk.Label(label=contact.display_name or "(sans nom)")
        name.set_xalign(0)
        name.set_wrap(True)
        name.add_css_class("title-2")
        self._detail.append(name)

        if not contact.phones:
            self._render_no_phone()
        for phone in contact.phones:
            self._detail.append(self._phone_row(contact, phone))

        if contact.emails:
            email_title = Gtk.Label(label="Emails")
            email_title.set_xalign(0)
            email_title.add_css_class("heading")
            email_title.set_margin_top(8)
            self._detail.append(email_title)
            for email in contact.emails:
                lbl = Gtk.Label(label=email)
                lbl.set_xalign(0)
                lbl.set_selectable(True)
                lbl.add_css_class("dim-label")
                self._detail.append(lbl)

    def _render_no_phone(self) -> None:
        lbl = Gtk.Label(label="Aucun numéro de téléphone pour ce contact.")
        lbl.set_xalign(0)
        lbl.add_css_class("dim-label")
        self._detail.append(lbl)

    def _phone_row(self, contact, phone: str) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        number = Gtk.Label(label=phone)
        number.set_xalign(0)
        number.set_hexpand(True)
        number.set_selectable(True)
        row.append(number)

        sms_btn = Gtk.Button(label="Envoyer SMS")
        sms_btn.set_tooltip_text("Ouvrir la fenêtre Messages avec ce destinataire")
        sms_btn.connect(
            "clicked",
            lambda _b, p=phone, n=contact.display_name: self._on_sms(p, n),
        )
        row.append(sms_btn)

        call_btn = Gtk.Button(label="Appeler")
        call_btn.set_tooltip_text(
            "Ouvre le dialer sur le téléphone — confirmez l'appel sur l'écran "
            "du téléphone (audio Ubuntu via Bluetooth HFP)"
        )
        call_btn.connect("clicked", lambda _b, p=phone: self._on_call(p))
        row.append(call_btn)

        return row

    # ── actions ──────────────────────────────────────

    def _on_sms(self, phone: str, name: str) -> None:
        if self._open_sms is None:
            show_dialog(
                self, "Contacts",
                "Ouverture de la fenêtre Messages indisponible.", error=True,
            )
            return
        try:
            self._open_sms(phone, name)
        except Exception as exc:  # ne jamais casser la fenêtre Contacts
            logger.warning("Contacts: ouverture SMS échouée: %s", exc)
            show_dialog(self, "Contacts", f"Échec : {exc}", error=True)

    def _on_call(self, phone: str) -> None:
        def worker() -> None:
            ok, detail = android_bridge.start_call(phone)
            GLib.idle_add(on_done, ok, detail)

        def on_done(ok: bool, detail: str) -> bool:
            show_dialog(self, "Appel", detail, error=not ok)
            return False  # one-shot

        threading.Thread(target=worker, daemon=True).start()

    # ── helpers ──────────────────────────────────────

    @staticmethod
    def _clear(container) -> None:
        child = container.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            container.remove(child)
            child = nxt


def _normalise(value: str) -> str:
    """Minuscules sans accents (et sans espaces pour les numéros)."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold().replace(" ", "")


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    status = getattr(exc, "status", None)
    if "contacts_permission_missing" in text:
        return (
            "Accès aux contacts non accordé sur le téléphone.\n\n"
            "Ouvrez l'app PhoneLink Companion et touchez « Autoriser l'accès "
            "aux SMS » (READ_CONTACTS est demandée avec les permissions SMS)."
        )
    if status in (401, 403):
        return (
            "Accès refusé (token invalide).\n"
            "Ré-appairez l'app compagnon depuis la fenêtre principale."
        )
    return (
        "Impossible de charger les contacts.\n\n"
        "Vérifiez que le téléphone est connecté et appairé.\n\n"
        f"Détail : {text}"
    )
