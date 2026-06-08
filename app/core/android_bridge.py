"""Client de l'app compagnon Android — couche transport (V0.4, mockable).

Ce module est le **client HTTP local** qui interrogera l'application compagnon
Android décrite dans ``docs/android-backend-v0.4.md``. En V0.4 il fonctionne en
mode **mock** : aucune connexion réseau réelle n'est faite, des données fictives
sont renvoyées pour permettre de développer et tester la couche Ubuntu avant que
l'app Android n'existe.

Le transport HTTP local est maintenant implémenté (``BridgeMode.HTTP``) avec la
**bibliothèque standard uniquement** (``urllib``) — aucune dépendance PyPI. Le
mode ``MOCK`` reste le défaut et n'est jamais cassé : passer en HTTP se fait par
paramètre (``mode=BridgeMode.HTTP``) ou via la variable d'environnement
``PHONELINK_BRIDGE_MODE``.

Les fonctions de commodité au niveau module (``check_health``,
``list_conversations``, ``list_messages``, ``send_message``) opèrent sur un pont
singleton, à l'image de ``get_backend()`` dans ``app/core/sms.py``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

#: URL de base par défaut : port-forward ADB recommandé (cf. doc §1).
DEFAULT_BASE_URL = "http://127.0.0.1:8765"

#: Préfixe de version de l'API locale.
API_PREFIX = "/v1"

#: En-tête User-Agent envoyé à l'app compagnon.
USER_AGENT = "phonelink-ubuntu/0.4"

#: Variable d'environnement pour forcer le mode du pont (mock | http).
ENV_MODE = "PHONELINK_BRIDGE_MODE"

#: Variable d'environnement pour la base URL en mode HTTP.
ENV_BASE_URL = "PHONELINK_BRIDGE_URL"

#: Variable d'environnement pour le token Bearer.
ENV_TOKEN = "PHONELINK_BRIDGE_TOKEN"

#: Variable d'environnement pour autoriser l'envoi réel de SMS (V0.5, opt-in).
#: Vaut faux par défaut : le garde-fou ``allow_real_send`` reste actif tant que
#: cette variable n'est pas explicitement positionnée à ``1``/``true``/``yes``.
ENV_ALLOW_SEND = "PHONELINK_BRIDGE_ALLOW_SEND"


class BridgeMode(str, Enum):
    """Mode de fonctionnement du pont."""
    MOCK = "mock"   # données fictives, aucun réseau (V0.4)
    HTTP = "http"   # app compagnon réelle via HTTP local


class BridgeError(Exception):
    """Échec d'une requête vers l'app compagnon (réseau, HTTP, ou JSON).

    Porte un ``status`` HTTP optionnel (``None`` si l'erreur est survenue avant
    d'obtenir une réponse, p. ex. connexion refusée ou timeout).
    """

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


# ──────────────────────────────────────────────
# Objets de réponse
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class HealthStatus:
    """Réponse de ``GET /health`` — disponibilité et capacités réelles."""
    reachable: bool                 # le serveur a répondu
    sms_permission: bool = False    # READ_SMS + SEND_SMS accordées
    default_sms_app: bool = False
    notification_access: bool = False  # accès aux notifications (RCS) accordé
    app_version: str = ""
    device: str = ""
    detail: str = ""                # message lisible pour l'UI

    @property
    def usable(self) -> bool:
        """True seulement si on peut réellement lire/envoyer des SMS."""
        return self.reachable and self.sms_permission


@dataclass(frozen=True)
class BridgeMessage:
    """Un SMS tel que renvoyé par l'API (miroir de ``sms.Message``)."""
    body: str
    timestamp: datetime
    outgoing: bool
    sender: str = ""


@dataclass(frozen=True)
class RcsThread:
    """Fil RCS capté via les notifications (``GET /rcs/messages``).

    Contrairement à une conversation SMS, le fil porte directement ses messages
    (pas de second appel) : la fenêtre disponible est de toute façon limitée à ce
    que les notifications ont laissé voir (cf. ``docs/rcs-v0.6.md``).
    """
    id: str
    contact_name: str
    messages: list["BridgeMessage"]


@dataclass(frozen=True)
class DeviceStatus:
    """État du téléphone renvoyé par ``GET /device/status`` (V0.8).

    ``reachable`` est faux si l'endpoint est indisponible (mode mock, téléphone
    non connecté, token invalide…) : l'UI peut alors afficher un statut neutre
    sans planter. ``battery_level`` vaut ``-1`` quand le niveau est inconnu.
    """
    reachable: bool
    battery_level: int = -1
    battery_charging: bool = False
    battery_status: str = ""
    device: str = ""
    server_running: bool = False
    sms_permission: bool = False
    notification_access: bool = False
    default_sms_app: bool = False
    detail: str = ""


@dataclass(frozen=True)
class AndroidNotification:
    """Une notification Android active renvoyée par ``GET /notifications`` (V0.8).

    Lecture seule, proche de Microsoft Phone Link : aucune réponse ni action
    ``RemoteInput``.
    """
    id: str
    package: str
    app_name: str
    title: str
    text: str
    big_text: str
    timestamp: Optional[datetime]
    is_clearable: bool


#: Types d'événements temps réel (contrat partagé avec EventBus.kt côté Android).
EVENT_NOTIFICATION_CHANGED = "notification_changed"
EVENT_SMS_CHANGED = "sms_changed"
EVENT_DEVICE_STATUS_CHANGED = "device_status_changed"


@dataclass(frozen=True)
class BridgeEvent:
    """Un événement temps réel renvoyé par ``GET /events`` (long polling, V0.9).

    ``id`` est incrémental (monotone côté serveur tant que le service tourne).
    ``type`` vaut l'un des ``EVENT_*`` ci-dessus (d'autres types futurs sont
    tolérés et simplement ignorés par l'UI). ``payload`` est un dict minimal
    optionnel — l'UI recharge ensuite les endpoints concernés.
    """
    id: int
    type: str
    timestamp: Optional[datetime]
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BridgeConversation:
    """Résumé de conversation renvoyé par ``GET /conversations``."""
    id: str
    contact_name: str
    phone_number: str
    last_message: str = ""
    last_timestamp: Optional[datetime] = None
    last_outgoing: bool = False  # direction du dernier message (V0.9)
    unread: int = 0


@dataclass(frozen=True)
class SendResult:
    """Résultat de ``POST /send``."""
    sent: bool                      # True = SMS réellement transmis
    detail: str = ""
    message: Optional[BridgeMessage] = None


# ──────────────────────────────────────────────
# Le pont
# ──────────────────────────────────────────────

class AndroidBridge:
    """Client de l'app compagnon Android.

    En mode ``MOCK`` (défaut), toutes les méthodes renvoient des données
    fictives sans aucun appel réseau. En mode ``HTTP``, les lectures (``health``,
    ``conversations``, ``messages``) passent par :meth:`_request` (urllib, stdlib).

    Garde-fou V0.4 : l'**envoi réel** de SMS est désactivé par défaut
    (``allow_real_send=False``) même en mode HTTP — ``send_message`` ne poste
    jamais ``/send`` tant que ce drapeau n'est pas explicitement activé.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        token: Optional[str] = None,
        mode: BridgeMode = BridgeMode.MOCK,
        timeout: float = 5.0,
        allow_real_send: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.mode = mode
        self.timeout = timeout
        self.allow_real_send = allow_real_send
        self._mock = _MockData()

    # ----- API publique --------------------------------------------------

    def check_health(self) -> HealthStatus:
        """Sonder le service compagnon (``GET /health``)."""
        if self.mode is BridgeMode.MOCK:
            logger.debug("android_bridge: check_health (mock)")
            return HealthStatus(
                reachable=False,
                sms_permission=False,
                notification_access=False,
                detail="Mode démo — aucune app compagnon Android connectée",
            )
        try:
            data = self._request("GET", "/health")
        except BridgeError as exc:
            logger.warning("android_bridge: health KO — %s", exc)
            raise
        status = HealthStatus(
            reachable=True,
            sms_permission=bool(data.get("sms_permission", False)),
            default_sms_app=bool(data.get("default_sms_app", False)),
            notification_access=bool(data.get("notification_access", False)),
            app_version=str(data.get("app_version", "")),
            device=str(data.get("device", "")),
            detail="Connecté",
        )
        logger.info(
            "android_bridge: health OK — device=%r version=%s sms_permission=%s",
            status.device, status.app_version, status.sms_permission,
        )
        return status

    def list_conversations(self) -> list[BridgeConversation]:
        """Lister les conversations (``GET /conversations``)."""
        if self.mode is BridgeMode.MOCK:
            logger.debug("android_bridge: list_conversations (mock)")
            return self._mock.conversations()
        data = self._request("GET", "/conversations")
        return [_parse_conversation(c) for c in data.get("conversations", [])]

    def list_messages(self, conversation_id: str) -> list[BridgeMessage]:
        """Lister les messages d'une conversation (``GET /messages``)."""
        if self.mode is BridgeMode.MOCK:
            logger.debug("android_bridge: list_messages %s (mock)", conversation_id)
            return self._mock.messages(conversation_id)
        data = self._request(
            "GET", "/messages", params={"conversation_id": conversation_id}
        )
        return [_parse_message(m) for m in data.get("messages", [])]

    def list_rcs(self) -> list[RcsThread]:
        """Lister les fils RCS captés via notifications (``GET /rcs/messages``).

        En mode mock, renvoie une liste vide (aucune notification réelle). En
        HTTP, parse ``{ "conversations": [ {id, contact_name, messages:[…]} ] }``.
        Ne lève jamais : un échec réseau renvoie une liste vide (le RCS est un
        complément, il ne doit pas casser l'affichage des SMS).
        """
        if self.mode is BridgeMode.MOCK:
            return []
        try:
            data = self._request("GET", "/rcs/messages")
        except BridgeError as exc:
            logger.warning("android_bridge: /rcs/messages indisponible: %s", exc)
            return []
        return [_parse_rcs_thread(t) for t in data.get("conversations", [])]

    def get_device_status(self) -> DeviceStatus:
        """Lire batterie + statut téléphone (``GET /device/status``, V0.8).

        Ne lève **jamais** : en mode mock ou si l'endpoint est indisponible
        (téléphone déconnecté, token invalide, version Android sans cet
        endpoint…), renvoie ``DeviceStatus(reachable=False, …)`` pour que l'UI
        reste affichable.
        """
        if self.mode is BridgeMode.MOCK:
            return DeviceStatus(
                reachable=False,
                detail="Mode démo — aucune app compagnon Android connectée",
            )
        try:
            data = self._request("GET", "/device/status")
        except BridgeError as exc:
            logger.warning("android_bridge: /device/status indisponible: %s", exc)
            return DeviceStatus(reachable=False, detail=str(exc))
        return _parse_device_status(data)

    def list_notifications(self) -> list[AndroidNotification]:
        """Lister les notifications Android actives (``GET /notifications``, V0.8).

        Lecture seule. En mode mock, renvoie une liste vide. En HTTP, lève
        :class:`BridgeError` sur erreur de transport (l'UI affiche alors un
        message clair) ; une réponse ``listener_not_connected`` donne une liste
        vide. Aucune action ``RemoteInput``.
        """
        if self.mode is BridgeMode.MOCK:
            return []
        data = self._request("GET", "/notifications")
        return [_parse_notification(n) for n in data.get("notifications", [])]

    #: Marge ajoutée au timeout réseau au-delà du ``timeout_ms`` serveur, pour
    #: que urllib ne coupe jamais une attente long polling encore en cours.
    EVENTS_NETWORK_MARGIN_S = 10.0

    def list_events(
        self, since: int = -1, timeout_ms: int = 25_000
    ) -> tuple[list[BridgeEvent], int]:
        """Long polling temps réel (``GET /events``, V0.9).

        Renvoie ``(events, last_event_id)`` : les événements d'id > ``since``,
        et le dernier id connu du serveur (à repasser en ``since`` au tour
        suivant). ``since < 0`` demande une **resynchro initiale** (le serveur
        renvoie une liste vide + son ``last_event_id`` courant).

        En mode ``MOCK``, renvoie ``([], max(since, 0))`` sans réseau. En HTTP,
        peut lever :class:`BridgeError` (réseau/HTTP/token) — l'appelant (thread
        d'écoute GTK) gère le retry/backoff et ne crashe jamais l'UI.
        """
        if self.mode is BridgeMode.MOCK:
            return [], max(since, 0)

        # Le serveur garde la connexion ouverte jusqu'à ``timeout_ms`` : le
        # timeout réseau doit lui laisser de la marge, sinon urllib couperait
        # l'attente et on enchaînerait des reconnexions inutiles.
        net_timeout = timeout_ms / 1000.0 + self.EVENTS_NETWORK_MARGIN_S
        data = self._request(
            "GET",
            "/events",
            params={"since": since, "timeout_ms": timeout_ms},
            timeout=net_timeout,
        )
        events = [_parse_event(e) for e in data.get("events", [])]
        try:
            last_event_id = int(data.get("last_event_id", since))
        except (ValueError, TypeError):
            last_event_id = max(since, 0)
        return events, last_event_id

    def send_message(
        self,
        body: str,
        conversation_id: Optional[str] = None,
        phone_number: Optional[str] = None,
    ) -> SendResult:
        """Envoyer un SMS (``POST /send``).

        Fournir ``conversation_id`` (fil existant) **ou** ``phone_number``
        (nouveau fil). En mode mock, rien n'est transmis.
        """
        body = body.strip()
        if not body:
            return SendResult(sent=False, detail="Message vide")
        if not conversation_id and not phone_number:
            return SendResult(
                sent=False, detail="conversation_id ou phone_number requis"
            )

        if self.mode is BridgeMode.MOCK:
            logger.info(
                "android_bridge: send_message (mock) → %s%s: %r",
                conversation_id or "", phone_number or "", body,
            )
            echo = BridgeMessage(body=body, timestamp=datetime.now(), outgoing=True)
            return SendResult(
                sent=False,
                detail="Message simulé — app compagnon Android requise",
                message=echo,
            )

        # Garde-fou V0.4 : ne jamais transmettre un vrai SMS tant que l'envoi
        # réel n'est pas explicitement autorisé, même connecté en HTTP.
        if not self.allow_real_send:
            logger.info(
                "android_bridge: send_message bloqué (allow_real_send=False) → %s%s",
                conversation_id or "", phone_number or "",
            )
            echo = BridgeMessage(body=body, timestamp=datetime.now(), outgoing=True)
            return SendResult(
                sent=False,
                detail="Envoi réel désactivé (allow_real_send=False)",
                message=echo,
            )

        payload: dict[str, str] = {"body": body}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if phone_number:
            payload["phone_number"] = phone_number
        data = self._request("POST", "/send", json_body=payload)
        raw_msg = data.get("message")
        return SendResult(
            sent=bool(data.get("sent", False)),
            detail=str(data.get("error") or data.get("detail") or ""),
            message=_parse_message(raw_msg) if raw_msg else None,
        )

    def pair(self, pin: str) -> str:
        """S'appairer avec l'app compagnon (``POST /v1/pair``).

        Échange le **code PIN** affiché par l'app Android contre un **token**
        Bearer persistant (cf. ``docs/android-backend-v0.4.md`` §5). Sur succès,
        ``self.token`` est mis à jour et le token est renvoyé.

        L'appairage est une opération réseau réelle : elle s'effectue quel que
        soit ``self.mode`` (il n'y a rien à simuler côté mock).

        Lève :class:`BridgeError` si :

        - le PIN est vide ;
        - le serveur répond 401/403 (PIN invalide/expiré) ou tout autre statut ;
        - la réponse n'est pas un JSON valide ;
        - la réponse ne contient pas de ``token`` exploitable ;
        - le serveur est injoignable (timeout, connexion refusée).
        """
        pin = (pin or "").strip()
        if not pin:
            raise BridgeError("PIN vide")

        # _request convertit déjà réseau/HTTP/JSON en BridgeError (avec status).
        data = self._request(
            "POST", "/pair", json_body={"pin": pin, "client": USER_AGENT}
        )
        token = data.get("token")
        if not token or not isinstance(token, str):
            raise BridgeError("Réponse d'appairage sans token exploitable")

        self.token = token
        logger.info("android_bridge: appairage réussi (token reçu)")
        return token

    # ----- transport HTTP (urllib, stdlib) -------------------------------

    def _build_url(self, path: str, params: Optional[dict]) -> str:
        """Construire ``base_url + API_PREFIX + path`` avec query-string encodée."""
        url = self.base_url + API_PREFIX + "/" + path.lstrip("/")
        if params:
            # Ignore les paramètres None ; encode proprement le reste.
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        return url

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        """Effectuer une requête HTTP JSON vers l'app compagnon (stdlib only).

        - ``method`` : ``"GET"`` ou ``"POST"``.
        - ``params`` : query-string (GET) ; les valeurs ``None`` sont ignorées.
        - ``json_body`` : corps JSON (POST).
        - ``timeout`` : délai réseau spécifique (défaut ``self.timeout``). Le long
          polling ``/events`` passe ici une valeur > ``timeout_ms`` pour ne pas
          couper l'attente côté serveur.

        Ajoute ``Authorization: Bearer <token>`` si un token est présent, applique
        le timeout, et renvoie le JSON décodé (toujours un ``dict`` :
        une réponse vide donne ``{}``).

        Lève :class:`BridgeError` pour toute erreur réseau, HTTP (4xx/5xx) ou
        JSON invalide — jamais d'exception ``urllib`` brute ne remonte.
        """
        url = self._build_url(path, params)

        data: Optional[bytes] = None
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(
            url, data=data, headers=headers, method=method.upper()
        )
        logger.debug("android_bridge: %s %s", method.upper(), url)

        try:
            with urllib.request.urlopen(
                req, timeout=timeout if timeout is not None else self.timeout
            ) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            # Réponse reçue mais statut d'erreur (4xx/5xx). Le corps peut porter
            # un message JSON ({"error": ...}) qu'on remonte si présent.
            body = b""
            try:
                body = exc.read()
            except Exception:  # pragma: no cover - lecture best-effort
                pass
            detail = _extract_error(body) or exc.reason or "erreur HTTP"
            raise BridgeError(
                f"HTTP {exc.code} sur {path}: {detail}", status=exc.code
            ) from exc
        except urllib.error.URLError as exc:
            # Pas de réponse : connexion refusée, DNS, timeout réseau, etc.
            raise BridgeError(
                f"Connexion impossible à {self.base_url}: {exc.reason}"
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise BridgeError(f"Erreur réseau vers {self.base_url}: {exc}") from exc

        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BridgeError(f"Réponse JSON invalide sur {path}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise BridgeError(
                f"Réponse JSON inattendue sur {path}: objet attendu, "
                f"reçu {type(parsed).__name__}"
            )
        return parsed


# ──────────────────────────────────────────────
# Parsing JSON → dataclasses
# ──────────────────────────────────────────────

def _extract_error(body: bytes) -> str:
    """Extraire un message d'erreur d'un corps de réponse JSON, si possible."""
    if not body:
        return ""
    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""
    if isinstance(data, dict):
        return str(data.get("error") or data.get("detail") or "")
    return ""


def _epoch_ms_to_dt(value: object) -> Optional[datetime]:
    """Convertir un epoch en millisecondes (entier) en ``datetime`` local."""
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000)
    except (ValueError, TypeError, OverflowError, OSError):
        logger.warning("android_bridge: horodatage invalide: %r", value)
        return None


def _parse_message(raw: dict) -> BridgeMessage:
    return BridgeMessage(
        body=str(raw.get("body", "")),
        timestamp=_epoch_ms_to_dt(raw.get("timestamp")) or datetime.now(),
        outgoing=bool(raw.get("outgoing", False)),
        sender=str(raw.get("sender", "")),
    )


def _parse_rcs_thread(raw: dict) -> RcsThread:
    return RcsThread(
        id=str(raw.get("id", "")),
        contact_name=str(raw.get("contact_name", "")),
        messages=[_parse_message(m) for m in raw.get("messages", [])],
    )


def _parse_device_status(raw: dict) -> DeviceStatus:
    try:
        level = int(raw.get("battery_level", -1))
    except (ValueError, TypeError):
        level = -1
    return DeviceStatus(
        reachable=True,
        battery_level=level,
        battery_charging=bool(raw.get("battery_charging", False)),
        battery_status=str(raw.get("battery_status", "")),
        device=str(raw.get("device", "")),
        server_running=bool(raw.get("server_running", False)),
        sms_permission=bool(raw.get("sms_permission", False)),
        notification_access=bool(raw.get("notification_access", False)),
        default_sms_app=bool(raw.get("default_sms_app", False)),
        detail="Connecté",
    )


def _parse_notification(raw: dict) -> AndroidNotification:
    return AndroidNotification(
        id=str(raw.get("id", "")),
        package=str(raw.get("package", "")),
        app_name=str(raw.get("app_name", "")),
        title=str(raw.get("title", "")),
        text=str(raw.get("text", "")),
        big_text=str(raw.get("big_text", "")),
        timestamp=_epoch_ms_to_dt(raw.get("timestamp")),
        is_clearable=bool(raw.get("is_clearable", True)),
    )


def _parse_event(raw: dict) -> BridgeEvent:
    try:
        event_id = int(raw.get("id", 0))
    except (ValueError, TypeError):
        event_id = 0
    payload = raw.get("payload")
    return BridgeEvent(
        id=event_id,
        type=str(raw.get("type", "")),
        timestamp=_epoch_ms_to_dt(raw.get("timestamp")),
        payload=payload if isinstance(payload, dict) else {},
    )


def _parse_conversation(raw: dict) -> BridgeConversation:
    return BridgeConversation(
        id=str(raw.get("id", "")),
        contact_name=str(raw.get("contact_name", "")),
        phone_number=str(raw.get("phone_number", "")),
        last_message=str(raw.get("last_message", "")),
        last_timestamp=_epoch_ms_to_dt(raw.get("last_timestamp")),
        last_outgoing=bool(raw.get("last_outgoing", False)),
        unread=int(raw.get("unread", 0) or 0),
    )


# ──────────────────────────────────────────────
# Données fictives (mode mock)
# ──────────────────────────────────────────────

@dataclass
class _MockData:
    """Conversations fictives ancrées sur l'heure courante.

    Volontairement proche du jeu de données de ``MockSmsBackend`` pour offrir une
    expérience cohérente entre la maquette SMS et ce pont.
    """

    _threads: dict[str, list[tuple[int, bool, str]]] = field(default_factory=dict)
    _meta: dict[str, tuple[str, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # id → (contact, numéro)
        self._meta = {
            "1": ("Maman", "+33 6 12 34 56 78"),
            "2": ("Léa", "+33 6 98 76 54 32"),
            "3": ("Banque", "36 30"),
        }
        # id → liste de (minutes_ago, outgoing, body), anciens → récents
        self._threads = {
            "1": [
                (180, False, "Tu viens manger dimanche ?"),
                (172, True, "Oui avec plaisir, j'apporte le dessert 🍰"),
                (170, False, "Parfait, à dimanche mon grand ❤️"),
            ],
            "2": [
                (95, False, "T'as vu le nouveau ciné qui sort ?"),
                (90, True, "Ouais ! On y va vendredi soir ?"),
                (88, False, "Carrément, je réserve les places"),
            ],
            "3": [
                (50, False, "Code de confirmation : 482917. Ne le partagez jamais."),
            ],
        }

    def messages(self, conversation_id: str) -> list[BridgeMessage]:
        now = datetime.now()
        items = self._threads.get(conversation_id, [])
        return [
            BridgeMessage(
                body=body,
                timestamp=now - timedelta(minutes=mins),
                outgoing=outgoing,
            )
            for (mins, outgoing, body) in items
        ]

    def conversations(self) -> list[BridgeConversation]:
        convos: list[BridgeConversation] = []
        for cid, (contact, number) in self._meta.items():
            msgs = self.messages(cid)
            last = msgs[-1] if msgs else None
            convos.append(
                BridgeConversation(
                    id=cid,
                    contact_name=contact,
                    phone_number=number,
                    last_message=last.body if last else "",
                    last_timestamp=last.timestamp if last else None,
                )
            )
        convos.sort(
            key=lambda c: c.last_timestamp or datetime.min, reverse=True
        )
        return convos


# ──────────────────────────────────────────────
# Pont singleton + fonctions de commodité
# ──────────────────────────────────────────────

_bridge: Optional[AndroidBridge] = None


def _env_flag(name: str) -> bool:
    """True si la variable d'environnement ``name`` vaut 1/true/yes/on."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _build_bridge() -> AndroidBridge:
    """Construire le pont en fusionnant **env > config persistée > défaut**.

    Priorité (la plus forte d'abord) :

    1. variables d'environnement explicites (``PHONELINK_BRIDGE_*``) ;
    2. configuration persistée (``app/core/config.py``) ;
    3. valeurs par défaut (mode mock, envoi réel désactivé).

    Ainsi un utilisateur final qui s'est appairé (mode ``http`` + token en
    config) obtient automatiquement le pont HTTP au lancement, sans variable
    d'environnement ; le développeur peut toujours surcharger via l'env.
    """
    from app.core import config  # import local : pas de couplage au chargement

    try:
        cfg = config.load_config()
    except Exception as exc:  # config illisible : on continue sur l'env/défauts
        logger.warning("android_bridge: config illisible (%s) — défauts", exc)
        cfg = None

    # mode : env > config > mock
    env_mode = os.environ.get(ENV_MODE)
    if env_mode is not None:
        mode = BridgeMode.HTTP if env_mode.strip().lower() == "http" else BridgeMode.MOCK
        mode_src = "env"
    elif cfg is not None and cfg.android_bridge_mode == "http":
        mode = BridgeMode.HTTP
        mode_src = "config"
    else:
        mode = BridgeMode.MOCK
        mode_src = "config" if cfg is not None else "défaut"

    base_url = (
        os.environ.get(ENV_BASE_URL)
        or (cfg.android_bridge_base_url if cfg else "")
        or DEFAULT_BASE_URL
    )
    token = (
        os.environ.get(ENV_TOKEN)
        or (cfg.android_bridge_token if cfg else "")
        or None
    )

    # allow_real_send : env (si défini) > config > False
    if os.environ.get(ENV_ALLOW_SEND) is not None:
        allow_send = _env_flag(ENV_ALLOW_SEND)
    else:
        allow_send = bool(cfg.android_allow_send) if cfg else False

    logger.info(
        "android_bridge: mode=%s (%s), url=%s, token=%s, envoi_réel=%s",
        mode.value, mode_src, base_url,
        "présent" if token else "absent",
        "autorisé" if allow_send else "bloqué",
    )
    return AndroidBridge(
        base_url=base_url, token=token, mode=mode, allow_real_send=allow_send,
    )


def get_bridge() -> AndroidBridge:
    """Retourner le pont actif (singleton paresseux, env > config > défaut)."""
    global _bridge
    if _bridge is None:
        _bridge = _build_bridge()
    return _bridge


def set_allow_real_send(value: bool) -> None:
    """Active/désactive l'envoi réel sur le pont actif (action UI explicite).

    Utilisé par la confirmation d'envoi de l'UI : le garde-fou reste fermé tant
    que l'utilisateur n'a pas confirmé. N'affecte que la session courante (rien
    n'est persisté ici).
    """
    bridge = get_bridge()
    bridge.allow_real_send = value
    logger.info("android_bridge: envoi réel %s (action UI)", "activé" if value else "désactivé")


def set_bridge(bridge: Optional[AndroidBridge]) -> None:
    """Remplacer le pont actif (tests, ou bascule vers le mode HTTP).

    Passer ``None`` vide le cache : le prochain :func:`get_bridge` reconstruit
    depuis l'environnement.
    """
    global _bridge
    _bridge = bridge


# ──────────────────────────────────────────────
# Intégration avec la configuration persistante
# ──────────────────────────────────────────────

def bridge_from_config() -> AndroidBridge:
    """Construire un :class:`AndroidBridge` depuis la config persistée.

    Lit ``android_bridge_base_url`` / ``android_bridge_token`` /
    ``android_bridge_mode`` via :mod:`app.core.config`. L'envoi réel reste
    désactivé (``allow_real_send=False``).
    """
    from app.core import config  # import local : évite tout couplage au chargement

    cfg = config.load_config()
    mode = BridgeMode.HTTP if cfg.android_bridge_mode == "http" else BridgeMode.MOCK
    return AndroidBridge(
        base_url=cfg.android_bridge_base_url or DEFAULT_BASE_URL,
        token=cfg.android_bridge_token or None,
        mode=mode,
    )


def pair_and_save(pin: str, base_url: Optional[str] = None) -> str:
    """Appairer avec l'app compagnon **et persister** le token en config.

    - construit un pont HTTP vers ``base_url`` (ou l'URL déjà en config) ;
    - appelle :meth:`AndroidBridge.pair` (peut lever :class:`BridgeError`) ;
    - sur succès, enregistre token + URL et bascule ``android_bridge_mode`` sur
      ``"http"`` dans la config, puis remplace le pont actif.

    Renvoie le token. Ne touche pas au garde-fou d'envoi réel.
    """
    from app.core import config  # import local

    cfg = config.load_config()
    url = base_url or cfg.android_bridge_base_url or DEFAULT_BASE_URL

    bridge = AndroidBridge(base_url=url, mode=BridgeMode.HTTP)
    token = bridge.pair(pin)  # BridgeError remonte telle quelle si échec

    cfg.android_bridge_base_url = url
    cfg.android_bridge_token = token
    cfg.android_bridge_mode = "http"
    config.save_config(cfg)

    set_bridge(bridge)  # le pont appairé devient le pont actif
    logger.info("android_bridge: token persisté en configuration")
    return token


def check_health() -> HealthStatus:
    return get_bridge().check_health()


def list_conversations() -> list[BridgeConversation]:
    return get_bridge().list_conversations()


def list_messages(conversation_id: str) -> list[BridgeMessage]:
    return get_bridge().list_messages(conversation_id)


def list_rcs() -> list[RcsThread]:
    return get_bridge().list_rcs()


def get_device_status() -> DeviceStatus:
    return get_bridge().get_device_status()


def list_notifications() -> list[AndroidNotification]:
    return get_bridge().list_notifications()


def list_events(
    since: int = -1, timeout_ms: int = 25_000
) -> tuple[list[BridgeEvent], int]:
    return get_bridge().list_events(since=since, timeout_ms=timeout_ms)


def is_realtime_available() -> bool:
    """True si le pont actif peut faire du long polling réel (HTTP + token).

    Le thread d'écoute d'événements ne démarre que dans ce cas : en mode mock ou
    non appairé, ``/events`` n'a pas de sens (rien à pousser).
    """
    bridge = get_bridge()
    return bridge.mode is BridgeMode.HTTP and bool(bridge.token)


def send_message(
    body: str,
    conversation_id: Optional[str] = None,
    phone_number: Optional[str] = None,
) -> SendResult:
    return get_bridge().send_message(
        body, conversation_id=conversation_id, phone_number=phone_number
    )
