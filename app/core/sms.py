"""SMS conversations — data model and pluggable backends.

PhoneLink Ubuntu cannot read or send SMS on its own: Android does not expose the
SMS database over Bluetooth or ADB to a third-party desktop. The real backend
will therefore require a **companion Android app** (see ``docs/sms.md``) that
talks to this side over the network.

To let the Linux UI be built and tested *before* that companion exists, this
module ships a :class:`MockSmsBackend` serving fictional data. Any future
implementation only has to subclass :class:`SmsBackend` and be returned by
:func:`get_backend` — the UI code never changes.

Two concrete backends now exist:

* :class:`MockSmsBackend` — fictional data, no Android (default).
* :class:`AndroidCompanionBackend` — talks to the companion app through
  :mod:`app.core.android_bridge`. Itself still mock-by-default at the transport
  layer (no real network in V0.4), so it is safe to select without a phone.

Selection happens in :func:`get_backend`, driven by the ``PHONELINK_SMS_BACKEND``
environment variable (``mock`` | ``android``) or an explicit :func:`set_backend`.
"""

from __future__ import annotations

import os
import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Optional

from app.core import android_bridge
from app.utils.logger import get_logger

logger = get_logger(__name__)

RCS_PROVIDER_DUPLICATE_WINDOW_SECONDS = 120

#: Fenêtre (en secondes) pour rattacher un fil RCS au thread provider du même
#: contact quand le message RCS n'est PAS déjà dans le provider (cas Cathy :
#: notif texte récente vs MMS provider « placeholder »). Plus large que la
#: fenêtre de doublon : il s'agit ici de reconnaître « même conversation
#: vivante », pas « même message exact ». Bornée pour ne pas fusionner deux fils
#: homonymes éloignés dans le temps.
RCS_PROVIDER_ATTRIBUTION_WINDOW_SECONDS = 6 * 3600


# ──────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class Message:
    """A single message, immutable once created."""
    body: str
    timestamp: datetime
    outgoing: bool  # True = sent from this side, False = received from the contact
    source: str = "sms"  # "sms" (Telephony) | "rcs" (capté via notifications)


@dataclass
class Conversation:
    """A thread of messages with one contact."""
    id: str
    contact_name: str
    phone_number: str
    messages: list[Message] = field(default_factory=list)
    source: str = "sms"  # "sms" | "rcs" — origine du fil, pour l'UI (badge)

    @property
    def last_message(self) -> Optional[Message]:
        return self.messages[-1] if self.messages else None


@dataclass(frozen=True)
class _ProviderSummary:
    id: str
    contact_name: str
    phone_number: str
    last_message: str
    last_timestamp: Optional[datetime]


# ──────────────────────────────────────────────
# Backend abstraction
# ──────────────────────────────────────────────

class SmsBackend(ABC):
    """Abstract SMS source/sink.

    A real implementation (Android companion app, over Wi-Fi/ADB) just needs to
    fulfil this contract. The UI depends only on this interface.
    """

    #: Human-readable name shown in the UI to explain where data comes from.
    name: str = "SMS"

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        """True only when real send/receive is possible (the mock is never ready)."""

    @abstractmethod
    def list_conversations(self) -> list[Conversation]:
        """Return all conversations, most-recently-active first."""

    @abstractmethod
    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """Return a single conversation by id, or None."""

    @abstractmethod
    def send_message(self, conversation_id: str, body: str) -> tuple[bool, str]:
        """Attempt to send ``body`` in the given conversation.

        Returns ``(sent_for_real, message)``. The mock returns
        ``sent_for_real=False`` because nothing leaves the machine.
        """


# ──────────────────────────────────────────────
# Mock backend (fictional data, no Android)
# ──────────────────────────────────────────────

