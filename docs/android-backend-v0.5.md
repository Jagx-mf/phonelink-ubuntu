# Backend Android compagnon — V0.5 (SMS réels)

Suite de [`android-backend-v0.4.md`](android-backend-v0.4.md). La V0.4 préparait
le terrain (transport HTTP, appairage, mock). La **V0.5 implémente l'accès SMS
réel côté Android** tout en conservant le mock comme fallback.

> Statut : **validé sur appareil réel** (lecture conversations/messages OK via
> l'app compagnon). Les raffinements UX/backend ci-dessous (§9) sont issus de
> cette validation terrain.

---

## 1. Ce qui change par rapport à la V0.4

### Côté Android (`android-companion/`)

| Fichier | Changement |
|---|---|
| `AndroidManifest.xml` | Ajout `READ_SMS`, `SEND_SMS`, `RECEIVE_SMS`, `READ_CONTACTS` |
| `SmsRepository.kt` (nouveau) | Lecture conversations/messages via `ContentResolver`, envoi via `SmsManager`, résolution contacts |
| `CompanionServer.kt` | Endpoints routés vers `SmsRepository` si permission, sinon `DemoData` ; `/health` conforme au contrat |
| `DemoData.kt` | Format JSON **aligné sur le contrat** (`contact_name`, `last_timestamp`, `unread` entier) |
| `MainActivity.kt` | Demande de permissions runtime + affichage du mode (réel/démo) |
| `build.gradle.kts` | `versionName` 0.4.1 → 0.5.0 |

### Côté Ubuntu (`app/`)

| Fichier | Changement |
|---|---|
| `android_bridge.py` | Opt-in d'envoi réel via `PHONELINK_BRIDGE_ALLOW_SEND=1` (défaut : désactivé) |

**Aucune régression V0.4** : Bluetooth, photos, galerie, messages GTK et le mode
mock restent intacts. Le défaut Ubuntu reste `mock` + envoi réel désactivé.

---

## 2. Correctif important : le contrat JSON était désaligné

En V0.4.1, le `DemoData` Android renvoyait `title`/`timestamp` (+ `unread`
booléen) alors que le client Ubuntu (`android_bridge._parse_conversation`) attend
`contact_name`/`last_timestamp`/`unread` entier. De même `/health` renvoyait
`paired`/`device_name` au lieu de `sms_permission`/`device`.

Conséquence : en mode HTTP, les conversations se seraient affichées **sans nom ni
date**, et `HealthStatus.usable` aurait été **toujours faux**. La V0.5 aligne les
deux côtés (mock Android **et** réel) sur le contrat documenté en
`android-backend-v0.4.md §2`/`§6`.

---

## 3. Format JSON réel (identique au contrat)

```jsonc
// GET /v1/health
{ "status": "ok", "app_version": "0.5.0", "sms_permission": true,
  "default_sms_app": false, "device": "Samsung SM-G990B" }

// GET /v1/conversations
{ "conversations": [
  { "id": "<thread_id>", "contact_name": "Maman", "phone_number": "+33…",
    "last_message": "…", "last_timestamp": 1717412400000, "unread": 2 } ] }

// GET /v1/messages?conversation_id=<thread_id>
{ "conversation_id": "<thread_id>",
  "messages": [ { "body": "…", "timestamp": 1717412400000, "outgoing": false } ] }

// POST /v1/send   { "phone_number": "+33…", "body": "Bonjour" }
//            ou   { "conversation_id": "<thread_id>", "body": "Bonjour" }
{ "sent": true, "message": { "body": "Bonjour", "timestamp": …, "outgoing": true } }
// → 503 { "sent": false, "error": "permission SEND_SMS manquante" }
// → 400 { "sent": false, "error": "body vide" }
```

`id` = `thread_id` de `Telephony.Sms`. `outgoing` dérive du `TYPE` (SENT/OUTBOX/
FAILED/QUEUED = sortant).

---

## 4. Détails d'implémentation Android (`SmsRepository`)

- **Conversations** : un seul parcours de `Telephony.Sms.CONTENT_URI` trié par
  `DATE DESC` (limité à 1000 lignes par défaut). La première occurrence de chaque
  `thread_id` donne le résumé (dernier message), et les messages reçus non lus
  sont comptés au passage (`unread`).
- **Messages** : `THREAD_ID = ?`, tri `DATE ASC`.
- **Contacts** : `ContactsContract.PhoneLookup` si `READ_CONTACTS` accordée,
  sinon le numéro sert de nom. Cache mémoire par numéro.
- **Envoi** : `divideMessage()` puis `sendTextMessage` (1 segment) ou
  `sendMultipartTextMessage` (multi-segments). `SmsManager` obtenu via
  `getSystemService(SmsManager::class.java)` (API 31+) avec fallback déprécié.

---

## 5. Limites connues V0.5

- **Pas de persistance du SMS envoyé** dans `Telephony.Sms` : l'écriture dans la
  base SMS exige d'être l'**app SMS par défaut**. L'envoi via `SmsManager`
  fonctionne, mais le message envoyé **ne réapparaîtra pas dans le fil** tant que
  l'app n'est pas définie par défaut. Le client reçoit un écho (`message`) pour
  l'affichage immédiat.
- **Pas de MMS**, double SIM ignorée (SIM par défaut), accusé « envoyé » ≠
  « délivré ».
- **Coût** : un message long est segmenté et facturé par segment.
- **Serveur lié à l'activité** : il s'arrête si l'activité est détruite (un
  service de premier plan viendra plus tard).

---

## 6. Politique permissions / distribution

