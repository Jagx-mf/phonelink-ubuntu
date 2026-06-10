"""Main application window for PhoneLink Ubuntu."""

import dataclasses
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
from app.core import android_bridge
from app.core import sms as sms_core
from app.core import event_listener
from app.core.config import PhoneLinkConfig, load_config, save_config
from app.ui.gallery_window import GalleryWindow
from app.ui.sms_window import SmsWindow
from app.ui.notifications_window import NotificationsWindow
from app.ui.files_window import FilesWindow
from app.ui.contacts_window import ContactsWindow
from app.ui.connection_window import ConnectionWindow, describe_connection_mode
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

        self._config = load_config()
        self._phone_mac: str = self._config.phone_mac
        self._phone_name: str = self._config.phone_name or PHONE_NAME

        # Status value labels (set during _build_ui)
        self._val_phone: Optional[Gtk.Label] = None
        self._val_bt: Optional[Gtk.Label] = None
        self._val_profile: Optional[Gtk.Label] = None
        self._val_source: Optional[Gtk.Label] = None
        self._val_sink: Optional[Gtk.Label] = None
        self._val_adb: Optional[Gtk.Label] = None
        self._val_scrcpy: Optional[Gtk.Label] = None

        # Phone status labels (V0.8 — battery + device status)
        self._val_battery: Optional[Gtk.Label] = None
        self._val_charging: Optional[Gtk.Label] = None
        self._val_server: Optional[Gtk.Label] = None
        self._val_sms: Optional[Gtk.Label] = None
        self._val_notif: Optional[Gtk.Label] = None
        # V1.0 — mode de connexion à l'app compagnon (USB/Wi-Fi/indisponible)
        self._val_connection: Optional[Gtk.Label] = None

        # ADB Wi-Fi host entry (set during _build_ui)
        self._wifi_host_entry: Optional[Gtk.Entry] = None

        # Temps réel Android (V0.9) : fenêtres enfants suivies (pour les
        # rafraîchir), écouteur d'événements long polling et notifications bureau.
        self._sms_window: Optional[SmsWindow] = None
        self._notif_window: Optional[NotificationsWindow] = None
        # V1.0 — fenêtres Fichiers / Contacts / Connexion (une instance à la fois)
        self._files_window: Optional[FilesWindow] = None
        self._contacts_window: Optional[ContactsWindow] = None
        self._connection_window: Optional[ConnectionWindow] = None
        self._notifier: Optional[event_listener.DesktopNotifier] = None
        #: conversation_id → timestamp (epoch s) du dernier message vu (anti-doublon).
        self._sms_seen: dict[str, float] = {}
        self._event_listener = event_listener.AndroidEventListener(
            on_event=self._on_android_event,
            on_auth_error=self._on_realtime_auth_required,
        )

        self._build_ui()
        self.connect("close-request", self._on_close)
        # First refresh slightly deferred so the window renders first
        GLib.timeout_add(200, self._refresh_status)
        # Démarre l'écoute temps réel une fois la fenêtre rattachée à l'app
        # (nécessaire pour les notifications bureau via Gtk.Application).
        GLib.timeout_add(600, self._start_realtime)

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

        self._val_phone   = self._adw_status_row(status_group, "Téléphone",      self._phone_name)
        self._val_bt      = self._adw_status_row(status_group, "Bluetooth",       "Vérification…")
        self._val_profile = self._adw_status_row(status_group, "Profil audio BT", "…")
        self._val_source  = self._adw_status_row(status_group, "Micro Ubuntu",    "…")
        self._val_sink    = self._adw_status_row(status_group, "Sortie audio",    "…")
        self._val_adb     = self._adw_status_row(status_group, "ADB",             "…")
        self._val_scrcpy  = self._adw_status_row(status_group, "scrcpy",          "…")

        # ── Phone (Android) group — V0.8 ──
        phone_group = Adw.PreferencesGroup()
        phone_group.set_title("Téléphone Android")
        phone_group.set_description("Via l'app compagnon (appairage requis)")
        page.add(phone_group)

        self._val_connection = self._adw_status_row(phone_group, "Connexion",       "—")
        self._val_battery  = self._adw_status_row(phone_group, "Batterie",          "—")
        self._val_charging = self._adw_status_row(phone_group, "Charge",            "—")
        self._val_server   = self._adw_status_row(phone_group, "Serveur Android",   "—")
        self._val_sms      = self._adw_status_row(phone_group, "SMS",               "—")
        self._val_notif    = self._adw_status_row(phone_group, "Notifications",     "—")

        # ── Sections d'actions (V1.0 — UX par cartes cohérentes) ──
        sections = [
            ("Communication", "Messages, contacts et notifications du téléphone", [
                ("Messages (SMS)",        "user-available-symbolic",             self._on_open_sms),
                ("Contacts",              "avatar-default-symbolic",             self._on_open_contacts),
                ("Notifications Android", "preferences-system-notifications-symbolic", self._on_open_notifications),
            ]),
            ("Fichiers et photos", "Explorateur Android et import de photos", [
                ("Fichiers Android",      "folder-remote-symbolic",              self._on_open_files),
                ("Importer photos",       "camera-photo-symbolic",               self._on_import_photos),
                ("Galerie photos",        "image-x-generic-symbolic",            self._on_open_gallery),
                ("Ouvrir dossier photos", "folder-pictures-symbolic",            self._on_open_photos),
            ]),
            ("Connexion", "Appairage et transport vers l'app compagnon", [
                ("Connexion Android (USB / Wi-Fi)", "network-workgroup-symbolic", self._on_open_connection),
                ("Appairer Android Companion",      "channel-secure-symbolic",    self._on_pair_android),
            ]),
            ("Audio et affichage", "Bluetooth, son et miroir d'écran", [
                ("Afficher téléphone (scrcpy)", "video-display-symbolic",              self._on_scrcpy),
                ("Scanner Bluetooth",           "network-wireless-acquiring-symbolic", self._on_scan_bt),
                ("Reconnecter le téléphone",    "bluetooth-symbolic",                  self._on_reconnect),
                ("Paramètres Bluetooth",        "preferences-system-symbolic",         self._on_bt_settings),
                ("Ouvrir pavucontrol",          "audio-volume-high-symbolic",          self._on_pavucontrol),
                ("Mode appel — guide",          "phone-symbolic",                      self._on_call_mode),
                ("Diagnostic système",          "computer-symbolic",                   self._on_diagnostic),
            ]),
        ]

        for group_title, group_desc, actions in sections:
            group = Adw.PreferencesGroup()
            group.set_title(group_title)
            group.set_description(group_desc)
            page.add(group)
            for title, icon_name, callback in actions:
                row = Adw.ActionRow()
                row.set_title(title)
                row.set_activatable(True)
                row.connect("activated", callback)
                row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))
                row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
                group.add(row)

        # ── ADB Wi-Fi group ──
        wifi_group = Adw.PreferencesGroup()
        wifi_group.set_title("ADB Wi-Fi")
        wifi_group.set_description("Photos et scrcpy sans câble (avancé)")
        page.add(wifi_group)

        host_row = Adw.ActionRow()
        host_row.set_title("Adresse IP")
        self._wifi_host_entry = Gtk.Entry()
        self._wifi_host_entry.set_placeholder_text("192.168.1.x")
        self._wifi_host_entry.set_valign(Gtk.Align.CENTER)
        if self._config.adb_wifi_host:
            self._wifi_host_entry.set_text(self._config.adb_wifi_host)
        host_row.add_suffix(self._wifi_host_entry)
        wifi_group.add(host_row)

        wifi_actions = [
            ("Connecter ADB Wi-Fi",      "network-wireless-symbolic", self._on_wifi_connect),
            ("Déconnecter ADB Wi-Fi",    "network-offline-symbolic",  self._on_wifi_disconnect),
            ("Activer TCP/IP (via USB)", "network-wired-symbolic",    self._on_wifi_enable_tcpip),
        ]
        for title, icon_name, callback in wifi_actions:
            row = Adw.ActionRow()
            row.set_title(title)
            row.set_activatable(True)
            row.connect("activated", callback)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            wifi_group.add(row)

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
            ("Téléphone",      self._phone_name),
            ("Bluetooth",      "Vérification…"),
            ("Profil audio BT","…"),
            ("Micro Ubuntu",   "…"),
            ("Sortie audio",   "…"),
            ("ADB",            "…"),
            ("scrcpy",         "…"),
            # V0.8/V1.0 — connexion + batterie + statut téléphone Android
            ("Connexion",      "—"),
            ("Batterie",       "—"),
            ("Charge",         "—"),
            ("Serveur Android","—"),
            ("SMS",            "—"),
            ("Notifications",  "—"),
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
         self._val_adb, self._val_scrcpy,
         self._val_connection,
         self._val_battery, self._val_charging, self._val_server,
         self._val_sms, self._val_notif) = val_refs

        # Sections d'actions (V1.0 — mêmes groupes que la variante Adwaita).
        sections = [
            ("Communication", [
                ("Messages (SMS)",        self._on_open_sms),
                ("Contacts",              self._on_open_contacts),
                ("Notifications Android", self._on_open_notifications),
            ]),
            ("Fichiers et photos", [
                ("Fichiers Android",      self._on_open_files),
                ("Importer photos",       self._on_import_photos),
                ("Galerie photos",        self._on_open_gallery),
                ("Ouvrir dossier photos", self._on_open_photos),
            ]),
            ("Connexion", [
                ("Connexion Android (USB / Wi-Fi)", self._on_open_connection),
                ("Appairer Android Companion",      self._on_pair_android),
            ]),
            ("Audio et affichage", [
                ("Afficher téléphone (scrcpy)", self._on_scrcpy),
                ("Scanner Bluetooth",           self._on_scan_bt),
                ("Reconnecter le téléphone",    self._on_reconnect),
                ("Paramètres Bluetooth",        self._on_bt_settings),
                ("Ouvrir pavucontrol",          self._on_pavucontrol),
                ("Mode appel — guide",          self._on_call_mode),
                ("Diagnostic système",          self._on_diagnostic),
            ]),
        ]
        for section_title, actions in sections:
            sep = Gtk.Separator()
            sep.set_margin_top(12)
            sep.set_margin_bottom(8)
            content.append(sep)

            t2 = Gtk.Label(label=section_title)
            t2.add_css_class("title-3")
            t2.set_halign(Gtk.Align.START)
            content.append(t2)

            for label, callback in actions:
                btn = Gtk.Button(label=label)
                btn.set_hexpand(True)
                btn.set_margin_top(2)
                btn.connect("clicked", callback)
                content.append(btn)

        sep2 = Gtk.Separator()
        sep2.set_margin_top(12)
        sep2.set_margin_bottom(8)
        content.append(sep2)

        t3 = Gtk.Label(label="ADB Wi-Fi (avancé)")
        t3.add_css_class("title-3")
        t3.set_halign(Gtk.Align.START)
        content.append(t3)

        host_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        host_box.set_margin_top(2)
        host_label = Gtk.Label(label="Adresse IP :")
        host_label.add_css_class("dim-label")
        host_box.append(host_label)
        self._wifi_host_entry = Gtk.Entry()
        self._wifi_host_entry.set_placeholder_text("192.168.1.x")
        self._wifi_host_entry.set_hexpand(True)
        if self._config.adb_wifi_host:
            self._wifi_host_entry.set_text(self._config.adb_wifi_host)
        host_box.append(self._wifi_host_entry)
        content.append(host_box)

        for label, callback in [
            ("Connecter ADB Wi-Fi",      self._on_wifi_connect),
            ("Déconnecter ADB Wi-Fi",    self._on_wifi_disconnect),
            ("Activer TCP/IP (via USB)", self._on_wifi_enable_tcpip),
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
        phone = _find_phone(paired, self._config)
        bt_connected = phone.connected if phone else False
        mac = phone.mac if phone else ""
        phone_name = phone.name if phone else (self._config.phone_name or PHONE_NAME)

        _, profile_raw = audio_core.get_bluetooth_card_profile()
        source = audio_core.get_active_source() or "Non détecté"
        sink   = audio_core.get_active_sink()   or "Non détecté"

        adb_ok   = adb_core.is_device_connected()
        scrcpy_ok = scrcpy_core.is_scrcpy_installed()

        # V0.8 — batterie + statut téléphone via l'app compagnon. Ne lève jamais
        # (renvoie reachable=False si indisponible) : l'UI ne doit pas planter.
        device = android_bridge.get_device_status()

        GLib.idle_add(
            self._apply_status,
            phone_name, bt_connected, mac,
            _fmt_profile(profile_raw),
            source, sink, adb_ok, scrcpy_ok, device,
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
        device: "android_bridge.DeviceStatus",
    ):
        """Apply fetched data to UI labels (must run on GTK main thread)."""
        self._phone_mac = mac
        self._phone_name = phone_name
        self._save_phone_config(mac, phone_name)

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
        self._apply_device_status(device)

    def _apply_device_status(self, device: "android_bridge.DeviceStatus") -> None:
        """Apply phone battery/status to UI labels (V0.8). Never crashes."""
        mode = describe_connection_mode(self._config.android_bridge_base_url)
        if not device.reachable:
            for lbl in (self._val_battery, self._val_charging,
                        self._val_sms, self._val_notif):
                _set_status_label(lbl, "—", ok=None)
            _set_status_label(self._val_server, "Indisponible", ok=False)
            _set_status_label(self._val_connection,
                              f"{mode} — indisponible", ok=False)
            return

        _set_status_label(self._val_connection, f"{mode} ✓", ok=True)

        if device.battery_level >= 0:
            _set_status_label(self._val_battery, f"{device.battery_level} %", ok=None)
        else:
            _set_status_label(self._val_battery, "Inconnu", ok=None)
        _set_status_label(self._val_charging,
                          "Oui ✓" if device.battery_charging else "Non",
                          ok=device.battery_charging or None)
        _set_status_label(self._val_server,
                          "OK ✓" if device.server_running else "Indisponible",
                          ok=device.server_running)
        _set_status_label(self._val_sms,
                          "OK ✓" if device.sms_permission else "Non",
                          ok=device.sms_permission)
        _set_status_label(self._val_notif,
                          "OK ✓" if device.notification_access else "Non",
                          ok=device.notification_access)

    # ──────────────────────────────────────────────
    # Action handlers
    # ──────────────────────────────────────────────

    def _on_scan_bt(self, _):
        _set_status_label(self._val_bt, "Scan en cours (6s)…", ok=None)

        def worker():
            bt_core.scan_start(6)
            GLib.idle_add(self._refresh_status)

        threading.Thread(target=worker, daemon=True).start()

    def _save_phone_config(self, mac: str, name: str) -> None:
        """Persist the detected phone when it changes.

        ``dataclasses.replace`` préserve tous les autres champs (dont le token
        d'appairage et l'URL du pont Android) — on ne reconstruit jamais la
        config à partir de valeurs par défaut."""
        if not mac:
            return
        # Repart de la config sur disque : l'appairage ou la fenêtre Connexion
        # ont pu la modifier depuis le chargement initial.
        on_disk = load_config()
        next_config = dataclasses.replace(on_disk, phone_mac=mac, phone_name=name)
        if next_config == on_disk and next_config == self._config:
            return
        self._config = next_config
        if next_config != on_disk:
            save_config(next_config)

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

    def _on_open_gallery(self, _):
        gallery = GalleryWindow(parent=self)
        gallery.present()

    def _on_open_sms(self, _):
        if self._sms_window is not None:
            self._sms_window.present()
            return
        sms = SmsWindow(parent=self)
        self._sms_window = sms
        sms.connect("close-request", self._on_sms_closed)
        sms.present()

    def _on_sms_closed(self, *_):
        self._sms_window = None
        return False

    def _on_open_notifications(self, _):
        if self._notif_window is not None:
            self._notif_window.present()
            return
        notifications = NotificationsWindow(parent=self)
        self._notif_window = notifications
        notifications.connect("close-request", self._on_notif_closed)
        notifications.present()

    def _on_notif_closed(self, *_):
        self._notif_window = None
        return False

    # ── Fichiers / Contacts / Connexion (V1.0) ──

    def _on_open_files(self, _):
        if self._files_window is not None:
            self._files_window.present()
            return
        files = FilesWindow(parent=self)
        self._files_window = files
        files.connect("close-request", self._on_files_closed)
        files.present()

    def _on_files_closed(self, *_):
        self._files_window = None
        return False

    def _on_open_contacts(self, _):
        if self._contacts_window is not None:
            self._contacts_window.present()
            return
        contacts = ContactsWindow(parent=self, open_sms=self.open_sms_for_number)
        self._contacts_window = contacts
        contacts.connect("close-request", self._on_contacts_closed)
        contacts.present()

    def _on_contacts_closed(self, *_):
        self._contacts_window = None
        return False

    def open_sms_for_number(self, phone_number: str, contact_name: str = "") -> None:
        """Ouvre la fenêtre Messages préparée pour ``phone_number`` (Contacts).

        Réutilise la fenêtre existante si elle est ouverte ; sinon en crée une.
        ``compose_to`` ouvre le fil existant correspondant au numéro ou passe
        en mode « nouveau message »."""
        if self._sms_window is None:
            sms = SmsWindow(parent=self)
            self._sms_window = sms
            sms.connect("close-request", self._on_sms_closed)
        self._sms_window.compose_to(phone_number, contact_name)

    def _on_open_connection(self, _):
        if self._connection_window is not None:
            self._connection_window.present()
            return
        connection = ConnectionWindow(
            parent=self, on_applied=self._on_connection_applied
        )
        self._connection_window = connection
        connection.connect("close-request", self._on_connection_closed)
        connection.present()

    def _on_connection_closed(self, *_):
        self._connection_window = None
        return False

    def _on_connection_applied(self) -> None:
        """Nouvelle URL de pont appliquée : tout l'écosystème se reconfigure.

        Même chemin qu'après un appairage : backend SMS reconstruit, fenêtres
        ouvertes rechargées, statut rafraîchi (⇒ /v1/health sur la nouvelle
        URL) et écoute temps réel redémarrée."""
        self._config = load_config()
        if self._sms_window is not None:
            try:
                self._sms_window.reload_backend()
            except Exception as exc:  # ne jamais casser l'accueil
                logger.warning("Rechargement backend Messages échoué: %s", exc)
        if self._notif_window is not None:
            self._notif_window.reload_async()
        self._refresh_status()
        self._restart_realtime()

    def _on_open_photos(self, _):
        ok, msg = photos_core.open_local_folder()
        if not ok:
            show_dialog(self, "Erreur", msg, error=True)

    # ── ADB Wi-Fi ──

    def _wifi_host(self) -> str:
        if self._wifi_host_entry is None:
            return ""
        return self._wifi_host_entry.get_text().strip()

    def _save_wifi_config(self, host: str, port: int) -> None:
        """Persist the ADB Wi-Fi host/port when it changes (préserve le reste)."""
        if host == self._config.adb_wifi_host and port == self._config.adb_wifi_port:
            return
        on_disk = load_config()
        self._config = dataclasses.replace(
            on_disk, adb_wifi_host=host, adb_wifi_port=port
        )
        save_config(self._config)

    def _on_wifi_connect(self, _):
        host = self._wifi_host()
        if not host:
            show_dialog(self, "ADB Wi-Fi non configuré",
                        "Renseignez l'adresse IP du téléphone.\n\n"
                        "Activez d'abord TCP/IP via USB, puis saisissez l'IP "
                        "affichée dans les paramètres Wi-Fi du téléphone.",
                        error=True)
            return
        port = self._config.adb_wifi_port

        def worker():
            ok, msg = adb_core.connect_wifi(host, port)
            if ok:
                self._save_wifi_config(host, port)

            def on_done():
                show_dialog(self, "ADB Wi-Fi", msg, error=not ok)
                self._refresh_status()

            GLib.idle_add(on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_wifi_disconnect(self, _):
        host = self._wifi_host() or None
        port = self._config.adb_wifi_port

        def worker():
            ok, msg = adb_core.disconnect_wifi(host, port)

            def on_done():
                show_dialog(self, "ADB Wi-Fi", msg, error=not ok)
                self._refresh_status()

            GLib.idle_add(on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_wifi_enable_tcpip(self, _):
        if not adb_core.is_device_connected():
            show_dialog(self, "ADB USB requis",
                        "Aucun appareil ADB en USB détecté.\n\n"
                        "Branchez le téléphone en USB avec le débogage activé, "
                        "puis réessayez.", error=True)
            return
        port = self._config.adb_wifi_port

        def worker():
            ok, msg = adb_core.enable_tcpip(port)
            ip = adb_core.get_device_ip() if ok else None

            def on_done():
                body = msg
                if ip:
                    body += f"\n\nIP détectée du téléphone : {ip}"
                    if self._wifi_host_entry is not None:
                        self._wifi_host_entry.set_text(ip)
                show_dialog(self, "ADB TCP/IP", body, error=not ok)

            GLib.idle_add(on_done)

        threading.Thread(target=worker, daemon=True).start()

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
    # Appairage Android Companion (Part 1)
    # ──────────────────────────────────────────────

    def _on_pair_android(self, _):
        """Ouvre une boîte de dialogue PIN, appaire et reconfigure le pont.

        Au succès : token persisté en config (via ``pair_and_save``), backend SMS
        rechargé, statut « Téléphone Android » rafraîchi et écoute temps réel
        redémarrée. N'altère pas l'appairage déjà présent dans la fenêtre
        Messages (qui se met aussi à jour si elle est ouverte)."""
        win = Gtk.Window(
            title="Appairer Android Companion", transient_for=self, modal=True
        )
        win.set_default_size(380, -1)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)

        info = Gtk.Label(
            label="Saisissez le PIN affiché par l'app PhoneLink Companion sur le "
                  "téléphone.\nLa connexion locale (port-forward ADB ou réseau) "
                  "doit être active."
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
                    logger.warning("Appairage (accueil) échoué: %s", err)
                    status.set_text(_pair_error_message(err))
                    pair.set_sensitive(True)
                    return False
                logger.info("Appairage (accueil) réussi")
                win.destroy()
                self._after_pairing()
                return False

            threading.Thread(target=worker, daemon=True).start()

        pair.connect("clicked", do_pair)
        entry.connect("activate", do_pair)
        win.present()

    def _after_pairing(self) -> None:
        """Reconfigure tout l'écosystème après un appairage réussi."""
        # La config sur disque a changé (token + mode http) : on resynchronise.
        self._config = load_config()
        # Le backend SMS sera reconstruit (http + nouveau token) au prochain accès.
        sms_core.set_backend(None)
        # Si la fenêtre Messages est ouverte, elle bascule sur le nouveau backend.
        if self._sms_window is not None:
            try:
                self._sms_window.reload_backend()
            except Exception as exc:  # ne jamais casser l'accueil
                logger.warning("Rechargement backend Messages échoué: %s", exc)
        if self._notif_window is not None:
            self._notif_window.reload_async()
        self._refresh_status()
        self._restart_realtime()
        show_dialog(
            self,
            "Appairage Android",
            "Appairage réussi — téléphone Android connecté.\n"
            "Batterie, serveur, SMS et notifications vont se mettre à jour.",
        )

    # ──────────────────────────────────────────────
    # Temps réel : écoute des événements Android (Part 4 & 6)
    # ──────────────────────────────────────────────

    def _start_realtime(self) -> bool:
        """Crée le notifieur bureau et démarre l'écoute si appairé. One-shot."""
        app = self.get_application()
        if app is not None and self._notifier is None:
            self._notifier = event_listener.DesktopNotifier(app)
        if android_bridge.is_realtime_available():
            if self._event_listener.start():
                self._prime_baselines()
        return False  # GLib timeout one-shot

    def _restart_realtime(self) -> None:
        """Redémarre l'écoute (après (ré)appairage) en réamorçant les bases."""
        self._sms_seen.clear()
        if self._event_listener.start():
            self._prime_baselines()

    def _prime_baselines(self) -> None:
        """Mémorise l'état courant (SMS + notifications) **sans** notifier, pour
        ne pas déclencher de notifications bureau pour du contenu déjà présent."""
        def sms_worker() -> None:
            try:
                convos = sms_core.get_backend().list_conversations()
            except Exception:
                convos = []
            GLib.idle_add(self._apply_sms, convos, True)

        def notif_worker() -> None:
            try:
                notifs = android_bridge.list_notifications()
            except Exception:
                notifs = []
            GLib.idle_add(self._apply_notifications, notifs, True)

        threading.Thread(target=sms_worker, daemon=True).start()
        threading.Thread(target=notif_worker, daemon=True).start()

    def _on_android_event(self, event: "android_bridge.BridgeEvent") -> None:
        """Routeur d'événements (appelé sur le thread GTK via GLib.idle_add)."""
        if event.type == android_bridge.EVENT_DEVICE_STATUS_CHANGED:
            self._refresh_status()
        elif event.type == android_bridge.EVENT_NOTIFICATION_CHANGED:
            self._handle_notification_event()
        elif event.type == android_bridge.EVENT_SMS_CHANGED:
            self._handle_sms_event()

    def _on_realtime_auth_required(self) -> None:
        """Token invalide détecté par l'écouteur : on n'en fait pas un drame
        (pas de spam) — un ré-appairage depuis l'accueil suffit."""
        logger.warning("Temps réel: token invalide — ré-appairage requis")

    def _on_close(self, *_):
        """Arrête proprement l'écoute à la fermeture de la fenêtre principale."""
        self._event_listener.stop()
        return False  # laisse la fermeture suivre son cours

    # ── SMS (événement sms_changed) ──

    def _handle_sms_event(self) -> None:
        if self._sms_window is not None:
            self._sms_window.refresh_realtime()
        if self._notifier is None:
            return

        def worker() -> None:
            try:
                convos = sms_core.get_backend().list_conversations()
            except Exception:
                convos = []
            GLib.idle_add(self._apply_sms, convos, False)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_sms(self, convos: list, prime: bool) -> bool:
        """Diffe les conversations et notifie les **nouveaux entrants** (pas en
        mode prime, pas pour les sortants, pas si la fenêtre Messages est active)."""
        active = self._sms_window is not None and self._sms_window.is_active()
        for convo in convos:
            last = convo.last_message
            if last is None:
                continue
            ts = last.timestamp.timestamp() if last.timestamp else 0.0
            prev = self._sms_seen.get(convo.id)
            self._sms_seen[convo.id] = max(prev or 0.0, ts)
            if prime or self._notifier is None or last.outgoing:
                continue
            is_new = prev is None or ts > prev
            if is_new and not active:
                self._notifier.notify(
                    f"sms:{convo.id}:{int(ts)}",
                    "PhoneLink Ubuntu — Nouveau SMS",
                    f"{convo.contact_name} : {last.body}",
                )
        return False  # one-shot

    # ── Notifications Android (événement notification_changed) ──

    def _handle_notification_event(self) -> None:
        if self._notif_window is not None:
            self._notif_window.reload_async()
        if self._notifier is None:
            return

        def worker() -> None:
            try:
                notifs = android_bridge.list_notifications()
            except Exception:
                notifs = []
            GLib.idle_add(self._apply_notifications, notifs, False)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_notifications(self, notifs: list, prime: bool) -> bool:
        """Notifie les **nouvelles** notifications Android (dédupliquées par id).

        En mode prime, ou si la fenêtre Notifications est active, on marque
        seulement comme vues (aucun popup)."""
        if self._notifier is None:
            return False
        active = self._notif_window is not None and self._notif_window.is_active()
        for notif in notifs:
            key = f"notif:{notif.id}"
            if prime or active:
                self._notifier.mark_seen(key)
                continue
            app_label = notif.app_name or notif.package or "Notification"
            title = f"PhoneLink Ubuntu — {app_label}"
            text = notif.big_text or notif.text
            # Corps lisible : « Expéditeur : message » quand les deux existent.
            if notif.title and text:
                body = f"{notif.title} : {text}"
            else:
                body = text or notif.title
            self._notifier.notify(key, title, body)
        return False  # one-shot


# ──────────────────────────────────────────────
# Module-level helpers
# ──────────────────────────────────────────────


def _pair_error_message(exc: Exception) -> str:
    """Message clair selon le type d'échec d'appairage."""
    status = getattr(exc, "status", None)
    if status in (401, 403):
        return "PIN invalide ou expiré. Vérifiez le PIN affiché sur le téléphone."
    if status is None:
        return (
            "Serveur Android indisponible.\n"
            "Vérifiez que l'app compagnon tourne et que la connexion locale "
            "(port-forward ADB ou réseau) est active."
        )
    return f"Échec de l'appairage : {exc}"

_PHONE_KEYWORDS = (
    "s21", "mickael", "samsung", "galaxy", "pixel", "oneplus", "xiaomi",
    "redmi", "poco", "huawei", "honor", "oppo", "realme", "vivo", "nokia",
    "motorola", "moto", "sony", "xperia", "android", "phone",
)


def _find_phone(devices: list, config: PhoneLinkConfig) -> Optional[object]:
    """Identify the user's phone, ignoring non-phone peripherals (e.g. game controllers).

    Returns None rather than guessing when no phone-like device is present, so a
    stray peripheral never gets selected or persisted as the phone.
    """
    # Drop obvious non-phones (controllers, mice, headsets, …) up front.
    candidates = [d for d in devices if not getattr(d, "is_excluded", False)]

    # 1. The MAC the user has been using before — but only if it still looks like
    #    a real device (this also self-heals a config that wrongly captured a
    #    peripheral such as an Xbox controller).
    if config.phone_mac:
        for dev in candidates:
            if dev.mac.upper() == config.phone_mac.upper():
                return dev

    # 2. A device that positively identifies as a phone (bluetoothctl Icon: phone),
    #    preferring one that is currently connected.
    phones = [d for d in candidates if getattr(d, "is_phone", False)]
    for dev in phones:
        if dev.connected:
            return dev
    if phones:
        return phones[0]

    # 3. Fallback when the icon is unavailable: match a known phone name keyword.
    for dev in candidates:
        if any(kw in dev.name.lower() for kw in _PHONE_KEYWORDS):
            return dev

    return None


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