class MockSmsBackend(SmsBackend):
    """In-memory backend with fictional conversations for UI development."""

    name = "Démo (données fictives)"

    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self._seed()

    @property
    def is_ready(self) -> bool:
        return False  # No companion app: never a real channel.

    def list_conversations(self) -> list[Conversation]:
        convos = list(self._conversations.values())
        convos.sort(
            key=lambda c: c.last_message.timestamp if c.last_message else datetime.min,
            reverse=True,
        )
        return convos

    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        return self._conversations.get(conversation_id)

    def send_message(self, conversation_id: str, body: str) -> tuple[bool, str]:
        body = body.strip()
        convo = self._conversations.get(conversation_id)
        if convo is None or not body:
            return False, "Conversation ou message invalide"
        # Simulated send: append locally so the UI updates, but nothing is
        # actually transmitted — there is no Android companion yet.
        convo.messages.append(
            Message(body=body, timestamp=datetime.now(), outgoing=True)
        )
        logger.info("SMS simulé → %s (%s): %r", convo.contact_name, convo.phone_number, body)
        return False, "Message simulé — aucun envoi réel (app compagnon Android requise)"

    def _seed(self) -> None:
        """Populate fictional conversations anchored to 'now' for plausible times."""
        now = datetime.now()

        def msgs(*items: tuple[int, bool, str]) -> list[Message]:
            # items: (minutes_ago, outgoing, body)
            return [
                Message(body=b, timestamp=now - timedelta(minutes=m), outgoing=o)
                for (m, o, b) in items
            ]

        seed = [
            Conversation(
                id="1", contact_name="Maman", phone_number="+33 6 12 34 56 78",
                messages=msgs(
                    (180, False, "Tu viens manger dimanche ?"),
                    (172, True,  "Oui avec plaisir, j'apporte le dessert 🍰"),
                    (170, False, "Parfait, à dimanche mon grand ❤️"),
                ),
            ),
            Conversation(
                id="2", contact_name="Léa", phone_number="+33 6 98 76 54 32",
                messages=msgs(
                    (95, False, "T'as vu le nouveau ciné qui sort ?"),
                    (90, True,  "Ouais ! On y va vendredi soir ?"),
                    (88, False, "Carrément, je réserve les places"),
                ),
            ),
            Conversation(
                id="3", contact_name="Banque", phone_number="36 30",
                messages=msgs(
                    (50, False, "Code de confirmation : 482917. Ne le partagez jamais."),
                ),
            ),
            Conversation(
                id="4", contact_name="Thomas (collègue)", phone_number="+33 7 11 22 33 44",
                messages=msgs(
                    (30, False, "La réunion de 14h est décalée à 15h30"),
                    (28, True,  "Ok merci pour l'info 👍"),
                    (5,  False, "Tu peux m'envoyer le doc avant ?"),
                ),
            ),
            Conversation(
                id="5", contact_name="Livraison", phone_number="38 00",
                messages=msgs(
                    (2, False, "Votre colis sera livré aujourd'hui entre 16h et 18h."),
                ),
            ),
        ]
        self._conversations = {c.id: c for c in seed}


# ──────────────────────────────────────────────
# RCS/provider duplicate filtering helpers
# ──────────────────────────────────────────────

