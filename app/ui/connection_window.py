"""Fenêtre « Connexion Android » pour PhoneLink Ubuntu (V1.0, Phase 3).

Choix du transport vers l'app compagnon Android, sans câble si souhaité :

* **USB / ADB forward** — ``http://127.0.0.1:8765`` (nécessite
  ``adb forward tcp:8765 tcp:8765``) ;
* **Wi-Fi** — ``http://IP_TELEPHONE:8765`` (IP affichée dans l'app
  PhoneLink Companion, aucun câble requis) ;
* découverte automatique : scan léger du réseau local sur le port 8765
  (cf. :mod:`app.core.discovery`), sans bloquer GTK.

« Tester la connexion » sonde ``/v1/health`` (endpoint public). « Utiliser
cette connexion » persiste ``android_bridge_base_url`` dans ``config.json``,
reconstruit le pont et notifie la fenêtre principale (rafraîchissement du
statut + redémarrage du temps réel). L'appairage PIN reste possible ensuite,
quel que soit le transport.
"""

from __future__ import annotations

import threading
import urllib.parse
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from app.core import android_bridge
from app.core import config as config_core
from app.core import discovery
from app.core import sms as sms_core
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Callback notifié après « Utiliser cette connexion » (la fenêtre principale
#: rafraîchit son statut et relance l'écoute temps réel).
AppliedCallback = Callable[[], None]


def describe_connection_mode(base_url: str) -> str:
    """Libellé du mode selon l'URL configurée (affiché aussi à l'accueil)."""
    host = urllib.parse.urlsplit(base_url or "").hostname or ""
    if host in ("127.0.0.1", "localhost", "::1"):
        return "USB / ADB forward"
    if host:
        return f"Wi-Fi ({host})"
    return "Non configuré"


class ConnectionWindow(Gtk.Window):
    """Configuration et test de la connexion à l'app compagnon Android."""

    def __init__(self, parent: Gtk.Window, on_applied: Optional[AppliedCallback] = None):
        super().__init__(transient_for=parent, modal=False)
        self.set_title("Connexion Android")
        self.set_default_size(520, -1)

        self._on_applied = on_applied
        self._busy = False

        cfg = config_core.load_config()
        current_url = cfg.android_bridge_base_url or config_core.DEFAULT_ANDROID_BRIDGE_URL
        parts = urllib.parse.urlsplit(current_url)
        current_host = parts.hostname or "127.0.0.1"
        current_port = parts.port or discovery.COMPANION_PORT
        is_usb = current_host in ("127.0.0.1", "localhost", "::1")

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(outer)

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        title = Gtk.Label(label="Connexion Android")
        title.add_css_class("title")
        header.set_title_widget(title)
        outer.append(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        outer.append(box)

        self._current_label = Gtk.Label(
            label=f"Connexion actuelle : {describe_connection_mode(current_url)}"
                  f"  —  {current_url}"
        )
        self._current_label.set_xalign(0)
        self._current_label.set_wrap(True)
        self._current_label.add_css_class("dim-label")
        box.append(self._current_label)

        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ── choix du mode ──
        self._radio_usb = Gtk.CheckButton(label="USB / ADB forward (127.0.0.1)")
        self._radio_usb.set_tooltip_text(
            "Câble USB + « adb forward tcp:8765 tcp:8765 »"
        )
        box.append(self._radio_usb)

        self._radio_wifi = Gtk.CheckButton(
            label="Wi-Fi — IP du téléphone (sans câble)"
        )
        self._radio_wifi.set_group(self._radio_usb)
        self._radio_wifi.set_tooltip_text(
            "IP affichée dans l'app PhoneLink Companion (même réseau Wi-Fi)"
        )
        box.append(self._radio_wifi)

        # ── IP + port ──
        grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ip_label = Gtk.Label(label="IP du téléphone :")
        ip_label.add_css_class("dim-label")
        grid.append(ip_label)
        self._ip_entry = Gtk.Entry()
        self._ip_entry.set_placeholder_text("192.168.1.x")
        self._ip_entry.set_hexpand(True)
        if not is_usb:
            self._ip_entry.set_text(current_host)
        grid.append(self._ip_entry)
        port_label = Gtk.Label(label="Port :")
        port_label.add_css_class("dim-label")
        grid.append(port_label)
        self._port_entry = Gtk.Entry()
        self._port_entry.set_text(str(current_port))
        self._port_entry.set_max_length(5)
        self._port_entry.set_width_chars(6)
        grid.append(self._port_entry)
        box.append(grid)

        (self._radio_wifi if not is_usb else self._radio_usb).set_active(True)
        self._radio_usb.connect("toggled", lambda _b: self._update_sensitivity())
        self._ip_entry.connect("changed", lambda _e: self._update_sensitivity())

        # ── actions ──
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._scan_btn = Gtk.Button(label="Rechercher sur le réseau")
        self._scan_btn.set_tooltip_text(
            "Scan léger du réseau local sur le port 8765 (quelques secondes)"
        )
        self._scan_btn.connect("clicked", self._on_scan)
        actions.append(self._scan_btn)

        self._test_btn = Gtk.Button(label="Tester la connexion")
        self._test_btn.connect("clicked", self._on_test)
        actions.append(self._test_btn)

        self._apply_btn = Gtk.Button(label="Utiliser cette connexion")
        self._apply_btn.add_css_class("suggested-action")
        self._apply_btn.connect("clicked", self._on_apply)
        actions.append(self._apply_btn)
        box.append(actions)

        # ── résultats du scan ──
        self._results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(self._results_box)

        # ── statut ──
        self._status = Gtk.Label(label="")
        self._status.set_xalign(0)
        self._status.set_wrap(True)
        box.append(self._status)

        hint = Gtk.Label(
            label="Astuce : la synchronisation sans câble passe par le Wi-Fi "
                  "(même réseau local). Le Bluetooth reste réservé à l'audio. "
                  "Après un changement de connexion, l'appairage PIN reste "
                  "possible depuis la fenêtre principale."
        )
        hint.set_xalign(0)
        hint.set_wrap(True)
        hint.add_css_class("dim-label")
        hint.add_css_class("caption")
        box.append(hint)

        self._update_sensitivity()

    # ── état des contrôles ───────────────────────────

    def _update_sensitivity(self) -> None:
        wifi = self._radio_wifi.get_active()
        self._ip_entry.set_sensitive(wifi and not self._busy)
        self._port_entry.set_sensitive(not self._busy)
        self._scan_btn.set_sensitive(not self._busy)
        has_target = not wifi or bool(self._ip_entry.get_text().strip())
        self._test_btn.set_sensitive(has_target and not self._busy)
        self._apply_btn.set_sensitive(has_target and not self._busy)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        if message:
            self._status.set_text(message)
        self._update_sensitivity()

    def _candidate_url(self) -> Optional[str]:
        """URL candidate selon le mode/les champs, ou None si invalide."""
        port_text = self._port_entry.get_text().strip() or str(discovery.COMPANION_PORT)
        if not port_text.isdigit() or not (1 <= int(port_text) <= 65535):
            self._status.set_text("Port invalide (1–65535).")
            return None
        port = int(port_text)
        if self._radio_usb.get_active():
            return f"http://127.0.0.1:{port}"
        host = self._ip_entry.get_text().strip()
        if not host:
            self._status.set_text("Saisissez l'IP du téléphone (ou lancez le scan).")
            return None
        return f"http://{host}:{port}"

    # ── test de connexion ────────────────────────────

    def _on_test(self, _btn: Gtk.Button) -> None:
        url = self._candidate_url()
        if url is None:
            return
        parts = urllib.parse.urlsplit(url)
        self._set_busy(True, f"Test de {url}…")

        def worker() -> None:
            device = discovery.check_health(
                parts.hostname or "", parts.port or discovery.COMPANION_PORT
            )
            GLib.idle_add(on_done, device)

        def on_done(device) -> bool:
            self._set_busy(False)
            if device is None:
                self._status.set_text(
                    f"Aucune réponse de {url}.\n"
                    "Vérifiez que le serveur est démarré dans l'app PhoneLink "
                    "Companion et que le téléphone est sur le même réseau "
                    "(ou que le port-forward ADB est actif)."
                )
            else:
                name = device.device or "Companion"
                version = f" v{device.app_version}" if device.app_version else ""
                self._status.set_text(f"Connexion OK — {name}{version} répond sur {url}.")
            return False  # one-shot

        threading.Thread(target=worker, daemon=True).start()

    # ── application ──────────────────────────────────

    def _on_apply(self, _btn: Gtk.Button) -> None:
        url = self._candidate_url()
        if url is None:
            return
        cfg = config_core.load_config()
        cfg.android_bridge_base_url = url
        config_core.save_config(cfg)
        logger.info("Connexion Android: base URL persistée → %s", url)

        # Reconstruit le pont et le backend SMS sur la nouvelle URL (le token
        # d'appairage persiste : il reste valable quel que soit le transport).
        android_bridge.set_bridge(None)
        sms_core.set_backend(None)

        self._current_label.set_label(
            f"Connexion actuelle : {describe_connection_mode(url)}  —  {url}"
        )
        token_hint = (
            "" if cfg.android_bridge_token
            else "\nPensez à appairer l'app compagnon (PIN) depuis la fenêtre "
                 "principale pour accéder aux SMS, fichiers et contacts."
        )
        self._status.set_text(f"Connexion enregistrée : {url}{token_hint}")
        if self._on_applied is not None:
            try:
                self._on_applied()
            except Exception as exc:  # le callback ne doit jamais casser la fenêtre
                logger.warning("Connexion: callback on_applied a levé: %s", exc)

    # ── scan réseau ──────────────────────────────────

    def _on_scan(self, _btn: Gtk.Button) -> None:
        self._clear_results()
        port_text = self._port_entry.get_text().strip()
        port = int(port_text) if port_text.isdigit() else discovery.COMPANION_PORT
        self._set_busy(True, "Scan du réseau local en cours (quelques secondes)…")

        def progress(done: int, total: int) -> None:
            if done % 32 == 0 or done == total:
                GLib.idle_add(
                    self._status.set_text,
                    f"Scan du réseau local… {done}/{total} hôtes testés",
                )

        def worker() -> None:
            try:
                devices = discovery.scan_network(port=port, progress=progress)
            except Exception as exc:  # robustesse : jamais de crash UI
                logger.warning("Connexion: scan échoué: %s", exc)
                devices = []
            GLib.idle_add(on_done, devices)

        def on_done(devices: list) -> bool:
            self._set_busy(False)
            if not devices:
                self._status.set_text(
                    "Aucun appareil PhoneLink Companion détecté sur le réseau.\n"
                    "Vérifiez que le serveur est démarré sur le téléphone et "
                    "que les deux appareils sont sur le même Wi-Fi."
                )
                return False
            self._status.set_text(
                f"{len(devices)} appareil(s) détecté(s) — cliquez pour utiliser :"
            )
            for device in devices:
                label = device.device or device.host
                version = f" v{device.app_version}" if device.app_version else ""
                btn = Gtk.Button(
                    label=f"{label}{version} — {device.host}:{device.port}"
                )
                btn.connect(
                    "clicked",
                    lambda _b, d=device: self._use_discovered(d),
                )
                self._results_box.append(btn)
            return False  # one-shot

        threading.Thread(target=worker, daemon=True).start()

    def _use_discovered(self, device: "discovery.DiscoveredDevice") -> None:
        self._radio_wifi.set_active(True)
        self._ip_entry.set_text(device.host)
        self._port_entry.set_text(str(device.port))
        self._status.set_text(
            f"Appareil sélectionné : {device.host}:{device.port} — testez puis "
            "« Utiliser cette connexion »."
        )
        self._update_sensitivity()

    def _clear_results(self) -> None:
        child = self._results_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._results_box.remove(child)
            child = nxt
