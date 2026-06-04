# Backend Android compagnon — V0.4

Spécification technique de l'**application compagnon Android** qui donnera à
PhoneLink Ubuntu un accès SMS réel, et du **client Ubuntu** (`app/core/android_bridge.py`)
qui la pilotera.

> État V0.4 : on prépare le terrain. Côté Ubuntu, le client est **mockable** et ne
> fait encore **aucun appel réseau réel**. L'app Android n'est pas encore écrite.
> Cf. [`docs/sms.md`](sms.md) pour le rappel du « pourquoi une app compagnon ».

---

## 1. Architecture Linux ↔ Android

PhoneLink Ubuntu (GTK) reste un **client**. L'app compagnon Android est un
**petit serveur HTTP local** tournant sur le téléphone, joignable par Ubuntu sur
le réseau local (Wi-Fi) ou via le tunnel `adb`.

```
┌────────────────────────────┐         HTTP/JSON           ┌────────────────────────────┐
│        Ubuntu (client)     │  ───────────────────────▶   │      Android (serveur)     │
│                            │                             │                            │
│  app/ui/sms_window.py      │  GET  /health               │  Service compagnon         │
│        │                   │  GET  /conversations        │   ├─ HTTP server (local)   │
│  app/core/sms.py           │  GET  /messages?id=…        │   ├─ ContentResolver SMS   │
│   └─ AndroidCompanionBackend│ POST /send                  │   │   (Telephony.Sms)      │
│        │                   │                             │   └─ SmsManager (envoi)    │
│  app/core/android_bridge.py│  ◀───────────────────────   │                            │
│   (client HTTP mockable)   │        JSON responses       │                            │
└────────────────────────────┘                             └────────────────────────────┘
```

Deux canaux de transport possibles pour atteindre le serveur :

| Transport            | URL de base typique           | Bootstrap                                   |
|----------------------|-------------------------------|---------------------------------------------|
| **ADB port-forward** | `http://127.0.0.1:8765`       | `adb forward tcp:8765 tcp:8765` (USB ou Wi-Fi) |
| **Wi-Fi direct (LAN)** | `http://<ip_tel>:8765`      | même réseau Wi-Fi, IP du téléphone          |

ADB port-forward est **recommandé** : le trafic ne quitte pas le lien USB/ADB
déjà utilisé par le reste de l'app, et on évite d'exposer un port sur le LAN.

### Respect des contraintes projet

- 100 % local : aucun serveur cloud, aucune donnée hors de la machine et du téléphone.
- Réutilise l'infra ADB déjà présente (`app/core/adb.py`) pour le port-forward.
- N'utilise **pas** scrcpy / KDE Connect / GSConnect.

---

## 2. API locale prévue

- **Protocole** : HTTP/1.1, corps JSON (`Content-Type: application/json`).
- **Base URL** : configurable (défaut `http://127.0.0.1:8765`).
- **Auth** : en-tête `Authorization: Bearer <token>` (cf. §5).
- **Encodage** : UTF-8. Tous les horodatages en **epoch millisecondes** (entier),
  convertis en `datetime` côté Ubuntu.
- **Versionnage** : préfixe `/v1` (ex. `/v1/health`) pour autoriser des évolutions.

### Modèle de données (JSON)

```jsonc
// Conversation (résumé, sans le détail des messages)
{
  "id": "thread-42",
  "contact_name": "Maman",
  "phone_number": "+33 6 12 34 56 78",
  "last_message": "À dimanche mon grand",
  "last_timestamp": 1717412400000,
  "unread": 0
}

// Message
{
  "body": "Tu viens manger dimanche ?",
  "timestamp": 1717412400000,
  "outgoing": false   // true = envoyé depuis le téléphone, false = reçu
}
```

Ce modèle est volontairement aligné sur les dataclasses `Conversation` / `Message`
de `app/core/sms.py`, pour qu'un futur `AndroidCompanionBackend(SmsBackend)` mappe
les réponses sans friction.

---

## 3. Permissions Android nécessaires

L'app compagnon devra déclarer et obtenir à l'exécution :

| Permission                  | Usage                                              |
|-----------------------------|----------------------------------------------------|
| `READ_SMS`                  | Lire conversations et messages (`ContentResolver`) |
| `SEND_SMS`                  | Envoyer via `SmsManager`                           |
| `RECEIVE_SMS`               | Détecter les SMS entrants (notifications/refresh)  |
| `READ_CONTACTS` (optionnel) | Résoudre `phone_number` → `contact_name`           |
| `FOREGROUND_SERVICE`        | Maintenir le serveur HTTP en service de premier plan |
| `INTERNET`                  | Ouvrir un socket d'écoute local                    |

Notes importantes :
- Sur Android 6+, `READ_SMS` / `SEND_SMS` sont des permissions **dangereuses** :
  demande explicite à l'exécution, révocables à tout moment.
