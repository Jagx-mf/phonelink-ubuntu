"""SMS panel for PhoneLink Ubuntu (mock data, no Android connection yet).

Layout: conversation list on the left, the selected thread on the right, and a
compose row at the bottom. Sending is *simulated* — see ``app/core/sms.py`` and
``docs/sms.md``. The window talks only to :class:`~app.core.sms.SmsBackend`, so
swapping the mock for a real Android-companion backend changes nothing here.
"""

from __future__ import annotations

from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Gdk, Pango

from app.core import sms as sms_core
from app.utils.logger import get_logger

logger = get_logger(__name__)

_CSS = b"""
.sms-bubble { padding: 8px 12px; border-radius: 14px; }
.sms-in  { background-color: alpha(@theme_fg_color, 0.10); }
.sms-out { background-color: @accent_bg_color; color: @accent_fg_color; }
.sms-time { font-size: 0.75em; opacity: 0.6; }
.sms-preview { opacity: 0.6; font-size: 0.9em; }
"""


class SmsWindow(Gtk.Window):
    """Read/compose SMS over a pluggable backend (currently a mock)."""

    def __init__(self, parent: Gtk.Window):
        super().__init__(transient_for=parent, modal=False)
        self.set_title("Messages")
        self.set_default_size(1000, 700)

        self._backend = sms_core.get_backend()
        self._current_id: str | None = None
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
        outer.append(header)

        # Banner: make the demo / no-real-send state explicit.
        if not self._backend.is_ready:
            outer.append(self._demo_banner())

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

    def _demo_banner(self) -> Gtk.Widget:
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
                  "Le SMS réel nécessitera l'app compagnon Android."
        )
        lbl.set_wrap(True)
        lbl.set_xalign(0)
        bar.append(lbl)
        return bar

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

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)

        name = Gtk.Label(label=convo.contact_name)
        name.set_xalign(0)
        name.add_css_class("heading")
        box.append(name)

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
        self._send_btn.set_tooltip_text("Envoi simulé (app compagnon Android requise)")
        self._send_btn.connect("clicked", self._on_send)
        row.append(self._send_btn)
        return row

    # ── handlers ─────────────────────────────────

    def _on_conversation_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            self._current_id = None
            return
        self._current_id = getattr(row, "_conversation_id", None)
        self._render_thread()

    def _on_entry_changed(self, entry: Gtk.Entry) -> None:
        has_text = bool(entry.get_text().strip())
        self._send_btn.set_sensitive(has_text and self._current_id is not None)

    def _on_send(self, _widget) -> None:
        body = self._entry.get_text().strip()
        if not body or self._current_id is None:
            return
        # Simulated send: backend appends locally and reports it's not real.
        sent, _msg = self._backend.send_message(self._current_id, body)
        logger.debug("send simulated=%s", not sent)
        self._entry.set_text("")
        self._render_thread()

    # ── rendering ────────────────────────────────

    def _render_thread(self) -> None:
        child = self._thread_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._thread_box.remove(child)
            child = nxt
        self._bubbles.clear()

        if self._current_id is None:
            return
        convo = self._backend.get_conversation(self._current_id)
        if convo is None:
            return

        for message in convo.messages:
            self._thread_box.append(self._bubble(message))
        # Ajuste tout de suite à la place actuelle (sinon valeur par défaut
        # jusqu'au prochain redimensionnement).
        self._update_bubble_width()

        # Scroll to the latest message after layout settles.
        adj = self._thread_scroll.get_vadjustment()
        if adj is not None:
            adj.set_value(adj.get_upper())

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

        time_lbl = Gtk.Label(label=_fmt_time(message.timestamp))
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
