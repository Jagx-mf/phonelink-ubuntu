"""Main application window for PhoneLink Ubuntu."""

import threading
from typing import Optional

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

try:
    gi.require_version("Adw", "1")
    from gi.repository import Adw
    HAS_ADW = True
except (ValueError, RuntimeError):
    HAS_ADW = False

from app.core import bluetooth as bt_core
from app.core import audio as audio_core
from app.core import adb as adb_core
from app.core import scrcpy as scrcpy_core
from app.core import photos as photos_core
from app.core import system_checks
from app.ui.widgets import show_dialog
from app.utils.commands import launch_background, is_installed
from app.utils.logger import get_logger

logger = get_logger(__name__)

PHONE_NAME = "S21 FE de Mickael"

if HAS_ADW:
    _Base = Adw.ApplicationWindow
else:
    _Base = Gtk.ApplicationWindow


class MainWindow(_Base):
    """PhoneLink Ubuntu — fenêtre principale."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("PhoneLink Ubuntu")
        self.set_default_size(480, 720)

        self._phone_mac: str = ""

        # Status value labels (set during _build_ui)
        self._val_phone: Optional[Gtk.Label] = None
        self._val_bt: Optional[Gtk.Label] = None
        self._val_profile: Optional[Gtk.Label] = None
        self._val_source: Optional[Gtk.Label] = None
        self._val_sink: Optional[Gtk.Label] = None
        self._val_adb: Optional[Gtk.Label] = None
        self._val_scrcpy: Optional[Gtk.Label] = None

        self._build_ui()
        # First refresh slightly deferred so the window renders first
        GLib.timeout_add(200, self._refresh_status)

    # ──────────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────────

    def _build_ui(self):
        if HAS_ADW:
            self._build_adw()
        else:
            self._build_gtk()

    def _build_adw(self):
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header = Adw.HeaderBar()
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Rafraîchir l'état")
        refresh_btn.connect("clicked", lambda _: self._refresh_status())
        header.pack_end(refresh_btn)
        toolbar_view.add_top_bar(header)

        page = Adw.PreferencesPage()
        toolbar_view.set_content(page)

        # ── Status group ──
        status_group = Adw.PreferencesGroup()
        status_group.set_title("État du système")
        status_group.set_description("Rafraîchi automatiquement au démarrage")
        page.add(status_group)

        self._val_phone   = self._adw_status_row(status_group, "Téléphone",      PHONE_NAME)
        self._val_bt      = self._adw_status_row(status_group, "Bluetooth",       "Vérification…")
        self._val_profile = self._adw_status_row(status_group, "Profil audio BT", "…")
        self._val_source  = self._adw_status_row(status_group, "Micro Ubuntu",    "…")
        self._val_sink    = self._adw_status_row(status_group, "Sortie audio",    "…")
        self._val_adb     = self._adw_status_row(status_group, "ADB",             "…")
        self._val_scrcpy  = self._adw_status_row(status_group, "scrcpy",          "…")

        # ── Actions group ──
        actions_group = Adw.PreferencesGroup()
        actions_group.set_title("Actions")
        page.add(actions_group)

        actions = [
            ("Scanner Bluetooth",           "network-wireless-acquiring-symbolic", self._on_scan_bt),
            ("Reconnecter le téléphone",    "bluetooth-symbolic",                  self._on_reconnect),
            ("Paramètres Bluetooth",        "preferences-system-symbolic",         self._on_bt_settings),
            ("Ouvrir pavucontrol",          "audio-volume-high-symbolic",          self._on_pavucontrol),
            ("Mode appel — guide",          "phone-symbolic",                      self._on_call_mode),
            ("Afficher téléphone (scrcpy)", "video-display-symbolic",              self._on_scrcpy),
            ("Importer photos",             "camera-photo-symbolic",               self._on_import_photos),
            ("Ouvrir dossier photos",       "folder-pictures-symbolic",            self._on_open_photos),
            ("Diagnostic système",          "computer-symbolic",                   self._on_diagnostic),
        ]

        for title, icon_name, callback in actions:
            row = Adw.ActionRow()
            row.set_title(title)
            row.set_activatable(True)
            row.connect("activated", callback)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            actions_group.add(row)

    def _adw_status_row(self, group: "Adw.PreferencesGroup", title: str, value: str) -> Gtk.Label:
        """Add a read-only status row; return its value label."""
        row = Adw.ActionRow()
        row.set_title(title)

        lbl = Gtk.Label(label=value)
        lbl.set_valign(Gtk.Align.CENTER)
        lbl.add_css_class("dim-label")
        lbl.set_ellipsize(3)       # Pango.EllipsizeMode.END
        lbl.set_max_width_chars(32)
        row.add_suffix(lbl)

        group.add(row)
        return lbl

    def _build_gtk(self):
        """Fallback layout for GTK4 without libadwaita."""
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(outer)

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Rafraîchir l'état")
        refresh_btn.connect("clicked", lambda _: self._refresh_status())
        header.pack_end(refresh_btn)
        outer.append(header)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer.append(scroll)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)
        scroll.set_child(content)

        # Status section
        t = Gtk.Label(label="État du système")
        t.add_css_class("title-3")
        t.set_halign(Gtk.Align.START)
        content.append(t)

        grid = Gtk.Grid()
        grid.set_row_spacing(6)
        grid.set_column_spacing(16)
        content.append(grid)

        rows = [
            ("Téléphone",      PHONE_NAME),
            ("Bluetooth",      "Vérification…"),
            ("Profil audio BT","…"),
            ("Micro Ubuntu",   "…"),
            ("Sortie audio",   "…"),
            ("ADB",            "…"),
            ("scrcpy",         "…"),
        ]
        val_refs: list[Gtk.Label] = []
        for i, (key, val) in enumerate(rows):
            k = Gtk.Label(label=key + " :")
            k.set_halign(Gtk.Align.START)
            k.add_css_class("dim-label")
            grid.attach(k, 0, i, 1, 1)

            v = Gtk.Label(label=val)
            v.set_halign(Gtk.Align.START)
            v.set_hexpand(True)
            grid.attach(v, 1, i, 1, 1)
            val_refs.append(v)

        (self._val_phone, self._val_bt, self._val_profile,
         self._val_source, self._val_sink,
         self._val_adb, self._val_scrcpy) = val_refs

        sep = Gtk.Separator()
        sep.set_margin_top(12)
        sep.set_margin_bottom(8)
        content.append(sep)

        t2 = Gtk.Label(label="Actions")
        t2.add_css_class("title-3")
        t2.set_halign(Gtk.Align.START)
        content.append(t2)

        for label, callback in [
            ("Scanner Bluetooth",           self._on_scan_bt),
            ("Reconnecter le téléphone",    self._on_reconnect),
            ("Paramètres Bluetooth",        self._on_bt_settings),
            ("Ouvrir pavucontrol",          self._on_pavucontrol),
            ("Mode appel — guide",          self._on_call_mode),
            ("Afficher téléphone (scrcpy)", self._on_scrcpy),
            ("Importer photos",             self._on_import_photos),
            ("Ouvrir dossier photos",       self._on_open_photos),
            ("Diagnostic système",          self._on_diagnostic),
        ]:
            btn = Gtk.Button(label=label)
            btn.set_hexpand(True)
            btn.set_margin_top(2)
            btn.connect("clicked", callback)
            content.append(btn)

    # ──────────────────────────────────────────────
    # Status refresh (background thread → GLib.idle_add)
    # ──────────────────────────────────────────────

    def _refresh_status(self) -> bool:
        """Start a background fetch of all status data. Returns False (GLib timeout)."""
        logger.info("Refreshing status")
        threading.Thread(target=self._fetch_status, daemon=True).start()
        return False  # Don't repeat if called via GLib.timeout_add

    def _fetch_status(self):
        """Background: collect status data from all core modules."""
        paired = bt_core.get_paired_devices()
        phone = _find_phone(paired)
        bt_connected = phone.connected if phone else False
        mac = phone.mac if phone else ""
        phone_name = phone.name if phone else PHONE_NAME

        _, profile_raw = audio_core.get_bluetooth_card_profile()
        source = audio_core.get_active_source() or "Non détecté"
        sink   = audio_core.get_active_sink()   or "Non détecté"

        adb_ok   = adb_core.is_device_connected()
        scrcpy_ok = scrcpy_core.is_scrcpy_installed()

        GLib.idle_add(
            self._apply_status,
            phone_name, bt_connected, mac,
            _fmt_profile(profile_raw),
            source, sink, adb_ok, scrcpy_ok,
        )

    def _apply_status(
        self,
        phone_name: str,
        bt_connected: bool,
        mac: str,
        profile: str,
        source: str,
        sink: str,
        adb_ok: bool,
        scrcpy_ok: bool,
    ):
        """Apply fetched data to UI labels (must run on GTK main thread)."""
        self._phone_mac = mac

        self._val_phone.set_label(phone_name)

        _set_status_label(self._val_bt,
                          "Connecté ✓" if bt_connected else "Non connecté",
                          ok=bt_connected)
        self._val_profile.set_label(profile)
        self._val_source.set_label(_shorten(source))
        self._val_sink.set_label(_shorten(sink))
        _set_status_label(self._val_adb,
                          "Connecté ✓" if adb_ok else "Non connecté",
                          ok=adb_ok)
        _set_status_label(self._val_scrcpy,
                          "Installé ✓" if scrcpy_ok else "Non installé",
                          ok=scrcpy_ok)

    # ──────────────────────────────────────────────
    # Action handlers
    # ──────────────────────────────────────────────

    def _on_scan_bt(self, _):
        _set_status_label(self._val_bt, "Scan en cours (6s)…", ok=None)

        def worker():
            bt_core.scan_start(6)
            GLib.idle_add(self._refresh_status)

        threading.Thread(target=worker, daemon=True).start()

    def _on_reconnect(self, _):
        if not self._phone_mac:
            show_dialog(self, "MAC introuvable",
                        "Aucun téléphone appairé détecté.\n"
                        "Vérifiez les paramètres Bluetooth GNOME.", error=True)
            return

        mac = self._phone_mac

        def worker():
            ok, msg = bt_core.connect_device(mac)

            def on_done():
                show_dialog(self, "Connexion Bluetooth", msg, error=not ok)
                self._refresh_status()

            GLib.idle_add(on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_bt_settings(self, _):
        launch_background(["gnome-control-center", "bluetooth"])

    def _on_pavucontrol(self, _):
        ok, msg = audio_core.open_pavucontrol()
        if not ok:
            show_dialog(self, "pavucontrol absent", msg, error=True)

    def _on_call_mode(self, _):
        show_dialog(self, "Mode appel — Guide",
            "Pour passer un appel avec le micro Ubuntu :\n\n"
            "1. Connectez le téléphone en Bluetooth\n"
            "2. Passez / recevez un appel sur le téléphone\n"
            "3. Dans pavucontrol → onglet 'Configuration' :\n"
            "   Sélectionnez 'Headset Head Unit (HSP/HFP)'\n"
            "4. Dans pavucontrol → onglet 'Entrée' :\n"
            "   Vérifiez que le micro Bluetooth est sélectionné\n"
            "5. Parlez — votre micro Ubuntu est utilisé par le téléphone"
        )

    def _on_scrcpy(self, _):
        def worker():
            ok, msg = scrcpy_core.launch()
            if not ok:
                GLib.idle_add(show_dialog, self, "scrcpy", msg, True)

        threading.Thread(target=worker, daemon=True).start()

    def _on_import_photos(self, _):
        folder = photos_core.get_import_folder()
        show_dialog(self, "Import photos",
                    f"Import en cours depuis /sdcard/DCIM/Camera\n→ {folder}")

        def worker():
            ok, msg = photos_core.import_photos()
            GLib.idle_add(show_dialog, self, "Import photos", msg, not ok)

        threading.Thread(target=worker, daemon=True).start()

    def _on_open_photos(self, _):
        ok, msg = photos_core.open_local_folder()
        if not ok:
            show_dialog(self, "Erreur", msg, error=True)

    def _on_diagnostic(self, _):
        def worker():
            statuses = system_checks.check_all()
            lines = []
            for name, s in statuses.items():
                if name == "bluetooth_service":
                    mark = "✓" if s.active else "✗"
                    state = "actif" if s.active else s.note
                    lines.append(f"{mark} {s.label} : {state}")
                else:
                    mark = "✓" if s.installed else "✗"
                    state = "installé" if s.installed else "ABSENT"
                    if s.version:
                        state += f"  ({s.version[:30]})"
                    lines.append(f"{mark} {s.label} : {state}")

            body = "\n".join(lines)
            GLib.idle_add(show_dialog, self, "Diagnostic système", body)

        threading.Thread(target=worker, daemon=True).start()


# ──────────────────────────────────────────────
# Module-level helpers
# ──────────────────────────────────────────────

def _find_phone(devices: list) -> Optional[object]:
    """Identify the S21 FE among paired devices by name keywords."""
    keywords = ("s21", "mickael", "samsung", "galaxy")
    for dev in devices:
        if any(kw in dev.name.lower() for kw in keywords):
            return dev
    return devices[0] if devices else None


def _fmt_profile(raw: Optional[str]) -> str:
    if raw is None:
        return "Non détecté"
    rl = raw.lower()
    if "a2dp" in rl:
        return "A2DP (haute qualité)"
    if any(x in rl for x in ("hsp", "hfp", "headset")):
        return "HSP/HFP (appels)"
    return raw


def _shorten(name: str) -> str:
    """Strip common PulseAudio device-name prefixes for display."""
    if not name:
        return "Non détecté"
    for prefix in ("alsa_output.", "alsa_input.",
                   "bluez_output.", "bluez_input.",
                   "bluez_sink.", "bluez_source."):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name[:50]


def _set_status_label(lbl: Gtk.Label, text: str, ok: Optional[bool]):
    """Update a status label text and colour class."""
    lbl.set_label(text)
    for cls in ("success", "error", "dim-label"):
        lbl.remove_css_class(cls)
    if ok is True:
        lbl.add_css_class("success")
    elif ok is False:
        lbl.add_css_class("error")
    else:
        lbl.add_css_class("dim-label")