- Le Play Store **restreint fortement** l'accès SMS (politique « SMS and Call Log »).
  L'app compagnon sera vraisemblablement distribuée **hors store** (APK / sideload),
  ce qui est cohérent avec un outil personnel local.

---

## 4. Limites SMS sur Android

À garder en tête côté conception (et à exposer à l'utilisateur dans l'UI) :

- **Pas de MMS** en V0.4 : seuls les SMS texte sont gérés. Les MMS (images, groupes)
  sont hors périmètre.
- **Segmentation** : un SMS > 160 caractères (GSM-7) ou > 70 (UCS-2, ex. emojis)
  est découpé en plusieurs segments facturés ; `SmsManager.divideMessage()` gère
  le découpage mais le coût/opérateur reste réel.
- **App SMS par défaut** : l'écriture fiable dans la base SMS (marquer comme lu,
  cohérence des threads) peut exiger d'être l'**app SMS par défaut**. L'envoi via
  `SmsManager` ne l'exige pas, mais la persistance dans `Telephony.Sms` si.
- **Accusés de réception** : statut « envoyé » ≠ « délivré ». On pourra écouter les
  `PendingIntent` de `SmsManager` pour un statut plus fin (post-V0.4).
- **Quotas anti-spam** : Android limite le nombre de SMS envoyés par intervalle sans
  interaction utilisateur ; un envoi massif déclenche une boîte de confirmation système.
- **Double SIM** : le choix de la SIM d'envoi (`SubscriptionManager`) est ignoré en
  V0.4 (SIM par défaut).

---

## 5. Appairage sécurisé (PIN / token)

Le serveur écoute en local, mais on ne fait **aucune confiance implicite**. Schéma
d'appairage simple et suffisant pour un usage personnel :

1. **Affichage d'un PIN** : à l'activation du serveur, l'app Android affiche un
   **code PIN à 6 chiffres** (rotatif/expirable).
2. **Échange PIN → token** : Ubuntu poste le PIN une seule fois :
   ```
   POST /v1/pair   { "pin": "482917", "client": "phonelink-ubuntu" }
   → 200  { "token": "<token_opaque_long>" }
   ```
3. **Token persistant** : Ubuntu stocke le token via `app/core/config.py`
   (`~/.config/phonelink-ubuntu`). Toutes les requêtes suivantes portent
   `Authorization: Bearer <token>`.
4. **Révocation** : l'utilisateur peut invalider le token depuis l'app Android
   (« oublier cet appareil ») → les requêtes repassent en `401`.

Garde-fous :
- PIN à **usage unique** et **expirant** (ex. 5 min) → anti-brute-force.
- Token **opaque** et long (≥ 32 octets aléatoires), jamais journalisé en clair.
- Liaison recommandée sur `127.0.0.1` via port-forward ADB → surface réseau minimale.
- (Optionnel post-V0.4) TLS auto-signé + pinning si écoute sur le LAN.

### Appairage côté Ubuntu (implémenté)

- `AndroidBridge.pair(pin)` poste `POST /v1/pair { "pin", "client" }` et renvoie
  le token (met aussi à jour `self.token`). C'est une opération réseau réelle,
  effectuée quel que soit le mode.
- `pair_and_save(pin, base_url=None)` enchaîne l'appairage **et la persistance** :
  token + URL enregistrés via `config.py`, `android_bridge_mode` basculé sur
  `"http"`, et le pont appairé devient le pont actif (`set_bridge`).
- `bridge_from_config()` reconstruit un `AndroidBridge` depuis la config persistée.

Champs ajoutés dans `app/core/config.py` (`~/.config/phonelink-ubuntu/config.json`) :

| Champ                      | Rôle                              | Défaut                  |
|----------------------------|-----------------------------------|-------------------------|
| `android_bridge_base_url`  | base URL de l'app compagnon       | `http://127.0.0.1:8765` |
| `android_bridge_token`     | token Bearer obtenu à l'appairage | `""`                    |
| `android_bridge_mode`      | `mock` \| `http`                  | `mock`                  |

Erreurs gérées par `pair()` (toutes via `BridgeError`, `status` HTTP si dispo) :
**PIN vide**, **HTTP 401/403** (PIN invalide/expiré), **JSON invalide**,
**token absent** de la réponse, **serveur injoignable** (timeout/refus).

L'appairage **n'active pas** l'envoi réel de SMS : le garde-fou
`allow_real_send=False` reste en place (cf. §6 bis).

---

## 6. Endpoints prévus

Tous préfixés `/v1`. Réponses JSON. `401` si token absent/invalide, `400` si requête
malformée, `503` si le service SMS Android n'est pas prêt (permissions manquantes).

### `GET /health`
Sonde de disponibilité et de capacité réelle.
```jsonc
→ 200 {
  "status": "ok",
  "app_version": "0.4.0",
  "sms_permission": true,    // READ_SMS + SEND_SMS accordées
  "default_sms_app": false,
  "device": "Pixel 7"
}
```

