"""SMS panel for PhoneLink Ubuntu.

Layout: conversation list on the left, the selected thread on the right, and a
compose row at the bottom. The window talks only to
:class:`~app.core.sms.SmsBackend`, so the mock and the real Android-companion
backend are interchangeable.

Behaviour highlights:

* messages for a conversation are loaded **in a background thread** (the real
  backend does HTTP) and **cached** per ``conversation_id`` so re-opening a
  thread is instant; a "Rafraîchir" button forces a reload;
* the thread auto-scrolls to the **latest** message once laid out;
* sending a **real** SMS (Android backend) requires an explicit confirmation
  dialog — no real SMS leaves the phone without the user clicking "Envoyer";
* a "Appairer" button runs the PIN pairing flow and switches to the Android
  backend without restarting the app.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Gdk, Pango, GLib

from app.core import android_bridge
from app.core import sms as sms_core
from app.utils.logger import get_logger

logger = get_logger(__name__)

_CSS = b"""
.sms-bubble { padding: 8px 12px; border-radius: 14px; }
.sms-in  { background-color: alpha(@theme_fg_color, 0.10); }
.sms-out { background-color: @accent_bg_color; color: @accent_fg_color; }
.sms-time { font-size: 0.75em; opacity: 0.6; }
.sms-preview { opacity: 0.6; font-size: 0.9em; }
.sms-badge {
    font-size: 0.7em;
    padding: 1px 6px;
    border-radius: 8px;
    background-color: alpha(@theme_fg_color, 0.12);
}
.sms-badge-rcs { background-color: alpha(@accent_bg_color, 0.35); }
"""


class SmsWindow(Gtk.Window):
    """Read/compose SMS over a pluggable backend (currently a mock)."""

    def __init__(self, parent: Gtk.Window):
        super().__init__(transient_for=parent, modal=False)
        self.set_title("Messages")
        self.set_default_size(1000, 700)

        self._backend = sms_core.get_backend()
        self._current_id: str | None = None
        self._current_source: str = "sms"  # source du fil ouvert (compose RCS off)
        # Cache des messages déjà chargés, par conversation_id → liste de Message.
        # Évite de recharger depuis Android à chaque clic (P3).
        self._cache: dict[str, list[sms_core.Message]] = {}
        # Compteur de génération : un chargement async obsolète est ignoré si
        # l'utilisateur a changé de conversation entre-temps.
        self._load_seq = 0
        # Scroll auto en bas : armé à chaque ouverture, consommé une fois le
        # contenu réellement mis en page (cf. _on_thread_adj_changed).
        self._scroll_pending = False
        # Largeur dynamique des bulles : on suit les labels affichés et on
        # recalcule leur largeur max selon la place réelle (cf. do_size_allocate).
        self._bubbles: list[Gtk.Label] = []
        self._bubble_max_chars = self._BUBBLE_MAX_CHARS
        self._char_px: float | None = None
        self._install_css()

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(outer)

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        title = Gtk.Label(label="Messages")
        title.add_css_class("title")
        header.set_title_widget(title)

        # Bouton d'appairage PIN (bascule vers le backend Android réel).
        pair_btn = Gtk.Button.new_from_icon_name("channel-secure-symbolic")
        pair_btn.set_tooltip_text("Appairer l'app compagnon Android (PIN)")
        pair_btn.connect("clicked", self._on_pair_clicked)
        header.pack_start(pair_btn)

        # Bouton de rafraîchissement de la conversation courante (force reload).
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Rafraîchir cette conversation")
        refresh_btn.connect("clicked", self._on_refresh_clicked)
        header.pack_end(refresh_btn)

        outer.append(header)

        # Banner: make the demo / no-real-send state explicit.
        self._banner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(self._banner_box)
        self._refresh_banner()

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        paned.set_position(280)
        # Déplacer le séparateur change la largeur de la zone messages sans
        # redimensionner la fenêtre : on recalcule alors la largeur des bulles.
        paned.connect("notify::position", lambda *_: self._update_bubble_width())
        outer.append(paned)

        paned.set_start_child(self._build_conversation_list())
        paned.set_resize_start_child(False)
        paned.set_end_child(self._build_thread_pane())

        # Select the first conversation by default.
        first = self._list.get_row_at_index(0)
        if first is not None:
            self._list.select_row(first)

    # ── styling ──────────────────────────────────

    def _install_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _refresh_banner(self) -> None:
        """(Re)construit la bannière d'état selon le backend actif.

        Affichée seulement si le backend n'est pas un canal réel (mock/démo, ou
        Android non joignable). Vide sinon.
        """
        child = self._banner_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._banner_box.remove(child)
            child = nxt

        if self._backend.is_ready:
            return  # canal réel : pas de bannière

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.add_css_class("sms-preview")
        bar.set_margin_top(6)
        bar.set_margin_bottom(6)
        bar.set_margin_start(12)
        bar.set_margin_end(12)
        icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        bar.append(icon)
        lbl = Gtk.Label(
            label=f"{self._backend.name} — l'envoi est simulé. "
                  "Cliquez sur l'icône cadenas pour appairer l'app compagnon Android."
        )
        lbl.set_wrap(True)
        lbl.set_xalign(0)
        bar.append(lbl)
        self._banner_box.append(bar)

    # ── left: conversation list ──────────────────

    def _build_conversation_list(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list.add_css_class("navigation-sidebar")
        self._list.connect("row-selected", self._on_conversation_selected)

        for convo in self._backend.list_conversations():
            self._list.append(self._conversation_row(convo))

        scroll.set_child(self._list)
        return scroll

    def _conversation_row(self, convo: sms_core.Conversation) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row._conversation_id = convo.id  # read back on selection
        row._contact_name = convo.contact_name  # used by the send confirmation
        row._source = convo.source  # "sms" | "rcs" — gère compose + badge

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)

        # Ligne nom + badge de source (SMS classique / RCS via notification).
        name_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        name = Gtk.Label(label=convo.contact_name)
        name.set_xalign(0)
        name.set_hexpand(True)
        name.set_ellipsize(3)  # END
        name.add_css_class("heading")
        name_row.append(name)
        if convo.source == "rcs":
            badge = Gtk.Label(label="RCS")
            badge.add_css_class("sms-badge")
            badge.add_css_class("sms-badge-rcs")
            badge.set_valign(Gtk.Align.CENTER)
            name_row.append(badge)
        box.append(name_row)

        last = convo.last_message
        if last is not None:
            preview_text = ("Vous : " if last.outgoing else "") + last.body
            preview = Gtk.Label(label=preview_text)
            preview.set_xalign(0)
            preview.set_ellipsize(3)  # Pango.EllipsizeMode.END
            preview.set_max_width_chars(28)
            preview.add_css_class("sms-preview")
            box.append(preview)

        row.set_child(box)
        return row

    # ── right: thread + compose ──────────────────

    def _build_thread_pane(self) -> Gtk.Widget:
        pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        pane.set_hexpand(True)

        self._thread_scroll = Gtk.ScrolledWindow()
        self._thread_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._thread_scroll.set_vexpand(True)
        # Scroll auto en bas : "changed" se déclenche quand le contenu est mis en
        # page (upper/page-size changent), donc après le rendu des bulles (P4).
        self._thread_scroll.get_vadjustment().connect(
            "changed", self._on_thread_adj_changed
        )

        self._thread_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._thread_box.set_margin_top(12)
        self._thread_box.set_margin_bottom(12)
        self._thread_box.set_margin_start(12)
        self._thread_box.set_margin_end(12)
        self._thread_scroll.set_child(self._thread_box)
        pane.append(self._thread_scroll)

        pane.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        pane.append(self._build_compose_row())
        return pane

    def _build_compose_row(self) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_top(8)
        row.set_margin_bottom(8)
        row.set_margin_start(12)
        row.set_margin_end(12)

        self._entry = Gtk.Entry()
        self._entry.set_hexpand(True)
        self._entry.set_placeholder_text("Votre message…")
        self._entry.connect("changed", self._on_entry_changed)
        self._entry.connect("activate", self._on_send)
        row.append(self._entry)

        self._send_btn = Gtk.Button(label="Envoyer")
        self._send_btn.add_css_class("suggested-action")
        self._send_btn.set_sensitive(False)  # enabled only when text is present
        self._send_btn.connect("clicked", self._on_send)
        row.append(self._send_btn)
        self._update_send_affordance()
        return row

    def _is_android_backend(self) -> bool:
        return isinstance(self._backend, sms_core.AndroidCompanionBackend)

    def _update_send_affordance(self) -> None:
        """Tooltip du bouton Envoyer selon le backend (réel vs démo)."""
        if self._is_android_backend():
            self._send_btn.set_tooltip_text(
                "Envoie un vrai SMS via Android (confirmation demandée)"
            )
        else:
            self._send_btn.set_tooltip_text(
                "Envoi simulé (appairez l'app compagnon Android pour un envoi réel)"
            )

    # ── handlers ─────────────────────────────────

    def _on_conversation_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            self._current_id = None
            self._current_source = "sms"
            self._render_messages([])
            self._update_compose_state()
            return
        self._current_id = getattr(row, "_conversation_id", None)
        self._current_source = getattr(row, "_source", "sms")
        self._update_compose_state()
        self._open_conversation(self._current_id)

    def _update_compose_state(self) -> None:
        """Active/désactive la zone de saisie selon la source du fil.

        V0.6.0 : les fils RCS sont en **lecture seule** (envoi via RemoteInput
        prévu en V0.6.1). On désactive donc la saisie pour ces fils.
        """
        is_rcs = self._current_source == "rcs"
        self._entry.set_sensitive(not is_rcs)
        if is_rcs:
            self._entry.set_placeholder_text("Réponse RCS indisponible (V0.6.0)")
            self._send_btn.set_sensitive(False)
        else:
            self._entry.set_placeholder_text("Votre message…")
        self._on_entry_changed(self._entry)

    def _on_entry_changed(self, entry: Gtk.Entry) -> None:
        has_text = bool(entry.get_text().strip())
        can_send = (
            has_text
            and self._current_id is not None
            and self._current_source != "rcs"
        )
        self._send_btn.set_sensitive(can_send)

    def _on_refresh_clicked(self, _btn: Gtk.Button) -> None:
        if self._current_id is None:
            return
        # Invalide le cache et recharge depuis le backend.
        self._cache.pop(self._current_id, None)
        self._open_conversation(self._current_id, force=True)

    def _on_send(self, _widget) -> None:
        body = self._entry.get_text().strip()
        if not body or self._current_id is None:
            return
        # Envoi réel (backend Android) → confirmation explicite obligatoire.
        if self._is_android_backend():
            self._confirm_real_send(self._current_id, body)
            return
        # Backend démo : envoi simulé, sans confirmation (rien ne quitte la machine).
        self._do_send(self._current_id, body, real=False)

    # ── chargement (cache + thread) ───────────────

    def _open_conversation(self, conversation_id: str | None, force: bool = False) -> None:
        """Affiche une conversation : depuis le cache si possible, sinon charge
        en arrière-plan (sans bloquer l'UI). ``force`` ignore le cache."""
        if conversation_id is None:
            self._render_messages([])
            return

        if not force and conversation_id in self._cache:
            logger.debug("SMS: conversation %s servie depuis le cache", conversation_id)
            self._render_messages(self._cache[conversation_id])
            return

        # Pas en cache : on lance un chargement async et on affiche un état
        # transitoire. Le compteur de génération évite d'afficher un résultat
        # obsolète si l'utilisateur change de conversation entre-temps.
        self._load_seq += 1
        seq = self._load_seq
        self._render_loading()

        def worker() -> None:
            t0 = time.perf_counter()
            try:
                convo = self._backend.get_conversation(conversation_id)
                messages = list(convo.messages) if convo is not None else []
                err: Exception | None = None
            except Exception as exc:  # transport : ne doit jamais crasher l'UI
                messages, err = [], exc
            elapsed_ms = (time.perf_counter() - t0) * 1000
            GLib.idle_add(
                self._on_loaded, conversation_id, seq, messages, elapsed_ms, err
            )

        threading.Thread(target=worker, daemon=True).start()

    def _on_loaded(
        self,
        conversation_id: str,
        seq: int,
        messages: list[sms_core.Message],
        elapsed_ms: float,
        err: Exception | None,
    ) -> bool:
        if err is not None:
            logger.warning("SMS: échec chargement %s: %s", conversation_id, err)
        else:
            logger.info(
                "SMS: conversation %s chargée (%d messages) en %.0f ms",
                conversation_id, len(messages), elapsed_ms,
            )
            self._cache[conversation_id] = messages
        # N'affiche que si c'est toujours le dernier chargement demandé.
        if seq == self._load_seq and conversation_id == self._current_id:
            self._render_messages(messages)
        return False  # one-shot

    # ── rendering ────────────────────────────────

    def _clear_thread(self) -> None:
        child = self._thread_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._thread_box.remove(child)
            child = nxt
        self._bubbles.clear()

    def _render_loading(self) -> None:
        self._clear_thread()
        lbl = Gtk.Label(label="Chargement…")
        lbl.add_css_class("sms-preview")
        lbl.set_margin_top(16)
        self._thread_box.append(lbl)

    def _render_messages(self, messages: list[sms_core.Message]) -> None:
        self._clear_thread()
        for message in messages:
            self._thread_box.append(self._bubble(message))
        # Largeur des bulles ajustée tout de suite à la place disponible.
        self._update_bubble_width()
        # Arme le scroll auto en bas : appliqué quand le contenu sera mis en page.
        self._scroll_pending = True

    def _on_thread_adj_changed(self, adj: Gtk.Adjustment) -> None:
        """Scrolle en bas une fois le contenu mesuré (P4).

        ``changed`` est émis quand ``upper``/``page-size`` évoluent, c.-à-d.
        après que les bulles sont mises en page : on peut alors viser le bas.
        """
        if not self._scroll_pending:
            return
        adj.set_value(max(0, adj.get_upper() - adj.get_page_size()))
        # Considère le scroll fait dès qu'il y a du contenu réellement défilable
        # (sinon on garde l'intention pour la prochaine mise en page).
        if adj.get_upper() > adj.get_page_size():
            self._scroll_pending = False

    # ── envoi (avec confirmation pour le réel) ────

    def _contact_name(self, conversation_id: str) -> str:
        row = self._row_for_id(conversation_id)
        return getattr(row, "_contact_name", conversation_id) if row else conversation_id

    def _confirm_real_send(self, conversation_id: str, body: str) -> None:
        """Demande une confirmation explicite avant d'envoyer un VRAI SMS (P1)."""
        name = self._contact_name(conversation_id)
        dialog = Gtk.AlertDialog()
        dialog.set_modal(True)
        dialog.set_message("Envoyer un vrai SMS ?")
        dialog.set_detail(
            f"Le message sera réellement envoyé à « {name} » via votre téléphone "
            "Android. Cette action peut être facturée par votre opérateur."
        )
        dialog.set_buttons(["Annuler", "Envoyer"])
        dialog.set_cancel_button(0)
        dialog.set_default_button(1)

        def on_response(dlg: Gtk.AlertDialog, res) -> None:
            try:
                choice = dlg.choose_finish(res)
            except GLib.Error:
                return  # fermé/annulé
            if choice != 1:
                logger.info("SMS: envoi réel annulé par l'utilisateur")
                return
            # Confirmation = autorisation explicite de l'envoi réel pour la session.
            android_bridge.set_allow_real_send(True)
            self._do_send(conversation_id, body, real=True)

        dialog.choose(self, None, on_response)

    def _do_send(self, conversation_id: str, body: str, real: bool) -> None:
        try:
            sent, detail = self._backend.send_message(conversation_id, body)
        except Exception as exc:  # réseau/HTTP : ne jamais remonter dans GTK
            logger.warning("SMS: envoi échoué (conv %s): %s", conversation_id, exc)
            from app.ui.widgets import show_dialog
            show_dialog(self, "Envoi SMS", f"Échec de l'envoi : {exc}", error=True)
            return
        logger.info(
            "SMS: envoi (réel demandé=%s) → conv %s : transmis=%s detail=%r",
            real, conversation_id, sent, detail,
        )
        self._entry.set_text("")

        # Affichage optimiste : on ajoute le message localement si l'envoi a
        # réussi, ou si on est en démo (envoi simulé volontairement visible).
        if sent or not real:
            echo = sms_core.Message(
                body=body, timestamp=datetime.now(), outgoing=True
            )
            self._cache[conversation_id] = self._cache.get(conversation_id, []) + [echo]
            if conversation_id == self._current_id:
                self._render_messages(self._cache[conversation_id])

        if not sent and detail:
            from app.ui.widgets import show_dialog
            show_dialog(self, "Envoi SMS", detail, error=real)

    # ── appairage PIN ─────────────────────────────

    def _on_pair_clicked(self, _btn: Gtk.Button) -> None:
        """Ouvre une petite fenêtre modale : champ PIN + bouton Appairer (P5b)."""
        win = Gtk.Window(title="Appairer l'app compagnon", transient_for=self, modal=True)
        win.set_default_size(360, -1)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)

        info = Gtk.Label(
            label="Saisissez le PIN affiché par l'app PhoneLink Companion "
                  "(le port-forward ADB doit être actif)."
        )
        info.set_wrap(True)
        info.set_xalign(0)
        box.append(info)

        entry = Gtk.Entry()
        entry.set_placeholder_text("PIN à 6 chiffres")
        entry.set_max_length(6)
        entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        box.append(entry)

        status = Gtk.Label(label="")
        status.set_wrap(True)
        status.set_xalign(0)
        box.append(status)

        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btns.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label="Annuler")
        cancel.connect("clicked", lambda _b: win.destroy())
        pair = Gtk.Button(label="Appairer")
        pair.add_css_class("suggested-action")
        btns.append(cancel)
        btns.append(pair)
        box.append(btns)
        win.set_child(box)

        def do_pair(_w=None) -> None:
            pin = entry.get_text().strip()
            if not pin:
                status.set_text("Veuillez saisir le PIN.")
                return
            pair.set_sensitive(False)
            status.set_text("Appairage en cours…")

            def worker() -> None:
                try:
                    android_bridge.pair_and_save(pin)
                    err: Exception | None = None
                except Exception as exc:  # BridgeError et autres
                    err = exc
                GLib.idle_add(on_done, err)

            def on_done(err: Exception | None) -> bool:
                if err is not None:
                    logger.warning("Appairage échoué: %s", err)
                    status.set_text(f"Échec : {err}")
                    pair.set_sensitive(True)
                    return False
                logger.info("Appairage réussi — bascule vers le backend Android")
                win.destroy()
                self._reload_backend()
                return False

            threading.Thread(target=worker, daemon=True).start()

        pair.connect("clicked", do_pair)
        entry.connect("activate", do_pair)
        win.present()

    def _reload_backend(self) -> None:
        """Recharge le backend (après appairage) et reconstruit la liste."""
        sms_core.set_backend(None)  # forcera une re-sélection (config http+token)
        self._backend = sms_core.get_backend()
        logger.info("SMS: backend rechargé → %s", self._backend.name)
        self._cache.clear()
        self._current_id = None
        self._refresh_banner()
        self._update_send_affordance()
        self._reload_conversation_list()

    def _reload_conversation_list(self) -> None:
        child = self._list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._list.remove(child)
            child = nxt
        try:
            convos = self._backend.list_conversations()
        except Exception as exc:
            logger.warning("SMS: liste conversations indisponible: %s", exc)
            convos = []
        for convo in convos:
            self._list.append(self._conversation_row(convo))
        first = self._list.get_row_at_index(0)
        if first is not None:
            self._list.select_row(first)

    def _row_for_id(self, conversation_id: str) -> Gtk.ListBoxRow | None:
        index = 0
        while True:
            row = self._list.get_row_at_index(index)
            if row is None:
                return None
            if getattr(row, "_conversation_id", None) == conversation_id:
                return row
            index += 1

    #: Largeur maximale d'une bulle, en caractères (≈ 60 % de la zone messages à
    #: la taille par défaut). Borne la largeur ET force le retour à la ligne.
    _BUBBLE_MAX_CHARS = 44

    def _bubble(self, message: sms_core.Message) -> Gtk.Widget:
        align = Gtk.Align.END if message.outgoing else Gtk.Align.START

        # La colonne ne s'étire pas : alignée à gauche (reçu) / droite (envoyé),
        # elle se réduit à la largeur de la bulle.
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        column.set_halign(align)
        column.set_hexpand(False)

        bubble = Gtk.Label(label=message.body)
        bubble.set_wrap(True)
        # WORD_CHAR : coupe sur les mots, et À L'INTÉRIEUR d'un mot si besoin.
        # Indispensable pour les vrais SMS (codes, URLs, longs numéros) qui ne
        # contiennent pas d'espace et débordaient sinon sur une seule ligne.
        bubble.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        bubble.set_xalign(0)
        bubble.set_halign(align)
        bubble.set_hexpand(False)
        # Borne la largeur naturelle → la bulle ne dépasse pas cette largeur et
        # le texte revient à la ligne au-delà. La valeur est recalculée
        # dynamiquement selon la place disponible (cf. _update_bubble_width).
        bubble.set_max_width_chars(self._bubble_max_chars)
        bubble.add_css_class("sms-bubble")
        bubble.add_css_class("sms-out" if message.outgoing else "sms-in")
        self._bubbles.append(bubble)
        column.append(bubble)

        time_text = _fmt_time(message.timestamp)
        if message.source == "rcs":
            time_text += " · RCS"
        time_lbl = Gtk.Label(label=time_text)
        time_lbl.set_halign(align)
        time_lbl.add_css_class("sms-time")
        column.append(time_lbl)
        return column

    # ── largeur dynamique des bulles ─────────────

    #: Part de la zone messages occupée au maximum par une bulle.
    _BUBBLE_WIDTH_RATIO = 0.65

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        # Laisse GTK allouer les enfants d'abord (la zone messages obtient sa
        # largeur), puis on ajuste la largeur max des bulles.
        Gtk.Window.do_size_allocate(self, width, height, baseline)
        self._update_bubble_width()

    def _update_bubble_width(self) -> None:
        """Recalcule la largeur max des bulles (~65 % de la zone messages).

        Robuste : si la mesure n'est pas encore disponible ou échoue, on garde
        la borne fixe :attr:`_BUBBLE_MAX_CHARS` comme fallback.
        """
        area = self._thread_scroll.get_width()
        if area <= 1:
            return  # pas encore alloué : on garde la valeur courante
        char_px = self._approx_char_px()
        target = int((area * self._BUBBLE_WIDTH_RATIO) / char_px)
        # Borne raisonnable : jamais trop étroit, jamais au-delà du fallback ×2.
        target = max(20, min(target, self._BUBBLE_MAX_CHARS * 2))
        if target == self._bubble_max_chars:
            return  # rien à faire → évite des relayouts inutiles
        self._bubble_max_chars = target
        for bubble in self._bubbles:
            bubble.set_max_width_chars(target)

    def _approx_char_px(self) -> float:
        """Largeur approx. d'un caractère, en px, pour convertir px → chars.

        Mesurée une fois via Pango sur un échantillon de texte réaliste, puis
        mémorisée. Sert uniquement à approcher la cible 60–70 %.
        """
        if self._char_px is None:
            sample = "the quick brown fox jumps over the lazy dog "
            layout = self.create_pango_layout(sample)
            px, _ = layout.get_pixel_size()
            self._char_px = max(1.0, px / len(sample))
        return self._char_px


def _fmt_time(ts: datetime) -> str:
    """Short time label: 'HH:MM' today, otherwise 'JJ/MM HH:MM'."""
    now = datetime.now()
    if ts.date() == now.date():
        return ts.strftime("%H:%M")
    return ts.strftime("%d/%m %H:%M")
