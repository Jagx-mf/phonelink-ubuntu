"""Découverte du Companion Android sur le réseau local (V1.0, Phase 3).

Permet d'utiliser PhoneLink Ubuntu **sans câble USB ni adb forward** : le
serveur NanoHTTPD du téléphone écoute sur toutes les interfaces (port 8765),
il suffit de connaître son IP. Ce module :

* détecte l'IP locale de la machine Ubuntu (UDP connect, aucun paquet émis) ;
* scanne légèrement le /24 local sur le port du Companion (connexion TCP,
  timeout court, pool de threads borné) ;
* confirme chaque candidat par un ``GET /v1/health`` (endpoint public) et
  remonte le nom de l'appareil.

Tout est synchrone et bloquant — l'UI appelle :func:`scan_network` depuis un
thread d'arrière-plan. Stdlib uniquement (socket, concurrent.futures, urllib).
"""

from __future__ import annotations

import json
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Port du serveur Companion Android.
COMPANION_PORT = 8765

#: Timeout de la tentative TCP par hôte (scan léger).
_TCP_TIMEOUT_S = 0.3

#: Timeout du GET /v1/health de confirmation.
_HEALTH_TIMEOUT_S = 2.0

#: Threads simultanés du scan (un /24 = 253 hôtes → quelques secondes).
_MAX_WORKERS = 64


@dataclass(frozen=True)
class DiscoveredDevice:
    """Un appareil répondant à ``/v1/health`` sur le réseau local."""
    host: str
    port: int
    device: str = ""
    app_version: str = ""

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def get_local_ip() -> Optional[str]:
    """IP locale IPv4 (route par défaut), ou None hors réseau.

    Astuce classique : un ``connect`` UDP ne transmet rien mais force le
    noyau à choisir l'interface de sortie, dont on lit l'adresse.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1.0)
            sock.connect(("192.0.2.1", 80))  # TEST-NET-1 : jamais routé réellement
            return sock.getsockname()[0]
    except OSError:
        return None


def check_health(host: str, port: int = COMPANION_PORT) -> Optional[DiscoveredDevice]:
    """GET ``/v1/health`` (public) sur ``host:port`` ; None si pas un Companion."""
    url = f"http://{host}:{port}/v1/health"
    req = urllib.request.Request(
        url, headers={"User-Agent": "phonelink-ubuntu/scan"}
    )
    try:
        with urllib.request.urlopen(req, timeout=_HEALTH_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("status") != "ok":
        return None
    return DiscoveredDevice(
        host=host,
        port=port,
        device=str(data.get("device", "")),
        app_version=str(data.get("app_version", "")),
    )


def _tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=_TCP_TIMEOUT_S):
            return True
    except OSError:
        return False


def scan_network(
    port: int = COMPANION_PORT,
    progress: Optional[Callable[[int, int], None]] = None,
) -> list[DiscoveredDevice]:
    """Scanne le /24 local sur ``port`` et confirme via ``/v1/health``.

    Bloquant (quelques secondes) : à lancer depuis un thread. ``progress``
    (optionnel) reçoit ``(hôtes_testés, total)`` — appelé depuis les threads
    du pool, l'UI doit repasser par ``GLib.idle_add``.

    Renvoie la liste (possiblement vide) des Companions découverts. Hors
    réseau local, renvoie une liste vide sans lever.
    """
    local_ip = get_local_ip()
    if local_ip is None:
        logger.info("discovery: pas d'IP locale — scan impossible")
        return []
    prefix = local_ip.rsplit(".", 1)[0]
    hosts = [f"{prefix}.{i}" for i in range(1, 255) if f"{prefix}.{i}" != local_ip]

    found: list[DiscoveredDevice] = []
    done = 0

    def probe(host: str) -> Optional[DiscoveredDevice]:
        nonlocal done
        device = check_health(host, port) if _tcp_open(host, port) else None
        done += 1
        if progress is not None:
            try:
                progress(done, len(hosts))
            except Exception:  # le callback ne doit jamais casser le scan
                pass
        return device

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        for result in pool.map(probe, hosts):
            if result is not None:
                found.append(result)

    logger.info(
        "discovery: scan %s.0/24 port %d terminé — %d appareil(s)",
        prefix, port, len(found),
    )
    return found