### `GET /conversations`
Liste des conversations, plus récente d'abord. Pagination optionnelle
(`?limit=`, `?offset=`).
```jsonc
→ 200 { "conversations": [ {Conversation}, … ] }
```

### `GET /messages?conversation_id=<id>`
Messages d'une conversation, anciens → récents. Pagination optionnelle.
```jsonc
→ 200 { "conversation_id": "thread-42", "messages": [ {Message}, … ] }
→ 404 si l'id est inconnu
```

### `POST /send`
Envoi d'un SMS.
```jsonc
←  { "conversation_id": "thread-42", "body": "Bonjour" }
// ou, pour démarrer un nouveau fil :
←  { "phone_number": "+33 6 …",     "body": "Bonjour" }

→ 200 { "sent": true,  "message": {Message} }
→ 400 { "sent": false, "error": "body vide" }
→ 503 { "sent": false, "error": "permission SEND_SMS manquante" }
```

---

## 6 bis. Transport HTTP côté Ubuntu (implémenté)

`AndroidBridge._request()` est implémenté en **stdlib pure** (`urllib.request` /
`urllib.error` / `json`) — aucune dépendance PyPI.

- **GET** (query-string encodée) et **POST** (corps JSON) ; en-têtes
  `Accept: application/json`, `User-Agent: phonelink-ubuntu/0.4`, et
  `Authorization: Bearer <token>` si un token est présent.
- **Timeout** appliqué (`AndroidBridge.timeout`, défaut 5 s).
- **Gestion d'erreurs** : toute panne (réseau, HTTP 4xx/5xx, JSON invalide,
  réponse non-objet) lève une `BridgeError(message, status)` — aucune exception
  `urllib` brute ne remonte. Un corps d'erreur JSON `{"error": …}` est extrait
  dans le message.

### Activation (sans casser le mock)

Le mode **mock reste le défaut**. Le mode HTTP s'active par configuration :

| Variable                   | Rôle                                   | Défaut                  |
|----------------------------|----------------------------------------|-------------------------|
| `PHONELINK_BRIDGE_MODE`    | `mock` \| `http`                       | `mock`                  |
| `PHONELINK_BRIDGE_URL`     | base URL en mode http                  | `http://127.0.0.1:8765` |
| `PHONELINK_BRIDGE_TOKEN`   | token Bearer                           | _(aucun)_               |

```
PHONELINK_BRIDGE_MODE=http PHONELINK_BRIDGE_TOKEN=… python3 main.py
```

### Garde-fou : pas d'envoi réel en V0.4

`AndroidBridge.allow_real_send` vaut **`False`** par défaut. Même connecté en
HTTP, `send_message()` **ne poste jamais `/send`** : il renvoie un résultat
simulé (`sent=False`). L'envoi réel exigera de construire le pont avec
`allow_real_send=True`, volontairement non exposé via l'environnement.

---

## 7. Prochaines étapes d'implémentation

Côté **Ubuntu** (ce dépôt) :
1. ✅ Client mockable `app/core/android_bridge.py` :
   `check_health()`, `list_conversations()`, `list_messages()`, `send_message()`.
2. ✅ Transport HTTP réel `_request()` en stdlib (`urllib`), modes `mock`/`http`,
   timeout, erreurs réseau/HTTP/JSON, token Bearer — signatures inchangées.
3. ✅ `AndroidCompanionBackend(SmsBackend)` dans `app/core/sms.py` qui appelle
   `android_bridge` et mappe vers `Conversation`/`Message`.
4. ✅ Appairage PIN→token (`pair()` / `pair_and_save()`) + persistance du token
   via `config.py` (`android_bridge_*`) + `bridge_from_config()`.
5. ⬜ Lever le garde-fou `allow_real_send` (envoi réel) une fois l'app testée.
6. ⬜ Détection auto de l'app compagnon dans `get_backend()` (au-delà de l'env).
7. ⬜ UI d'appairage (champ PIN, état « connecté/déconnecté ») branchée sur
   `pair_and_save()` — seule étape UI restante.
8. ⬜ Mise en place du port-forward ADB depuis `app/core/adb.py`.

Côté **Android** (`android-companion/`) — **V0.5, cf. [`android-backend-v0.5.md`](android-backend-v0.5.md)** :
9. ⬜ Service de premier plan (serveur encore lié à l'activité).
10. ✅ Lecture SMS via `ContentResolver` (`Telephony.Sms`) → `SmsRepository`.
11. 🟡 Envoi via `SmsManager` ✅ ; persistance dans `Telephony.Sms` ⬜ (exige app SMS par défaut).
12. 🟡 Appairage PIN/token déjà présent (V0.4) ; révocation persistante ⬜.
13. ✅ Permissions runtime + état dégradé honnête (`/health.sms_permission`, fallback démo).