def _strip_accents(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _normalise_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", value or "")
    if len(digits) < 4:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith("0"):
        digits = "33" + digits[1:]
    return digits


def _normalise_name(value: str) -> str:
    text = _strip_accents(value).casefold()
    text = re.sub(r"[^0-9a-z]+", " ", text).strip()
    return re.sub(r"\s+", " ", text)


def _normalise_body(value: str) -> str:
    text = _strip_accents(value).casefold()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _identity_keys(*values: str) -> set[str]:
    keys: set[str] = set()
    for value in values:
        phone = _normalise_phone(value)
        if phone:
            keys.add("phone:" + phone)
            continue
        name = _normalise_name(value)
        if name:
            keys.add("name:" + name)
    return keys


def _timestamps_close(left: Optional[datetime], right: Optional[datetime]) -> bool:
    if left is None or right is None:
        return False
    delta = abs((left - right).total_seconds())
    return delta <= RCS_PROVIDER_DUPLICATE_WINDOW_SECONDS


def _messages_close(left: str, right: str) -> bool:
    left_norm = _normalise_body(left)
    right_norm = _normalise_body(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    shorter, longer = sorted((left_norm, right_norm), key=len)
    if len(shorter) >= 16 and shorter in longer:
        return True
    if min(len(left_norm), len(right_norm)) < 16:
        return False
    return SequenceMatcher(None, left_norm, right_norm).ratio() >= 0.92


def _match_rcs_to_provider(
    thread: android_bridge.RcsThread,
    providers: list[_ProviderSummary],
) -> tuple[Optional[str], bool]:
    """Rattache un fil RCS (notifications) à un thread provider du même contact.

    Renvoie ``(provider_id, covered)`` :

    * ``(id, True)`` — le dernier message RCS est **déjà** dans ce thread
      provider (même identité + timestamp proche + texte proche, cas broadcast
      type 36608). La ligne RCS est masquée et **rien n'est fusionné** (le
      provider porte déjà le message ; fusionner risquerait un doublon
      intra-fil).
    * ``(id, False)`` — le fil RCS appartient clairement à ce thread provider
      mais porte des messages **absents** du provider (cas Cathy : texte de
      notification vs MMS « placeholder »). La ligne RCS est masquée et ses
      messages sont **fusionnés** dans le thread à l'ouverture.
    * ``(None, False)`` — aucun rattachement sûr : le fil RCS reste une
      conversation autonome en lecture seule (aucune perte de message).
    """
    last = thread.messages[-1] if thread.messages else None
    if last is None:
        return None, False

    rcs_keys = _identity_keys(thread.contact_name, last.sender)
    if not rcs_keys:
        return None, False

    candidates: list[tuple[_ProviderSummary, set[str]]] = []
    for provider in providers:
        provider_keys = _identity_keys(provider.contact_name, provider.phone_number)
        shared = provider_keys.intersection(rcs_keys)
        if shared:
            candidates.append((provider, shared))
    if not candidates:
        return None, False

    # 1) Déjà couvert (même message présent côté provider) → masquer sans fusion.
    for provider, _shared in candidates:
        if (
            _timestamps_close(provider.last_timestamp, last.timestamp)
            and _messages_close(provider.last_message, last.body)
        ):
            return provider.id, True

    # 2) Sinon : rattacher au thread provider le plus proche dans le temps
    #    (même conversation vivante). Désambiguïse les contacts homonymes (deux
    #    « Cathy » de numéros différents → on prend le thread le plus récent).
    def _delta(provider: _ProviderSummary) -> float:
        if provider.last_timestamp is None or last.timestamp is None:
            return float("inf")
        return abs((provider.last_timestamp - last.timestamp).total_seconds())

    best, best_shared = min(candidates, key=lambda c: _delta(c[0]))
    phone_match = any(key.startswith("phone:") for key in best_shared)
    if phone_match or _delta(best) <= RCS_PROVIDER_ATTRIBUTION_WINDOW_SECONDS:
        return best.id, False
    return None, False


def _merge_rcs_messages(
    messages: list[Message],
    threads: list[android_bridge.RcsThread],
) -> list[Message]:
    """Fusionne les messages RCS rattachés dans un thread provider ouvert.

    Dédup stricte par ``(seconde, corps normalisé)`` pour ne jamais réintroduire
    un message déjà présent côté provider, puis tri chronologique. Les messages
    RCS gardent ``source="rcs"`` (badge horodatage côté UI).
    """
    def _key(ts: datetime, body: str) -> tuple[int, str]:
        return int(ts.timestamp()), _normalise_body(body)

    seen = {_key(m.timestamp, m.body) for m in messages}
    merged = list(messages)
    for thread in threads:
        for m in thread.messages:
            key = _key(m.timestamp, m.body)
            if key in seen:
                continue
            seen.add(key)
            merged.append(
                Message(
                    body=m.body,
                    timestamp=m.timestamp,
                    outgoing=m.outgoing,
                    source="rcs",
                )
            )
    merged.sort(key=lambda m: m.timestamp)
    return merged


# ──────────────────────────────────────────────
# Android companion backend (via android_bridge)
# ──────────────────────────────────────────────

class AndroidCompanionBackend(SmsBackend):
    """SMS backend backed by the Android companion app.

    It delegates every operation to :mod:`app.core.android_bridge` and maps the
    bridge's dataclasses onto the :class:`Conversation` / :class:`Message` model
    the UI expects. The bridge itself is still ``MOCK`` by default in V0.4, so
    this backend is fully usable without a phone — ``is_ready`` simply reports
    ``False`` until a real companion answers ``/health`` with SMS permission.
    """

    name = "Android (app compagnon)"

    def __init__(self, bridge: Optional[android_bridge.AndroidBridge] = None) -> None:
        self._bridge = bridge or android_bridge.get_bridge()
        self._conversation_meta: dict[str, android_bridge.BridgeConversation] = {}
        #: provider_id → fils RCS rattachés (fusionnés à l'ouverture du thread).
        #: Rempli par :meth:`list_conversations`, consommé par
        #: :meth:`get_conversation`.
        self._rcs_attribution: dict[str, list[android_bridge.RcsThread]] = {}

    @property
    def is_ready(self) -> bool:
        try:
            return self._bridge.check_health().usable
        except Exception as exc:  # transport errors must never crash the UI
            logger.warning("AndroidCompanionBackend: health check failed: %s", exc)
            return False

    #: Préfixe des ids de conversation RCS (captées via notifications). Permet de
    #: router get_conversation() sans les confondre avec un thread_id SMS.
    RCS_ID_PREFIX = "rcs:"

    def list_conversations(self) -> list[Conversation]:
        convos: list[Conversation] = []
        provider_summaries: list[_ProviderSummary] = []
        # 1) Conversations SMS/MMS (provider Telephony).
        bridge_convos = self._bridge.list_conversations()
        self._conversation_meta = {bc.id: bc for bc in bridge_convos}
        for bc in bridge_convos:
            # The /conversations summary carries only the last message preview,
            # not the full thread — synthesize a single Message so the list view
            # can render its preview. The outgoing flag is unknown here (the API
            # summary doesn't carry it), so default to received.
            messages: list[Message] = []
            if bc.last_message:
                messages = [
                    Message(
                        body=bc.last_message,
                        timestamp=bc.last_timestamp or datetime.now(),
                        outgoing=False,
                    )
                ]
            convos.append(
                Conversation(
                    id=bc.id,
                    contact_name=bc.contact_name,
                    phone_number=bc.phone_number,
                    messages=messages,
                    source="sms",
                )
            )
            provider_summaries.append(
                _ProviderSummary(
                    id=bc.id,
                    contact_name=bc.contact_name,
                    phone_number=bc.phone_number,
                    last_message=bc.last_message,
                    last_timestamp=bc.last_timestamp,
                )
            )

        # 2) Fils RCS captés via notifications (lecture seule, V0.6.0). Les
        # notifications complètent l'historique provider sans le dupliquer
        # (parité KDE Connect : un fil réel = une ligne) :
        #   - déjà couvert par le provider → masqué, pas de fusion ;
        #   - même contact mais message absent du provider (Cathy : texte vs
        #     MMS) → masqué et fusionné dans le thread provider à l'ouverture ;
        #   - rattachement incertain → conservé en ligne RCS autonome.
        self._rcs_attribution = {}
        for thread in self._bridge.list_rcs():
            provider_id, covered = _match_rcs_to_provider(thread, provider_summaries)
            if provider_id is not None:
                if not covered:
                    self._rcs_attribution.setdefault(provider_id, []).append(thread)
                    logger.debug(
                        "RCS rattaché au thread provider %s (fusion à l'ouverture)",
                        provider_id,
                    )
                else:
                    logger.debug(
                        "RCS ignoré dans la liste: déjà couvert par provider %s",
                        provider_id,
                    )
                continue
            last = thread.messages[-1] if thread.messages else None
            convos.append(
                Conversation(
                    id=self.RCS_ID_PREFIX + thread.id,
                    contact_name=thread.contact_name,
                    phone_number="",
                    messages=[
                        Message(
                            body=last.body,
                            timestamp=last.timestamp,
                            outgoing=last.outgoing,
                            source="rcs",
                        )
                    ] if last else [],
                    source="rcs",
                )
            )

        # Tri global : conversation la plus récemment active en premier.
        convos.sort(
            key=lambda c: c.last_message.timestamp if c.last_message else datetime.min,
            reverse=True,
        )
        return convos

    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        if conversation_id.startswith(self.RCS_ID_PREFIX):
            return self._get_rcs_conversation(conversation_id)

        # Metadata (name/number) comes from the latest /conversations result.
        # Avoid reloading the full list when the user opens a thread from the
        # visible list; /messages is the only expensive call at that point.
        meta = self._conversation_meta.get(conversation_id)
        if meta is None:
            bridge_convos = self._bridge.list_conversations()
            self._conversation_meta.update({c.id: c for c in bridge_convos})
            meta = self._conversation_meta.get(conversation_id)
        if meta is None:
            return None
        messages = [
            Message(body=m.body, timestamp=m.timestamp, outgoing=m.outgoing)
            for m in self._bridge.list_messages(conversation_id)
        ]
        # Fusionne l'historique RCS rattaché à ce thread (cf. list_conversations),
        # de sorte que SMS/MMS/RCS du même fil réel apparaissent ensemble.
        rcs_threads = self._rcs_attribution.get(conversation_id)
        if rcs_threads:
            messages = _merge_rcs_messages(messages, rcs_threads)
        return Conversation(
            id=meta.id,
            contact_name=meta.contact_name,
            phone_number=meta.phone_number,
            messages=messages,
            source="sms",
        )

    def _get_rcs_conversation(self, conversation_id: str) -> Optional[Conversation]:
        raw_id = conversation_id[len(self.RCS_ID_PREFIX):]
        thread = next((t for t in self._bridge.list_rcs() if t.id == raw_id), None)
        if thread is None:
            return None
        return Conversation(
            id=conversation_id,
            contact_name=thread.contact_name,
            phone_number="",
            messages=[
                Message(body=m.body, timestamp=m.timestamp, outgoing=m.outgoing,
                        source="rcs")
                for m in thread.messages
            ],
            source="rcs",
        )

    def send_message(self, conversation_id: str, body: str) -> tuple[bool, str]:
        if conversation_id.startswith(self.RCS_ID_PREFIX):
            return False, "Conversation RCS en lecture seule"
        result = self._bridge.send_message(body, conversation_id=conversation_id)
        return result.sent, result.detail


# ──────────────────────────────────────────────
# Backend selection (single injection point)
# ──────────────────────────────────────────────

#: Maps a backend key to its factory. Add future backends here.
_BACKENDS: dict[str, type[SmsBackend]] = {
    "mock": MockSmsBackend,
    "android": AndroidCompanionBackend,
}

#: Environment variable that picks the backend at startup. Defaults to "mock".
_ENV_KEY = "PHONELINK_SMS_BACKEND"

_backend: Optional[SmsBackend] = None


def get_backend() -> SmsBackend:
    """Return the active SMS backend (lazily created singleton).

    Selection order (highest priority first):

    1. an explicit backend set via :func:`set_backend`;
    2. the key in ``$PHONELINK_SMS_BACKEND`` (``mock`` | ``android``) — dev override;
    3. the persisted config: ``android`` if ``android_bridge_mode == "http"`` and a
       token is present (so a paired user gets real SMS automatically);
    4. otherwise the mock (demo fallback).

    The UI never has to change: it always talks to :class:`SmsBackend`.
    """
    global _backend
    if _backend is None:
        _backend = _select_backend()
    return _backend


def _select_backend() -> SmsBackend:
    """Resolve the backend per the documented priority, logging the reason."""
    # 1/2. Override explicite par l'environnement (développeur).
    env_key = os.environ.get(_ENV_KEY)
    if env_key:
        key = env_key.strip().lower()
        factory = _BACKENDS.get(key)
        if factory is None:
            logger.warning(
                "%s=%r inconnu — retour au mock (valeurs: %s)",
                _ENV_KEY, key, ", ".join(_BACKENDS),
            )
            factory = MockSmsBackend
        backend = factory()
        logger.info("Backend SMS (override env %s=%s): %s", _ENV_KEY, key, backend.name)
        return backend

    # 3. Config persistée : appairé (http + token) → backend Android.
    reason = "config absente"
    try:
        from app.core import config
        cfg = config.load_config()
        if cfg.android_bridge_mode == "http" and cfg.android_bridge_token:
            backend = AndroidCompanionBackend()
            logger.info("Backend SMS (config: appairé http+token): %s", backend.name)
            return backend
        reason = (
            "mode config != http" if cfg.android_bridge_mode != "http"
            else "token d'appairage absent"
        )
    except Exception as exc:  # config illisible : on retombe proprement sur le mock
        reason = f"config illisible: {exc}"

    # 4. Fallback démo.
    backend = MockSmsBackend()
    logger.info("Backend SMS mock (fallback démo — raison: %s)", reason)
    return backend


def set_backend(backend: Optional[SmsBackend]) -> None:
    """Override the active backend (tests, or a future in-app switch).

    Passing ``None`` clears the cache so the next :func:`get_backend` re-selects
    from the environment.
    """
    global _backend
    _backend = backend
