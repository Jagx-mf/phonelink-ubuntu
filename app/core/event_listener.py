"""Écoute temps réel des événements Android côté Ubuntu (V0.9).

Ce module fait le pont entre le endpoint Android ``GET /v1/events`` (long polling,
cf. ``EventBus.kt``) et l'UI GTK. Il évite à l'utilisateur de cliquer sur
« Rafraîchir » : un thread d'arrière-plan interroge ``/events`` en boucle et
réinjecte chaque événement **sur le thread GTK** via ``GLib.idle_add``.

Deux objets :

* :class:`AndroidEventListener` — le thread d'écoute (démarrage/arrêt propres,
  backoff réseau, gestion du token invalide sans spam) ;
* :class:`DesktopNotifier` — affiche des notifications bureau natives, avec dédup.
  Délivrance **fiable** via ``notify-send`` (vérifié par ``shutil.which`` et
  lancé sans ``shell=True``) ; repli sur ``Gio.Notification`` si ``notify-send``
  est absent. ``Gtk.Application.send_notification`` seul est peu fiable sur GNOME
  quand aucun fichier ``.desktop`` ne correspond à l'``application_id`` (la
  notification est silencieusement ignorée), d'où le choix de ``notify-send``.

Aucune dépendance lourde : uniquement la bibliothèque standard + ``GLib``/``Gio``
(déjà présents). Le module ne touche jamais directement aux widgets : il appelle
des callbacks fournis par l'UI.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections import OrderedDict
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gio

from app.core import android_bridge
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AndroidEventListener:
    """Thread d'écoute long polling de ``/v1/events``.

    Usage :

        listener = AndroidEventListener(on_event=handle, on_auth_error=warn)
        listener.start()   # no-op si non appairé (mock / pas de token)
        ...
        listener.stop()    # à la fermeture de l'application

    ``on_event(event: BridgeEvent)`` est appelé **sur le thread GTK**. Il ne doit
    donc pas être bloquant : déléguer tout travail réseau à un thread.

    ``on_auth_error()`` (optionnel) est appelé **une seule fois** sur le thread
    GTK si le serveur répond 401/403 (token invalide) : l'UI peut afficher
    « appairage requis » sans que le thread ne spamme le serveur.
    """

    #: Timeout de long polling demandé au serveur (borné côté Android à 20–30 s).
    POLL_TIMEOUT_MS = 25_000

    #: Attente après une erreur réseau (serveur indisponible) avant de réessayer.
    BACKOFF_NETWORK_S = 5.0

    def __init__(
        self,
        on_event: Callable[["android_bridge.BridgeEvent"], None],
        on_auth_error: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_event = on_event
        self._on_auth_error = on_auth_error
        self._thread: Optional[threading.Thread] = None
        #: Event d'arrêt du thread courant. Chaque thread capture le sien : un
        #: redémarrage crée un nouvel Event, l'ancien thread s'arrête seul.
        self._stop: Optional[threading.Event] = None

    # ── cycle de vie ─────────────────────────────────

    def start(self) -> bool:
        """Démarre (ou redémarre) l'écoute. Renvoie True si un thread a démarré.

        No-op si le pont n'est pas appairé en HTTP (rien à écouter) : renvoie
        False. Idempotent : un appel pendant qu'un thread tourne le remplace
        proprement.
        """
        self.stop()  # signale tout thread précédent
        if not android_bridge.is_realtime_available():
            logger.info("EventListener: non appairé (HTTP+token) — écoute non démarrée")
            return False
        stop = threading.Event()
        self._stop = stop
        thread = threading.Thread(
            target=self._run, args=(stop,), name="android-events", daemon=True
        )
        self._thread = thread
        thread.start()
        logger.info("EventListener: thread d'écoute démarré")
        return True

    def stop(self) -> None:
        """Demande l'arrêt du thread courant (non bloquant).

        Le thread peut rester bloqué jusqu'à la fin de sa requête long polling
        en cours (≤ ~35 s) avant de constater l'arrêt ; comme il est *daemon*,
        il n'empêche pas la fermeture de l'application.
        """
        if self._stop is not None:
            self._stop.set()
        self._thread = None
        self._stop = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── boucle ───────────────────────────────────────

    def _run(self, stop: threading.Event) -> None:
        # since = -1 → resynchro initiale : le serveur renvoie son last_event_id
        # courant sans rejouer l'historique (pas de notifications fantômes au
        # démarrage). On ne reçoit ensuite que les NOUVEAUX événements.
        since = -1
        auth_failed = False
        while not stop.is_set():
            try:
                events, last_event_id = android_bridge.list_events(
                    since=since, timeout_ms=self.POLL_TIMEOUT_MS
                )
            except android_bridge.BridgeError as exc:
                if exc.status in (401, 403):
                    # Token invalide : prévenir une fois puis arrêter (pas de spam).
                    logger.warning("EventListener: token invalide (%s) — arrêt", exc)
                    if self._on_auth_error is not None and not auth_failed:
                        auth_failed = True
                        GLib.idle_add(self._safe_call, self._on_auth_error)
                    return
                # Serveur indisponible / réseau : backoff puis retry.
                logger.debug("EventListener: /events indisponible (%s) — retry", exc)
                if stop.wait(self.BACKOFF_NETWORK_S):
                    return
                continue
            except Exception as exc:  # robustesse : ne jamais tuer le thread
                logger.warning("EventListener: erreur inattendue: %s", exc)
                if stop.wait(self.BACKOFF_NETWORK_S):
                    return
                continue

            since = last_event_id
            for event in events:
                if stop.is_set():
                    return
                GLib.idle_add(self._safe_call, self._on_event, event)
        logger.info("EventListener: thread d'écoute arrêté")

    @staticmethod
    def _safe_call(func: Callable, *args) -> bool:
        """Exécute un callback UI en avalant toute exception (jamais re-planifié)."""
        try:
            func(*args)
        except Exception as exc:  # un callback UI ne doit jamais tuer la boucle GLib
            logger.warning("EventListener: callback UI a levé: %s", exc)
        return False  # GLib.idle_add one-shot


class DesktopNotifier:
    """Notifications bureau natives, sobres et dédupliquées.

    Délivrance **fiable** : ``notify-send`` en priorité (validé terrain),
    ``Gio.Notification`` en repli. La dédup (clé ``key``) évite les doublons lors
    de rafraîchissements successifs. Ne lève jamais.
    """

    #: Nombre de clés mémorisées (anti-doublon) avant purge des plus anciennes.
    _MAX_SEEN = 256

    #: Nom d'application affiché par ``notify-send`` (et icône thématique sobre).
    _APP_NAME = "PhoneLink Ubuntu"
    _ICON = "phone-symbolic"

    def __init__(self, app) -> None:
        self._app = app
        self._seen: "OrderedDict[str, None]" = OrderedDict()
        # Résolu une fois : chemin absolu de notify-send, ou None si absent.
        self._notify_send = shutil.which("notify-send")
        if self._notify_send is None:
            logger.info(
                "DesktopNotifier: notify-send introuvable — repli sur Gio.Notification"
            )
        else:
            logger.info("DesktopNotifier: notify-send détecté (%s)", self._notify_send)

    def notify(self, key: str, title: str, body: str) -> None:
        """Affiche une notification bureau si ``key`` n'a pas déjà été vue.

        ``key`` identifie le contenu (p. ex. ``"sms:<conv>:<timestamp>"``) pour
        ne notifier qu'une fois. Ne lève jamais.
        """
        if not key or key in self._seen:
            return
        self._remember(key)
        self._deliver(title or self._APP_NAME, body or "")

    def _deliver(self, title: str, body: str) -> None:
        """Tente notify-send (fiable) puis Gio.Notification. Ne lève jamais."""
        # 1) notify-send — chemin fiable, sans shell=True, ne crashe pas si absent.
        if self._notify_send is not None:
            try:
                subprocess.run(
                    [
                        self._notify_send,
                        "-a", self._APP_NAME,
                        "-i", self._ICON,
                        title,
                        body,
                    ],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                logger.info(
                    "DesktopNotifier: notification bureau envoyée (notify-send): %r",
                    title,
                )
                return
            except Exception as exc:  # binaire cassé, timeout… → on tente Gio
                logger.warning(
                    "DesktopNotifier: notify-send a échoué (%s) — repli Gio", exc
                )

        # 2) Gio.Notification — repli (peut être ignoré par GNOME sans .desktop).
        try:
            notification = Gio.Notification.new(title)
            if body:
                notification.set_body(body)
            # id=None : notification transitoire (non conservée/retirable côté app).
            self._app.send_notification(None, notification)
            logger.info(
                "DesktopNotifier: notification bureau envoyée (Gio): %r", title
            )
        except Exception as exc:
            logger.warning("DesktopNotifier: envoi notification bureau impossible (%s)", exc)

    def mark_seen(self, key: str) -> None:
        """Marque ``key`` comme déjà vue **sans** afficher de notification.

        Utilisé pour amorcer l'état au démarrage (contenu déjà présent) ou quand
        la fenêtre concernée est active : on ne veut pas de popup, mais on doit
        éviter d'en afficher un plus tard pour le même contenu."""
        if key:
            self._remember(key)

    def _remember(self, key: str) -> None:
        self._seen[key] = None
        while len(self._seen) > self._MAX_SEEN:
            self._seen.popitem(last=False)