`READ_SMS`/`SEND_SMS` sont des permissions **dangereuses** : demande runtime,
révocables. Si refusées, le serveur **reste fonctionnel en mode démo** et
`/health` renvoie `sms_permission=false` (état honnête, le client le détecte via
`HealthStatus.usable`). L'accès SMS étant **fortement restreint sur le Play
Store**, l'app compagnon est destinée au **sideload/APK** (outil personnel).

---

## 7. Tests (à lancer côté utilisateur)

```bash
# 1. Compiler/installer l'APK (Android Studio, ou ./gradlew si wrapper présent)
# 2. Lancer l'app, "Autoriser l'accès aux SMS", "Démarrer le serveur"

adb devices
adb forward tcp:8765 tcp:8765

curl http://127.0.0.1:8765/v1/health
# attendu : "sms_permission": true si permissions accordées

curl -X POST http://127.0.0.1:8765/v1/pair \
  -H "Content-Type: application/json" \
  -d '{"pin":"<PIN_AFFICHÉ>","client":"phonelink-ubuntu"}'
TOKEN="<token_reçu>"

curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/v1/conversations
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8765/v1/messages?conversation_id=<thread_id>"

# Envoi réel (⚠️ envoie un vrai SMS) :
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"phone_number":"+33...","body":"Test PhoneLink"}' \
  http://127.0.0.1:8765/v1/send

# Interface GTK :
PHONELINK_BRIDGE_MODE=http PHONELINK_BRIDGE_TOKEN=$TOKEN \
  PHONELINK_SMS_BACKEND=android python3 main.py
# Pour autoriser l'envoi réel depuis GTK (opt-in) :
#   ... PHONELINK_BRIDGE_ALLOW_SEND=1 python3 main.py
```

---

## 8. Reste à faire (post-V0.5)

- Devenir app SMS par défaut (optionnel) → persistance des envois dans le fil.
- `RECEIVE_SMS` : notification/rafraîchissement temps réel des entrants.
- Service de premier plan pour garder le serveur vivant.
- Port-forward ADB automatique depuis `app/core/adb.py`.

---

## 9. Raffinements UX/backend (post-validation terrain)

Issus de l'usage réel. Tout reste compatible V0.4 (mock par défaut, Bluetooth/
photos/galerie intacts).

### 9.1 Sélection de backend automatique (plus de variables d'env obligatoires)

`sms.get_backend()` et `android_bridge.get_bridge()` résolvent désormais leur
configuration par **priorité décroissante** :

1. **variables d'environnement** explicites (override développeur) ;
2. **config persistée** (`~/.config/phonelink-ubuntu/config.json`) : si
   `android_bridge_mode == "http"` **et** un token est présent → backend Android ;
3. **fallback mock/démo**.

Concrètement : après un appairage, `python3 main.py` **suffit** — plus besoin de
`PHONELINK_SMS_BACKEND=android …`. Logs émis : backend choisi, mode + source,
URL, token présent/absent, `health` OK/KO, **raison** du fallback démo.

### 9.2 Envoi de vrais SMS depuis GTK, sans variable d'env, avec garde-fou

- Le bouton **Envoyer** déclenche, sur backend Android, une **boîte de
  confirmation** « Envoyer un vrai SMS ? » (nom du contact, avertissement coût).
- La confirmation = autorisation explicite : elle lève le garde-fou
  `allow_real_send` **pour la session** (`android_bridge.set_allow_real_send`).
- Garde-fou persistant complémentaire : `config.android_allow_send` (défaut
  `False`) et l'override `PHONELINK_BRIDGE_ALLOW_SEND=1`.
- En mode démo, l'envoi reste simulé (aucune confirmation, rien n'est transmis).
- **Aucun SMS réel n'est envoyé sans clic explicite** sur « Envoyer » dans le
  dialog → sûr pendant les tests.

### 9.3 `/v1/messages` renvoie les N **derniers** messages

`SmsRepository.messages()` interroge `DATE DESC LIMIT N` puis **inverse** vers
ancien→récent (défaut `N=200`, paramètre `?limit=`). On obtient donc les messages
les plus récents (et non les plus anciens) sur les longs fils.

### 9.4 Cache + chargement non bloquant (latence au changement de conversation)

- Côté GTK : cache des messages **par `conversation_id`** → réouverture instantanée.
- Premier chargement (ou **Rafraîchir**) effectué dans un **thread**, l'UI affiche
  « Chargement… » et ne se fige pas ; résultat appliqué via `GLib.idle_add`.
- Un **compteur de génération** ignore un résultat obsolète si l'utilisateur a
  changé de conversation entre-temps.
- Bouton **Rafraîchir** (icône) dans la barre de titre : invalide le cache de la
  conversation courante et recharge. Log du **temps de chargement** (ms).

### 9.5 Scroll automatique en bas

À l'ouverture d'une conversation, on vise le **dernier message**. Le scroll est
appliqué via le signal `changed` de l'ajustement vertical (donc **après** la mise
en page des bulles), pas immédiatement après l'ajout des widgets.

### 9.6 UI d'appairage PIN

Bouton « cadenas » dans la barre de titre → petite fenêtre modale (champ PIN +
**Appairer**). Appelle `pair_and_save(pin)` dans un thread, persiste le token,
**bascule** le backend vers Android et **recharge** la liste des conversations,
sans relancer l'application.

### Fichiers touchés (9.x)

`app/core/config.py` (champ `android_allow_send`), `app/core/android_bridge.py`
(`_build_bridge` env>config>défaut, `set_allow_real_send`, logs health),
`app/core/sms.py` (`_select_backend`), `app/ui/sms_window.py` (cache, thread,
scroll, confirmation, appairage), `android-companion/.../SmsRepository.kt` +
`CompanionServer.kt` (limite messages).
