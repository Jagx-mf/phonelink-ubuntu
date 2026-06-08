Créer ou mettre à jour le fichier :

docs/openclaw/PROJECT_MEMORY.md

Objectif :
Conserver un état complet et factuel du projet PhoneLink Ubuntu afin de pouvoir reprendre le développement à tout moment.

Structure obligatoire :

# PhoneLink Ubuntu - Mémoire Projet

## Vision du projet

* Concurrent Linux de Microsoft Phone Link
* Communication Ubuntu ↔ Android
* Fonctionnement USB puis Wi-Fi
* Interface GTK moderne
* Aucune dépendance KDE Connect / GSConnect

## État actuel du projet

### V0.1

* Connexion Bluetooth
* Détection téléphone
* Diagnostic système

### V0.2

* Import photos ADB
* Galerie photos GTK
* Correctifs Bluetooth et ADB

### V0.3

* Interface Messages GTK
* Backend SMS abstrait
* Mock backend fonctionnel

### V0.4

* Android Companion créé
* Application Android Kotlin
* Serveur HTTP NanoHTTPD embarqué
* Endpoints :

  * GET /v1/health
  * POST /v1/pair
  * GET /v1/conversations
  * GET /v1/messages
  * POST /v1/send

### Validation effectuée

Ubuntu :

adb devices → OK

adb forward tcp:8765 tcp:8765 → OK

curl /v1/health → OK

curl /v1/pair → OK

curl /v1/conversations → OK

PhoneLink Ubuntu :

* AndroidBridge fonctionnel
* Appairage PIN → token fonctionnel
* Messages visibles dans GTK
* Backend Android sélectionnable

Android :

* APK compilé
* Installation sur Samsung S21 FE
* Serveur HTTP démarré
* Appairage fonctionnel

## V0.5 — SMS réels (validée)

* Lecture SMS classiques via `Telephony.Sms` / `content://sms`
* Envoi SMS réel via `SmsManager` (multipart), avec confirmation explicite côté GTK
* Résolution des noms via `ContactsContract` (READ_CONTACTS)
* Garde-fou `allow_real_send` : aucun SMS ne part sans action utilisateur

## V0.6 — Provider canonique + dédup SMS/MMS/RCS (validée)

### Lecture élargie (parité KDE Connect)

* SMS classiques : `Telephony.Sms` / `content://sms`
* Surface élargie : `content://mms-sms`
* MMS : `content://mms`
* Texte MMS : `content://mms/part` (parts `text/plain`) — débloque l'historique récent (ex. Cathy après le 28/05)
* Lazy loading :

  * `/v1/conversations` reste léger (pas de lecture des parts MMS)
  * `/v1/messages?conversation_id=ID` charge le détail au clic (lit les parts MMS)
* Cache GTK par `conversation_id` (rechargement seulement sur « Rafraîchir »)
* Notifications Android via `NotificationListenerService` pour RCS / temps réel / futur RemoteInput

### Découverte importante

Le provider SMS/MMS est la **source canonique de l'historique**.
Les notifications RCS sont un **complément**, pas une source équivalente à afficher
systématiquement comme conversation séparée dans la liste principale.

### Problème rencontré

Après l'ajout des notifications RCS, certaines conversations apparaissaient en doublon :

* 36608
* C3dPasChere
* Fr Travail
* StudiALT
* Weldom
* Cathy en MMS/RCS séparé

### Cause réelle

1. Côté Android :

   * `RcsMessageStore` pouvait contenir deux clés pour le même fil RCS
     (exemple : `53` et `shortcut:53`)
   * ces clés non canoniques venaient du `NotificationListener` (et d'un
     `rcs_store.json` hérité d'une version antérieure)

2. Côté Ubuntu/Python :

   * `app/core/sms.py` ajoutait les fils RCS dans la liste principale même quand
     ils étaient déjà couverts par le provider SMS/MMS

3. Cas Cathy :

   * le fil provider MMS id 4 portait le thread réel avec le placeholder `"MMS"`
   * le fil RCS portait le vrai texte récent
   * les deux représentaient le **même** échange réel récent
   * l'ancien fil Cathy id 40 correspond à un **autre numéro** et doit rester séparé

### Correction appliquée

1. Android :

   * `RcsNotificationListener.kt` stabilise les clés RCS (`stableConversationKey`)
   * `RcsMessageStore.kt` canonicalise et déduplique les fils
     (`canonicalConversationKey` / `deduplicatedThreads`)
   * `53` et `shortcut:53` représentent désormais le **même fil logique**

2. Python/GTK (`app/core/sms.py`) :

   * `/v1/conversations` est traité comme **historique canonique**
   * `_match_rcs_to_provider()` rapproche chaque fil RCS du provider :

     * RCS déjà couvert par le provider → **masqué** dans la liste, **pas** de fusion
     * RCS rattachable de façon fiable à un thread provider → **injecté au chargement**
       du fil (`_merge_rcs_messages`), avec dédup stricte `(seconde, corps normalisé)`
     * RCS réellement non couvert → **conservé visible en lecture seule**
   * désambiguïsation par proximité temporelle (fenêtre bornée 6 h) :
     deux contacts homonymes ne sont **pas** fusionnés aveuglément
   * l'envoi SMS classique reste basé sur le **thread provider**
   * RCS reste **non envoyable** tant que RemoteInput n'est pas implémenté

3. `android_bridge.py` :

   * parsing enrichi avec `sender` pour comparer fils RCS et provider

### État validé après correction

* 36608 apparaît une seule fois
* C3dPasChere apparaît une seule fois
* Fr Travail apparaît une seule fois
* StudiALT / Weldom ne sont plus doublonnés inutilement
* Cathy récente est rattachée proprement au bon fil provider (id 4)
* l'autre Cathy (autre numéro, id 40) reste séparée
* SMS classiques fonctionnent
* MMS restent lisibles
* historique Cathy récent reste visible
* lazy loading conservé
* cache GTK conservé

### Validation terrain datée — 2026-06-08

* Validation après redémarrage du téléphone et de l'application Android Companion
* L'application GTK redémarre correctement
* Les conversations SMS/MMS/RCS restent visibles après redémarrage
* La conversation Cathy récente reste lisible
* Les doublons principaux ne réapparaissent pas visuellement
* L'envoi SMS classique fonctionne encore après les changements provider-first SMS/MMS/RCS
* Le modèle provider-first reste validé
* `RemoteInput` / envoi RCS reste hors scope

* appairage Android conservé
* pas de retour à V0.5
* pas de suppression de `rcs_store.json`

### Tests effectués

* `py_compile` sur les fichiers Python modifiés : OK
* `git diff --check` : OK
* `/v1/health` : OK
* `/v1/conversations` : OK
* `/v1/messages?conversation_id=4` : OK
* `/v1/rcs/messages` : OK
* Test visuel GTK : doublons corrigés
* APK Android rebuild + installée après les modifications Kotlin

### Décision de conception (modèle retenu, proche KDE Connect)

* provider SMS/MMS = **source canonique** de l'historique
* notifications RCS = **complément**
* ne pas afficher les notifications RCS comme conversations séparées si elles sont
  déjà représentées par le provider
* ne pas fusionner aveuglément deux contacts homonymes
* en cas d'identité ambiguë : **mieux vaut garder séparé** que perdre/mélanger des messages

### À ne pas refaire (garde-fous)

* ne pas réintroduire une fusion globale agressive SMS/MMS/RCS
* ne pas supprimer automatiquement le cache RCS (`rcs_store.json`)
* ne pas revenir au modèle V0.5
* garder le modèle canonique **provider + enrichissement notifications**

### Risques restants

* certains fils MMS-only peuvent encore afficher un nom vide ou `"MMS"`
* point **hors scope** pour l'instant afin de préserver les performances de `/v1/conversations`
* une future V0.6.1 / V0.7 pourra résoudre les noms MMS via `content://mms/{id}/addr`
  avec mesure de performance
* RemoteInput / réponse RCS reste **hors** V0.6 actuelle

## V0.7 — Serveur Android dans un Foreground Service (en cours)

Branche : `feat/v0.7-android-foreground-service`.

### Objectif

Stabiliser l'application Android Companion : le serveur HTTP NanoHTTPD
(`CompanionServer`) est déplacé de l'activité vers un **Foreground Service**
Android (`CompanionForegroundService`). Le serveur continue donc de répondre
même si `MainActivity` est fermée ou mise en arrière-plan.

### Ce qui change (Android uniquement)

* Nouveau `CompanionForegroundService.kt` :
  * crée et gère l'unique instance `CompanionServer` ;
  * affiche une notification persistante « PhoneLink Companion actif » ;
  * canal de notification dédié pour Android 8+ (`IMPORTANCE_LOW`) ;
  * `startForeground` avec type `dataSync` (requis Android 14 / API 34) ;
  * `START_STICKY` : relance par le système si tué (PIN/token régénérés) ;
  * action `STOP` (bouton de notification) pour arrêter proprement.
* `MainActivity` ne possède plus le serveur : les boutons
  « Démarrer/Arrêter » pilotent le service (`startForegroundService` /
  `stopService`). L'UI continue d'afficher statut, IP, port 8765, PIN, état
  appairage, permission SMS, accès notifications/RCS. Le statut démarré/arrêté
  est lu via `CompanionForegroundService.isRunning`.
* `PairingManager` : ajout d'un singleton de processus `PairingManager.shared`
  partagé entre l'activité (affichage PIN) et le service (vérification token).
  Les deux composants vivent dans le même processus → une seule instance suffit.
* `AndroidManifest.xml` : permissions `FOREGROUND_SERVICE`,
  `FOREGROUND_SERVICE_DATA_SYNC`, `POST_NOTIFICATIONS` ; déclaration du service
  avec `android:foregroundServiceType="dataSync"`.
* `POST_NOTIFICATIONS` demandée au runtime (Android 13+) au démarrage du serveur.
* `versionCode` 3 → 4, `versionName` 0.6.0 → 0.7.0.

### Ce qui ne change PAS (garanti)

* Endpoints V0.6 strictement identiques : `/v1/health`, `/v1/pair`,
  `/v1/conversations`, `/v1/messages`, `/v1/send`, `/v1/rcs/messages`,
  `/v1/debug/notifications`, `/v1/debug/sms-provider`, `/v1/debug/mms-parts`.
* Appairage PIN/token inchangé (même logique, instance partagée).
* Modèle provider-first SMS/MMS/RCS **inchangé**.
* `RemoteInput` / envoi RCS toujours **hors scope**.
* Aucun fichier Python modifié ; client Ubuntu non touché.

### Tests effectués

* `assembleDebug` : **BUILD SUCCESSFUL**, APK debug généré (~5,6 Mo).
* `git diff --check` : OK.
* Aucun `.py` modifié.

### Limites restantes V0.7

* PIN/token restent **en mémoire** (`PairingManager.shared`) : perdus si le
  processus est tué (kill système, réinstallation) ou après `START_STICKY` qui
  régénère le PIN. Persistance à ajouter dans une version ultérieure.
* Test de redémarrage complet du téléphone avec serveur survivant en
  arrière-plan : **à valider sur le terrain**.
* Comportement des limites de temps des FGS `dataSync` (Android 15+) non
  éprouvé ; sans objet en targetSdk 34.

## V0.8 — Batterie / statut téléphone + notifications Android (en cours)

Branche : `feat/v0.8-device-status-notifications`.

### Objectif

Ajouter deux fonctionnalités complémentaires, sans toucher au modèle
provider-first SMS/MMS/RCS ni au Foreground Service V0.7 :

1. batterie + statut téléphone affichés côté GTK ;
2. fenêtre « Notifications Android » en lecture seule (proche de Microsoft
   Phone Link).

### Endpoints ajoutés (Android, token requis)

- `GET /v1/device/status` →
  `{ battery_level, battery_charging, battery_status, device, server_running,
  sms_permission, notification_access, default_sms_app, api_version }`.
  Batterie lue via le sticky broadcast `Intent.ACTION_BATTERY_CHANGED` /
  `BatteryManager` (API standard, **aucune dépendance ajoutée**). Les autres
  champs réutilisent `SmsRepository` / `RcsNotificationListener` /
  `CompanionForegroundService.isRunning`.
- `GET /v1/notifications` →
  `{ notifications: [ {id, package, app_name, title, text, big_text,
  timestamp, is_clearable} ] }`. Source : `getActiveNotifications()` via une
  nouvelle méthode `RcsNotificationListener.activeNotificationsSnapshot()`
  (toutes apps, pas seulement Google Messages). Filtre le bruit évident
  (résumés de groupe `FLAG_GROUP_SUMMARY`, notifications en cours
  `FLAG_ONGOING_EVENT`, notifications vides). Si le listener n'est pas
  connecté : `{ "status": "listener_not_connected", "notifications": [] }` avec
  **HTTP 200**.

### Ce qui change (Android)

- `CompanionServer.kt` : deux routes `GET /v1/device/status` et
  `GET /v1/notifications` (guarded), helper batterie privé `batteryInfo()`.
  `/v1/health` et tous les endpoints V0.6/V0.7 **inchangés**.
- `RcsNotificationListener.kt` : ajout de `activeNotificationsSnapshot()` +
  helpers `notificationToJson()` / `appLabel()`. **Aucune** écriture dans
  `RcsMessageStore`, **aucune** logique provider-first touchée, **aucun**
  `RemoteInput`. Le chemin RCS (`refreshFromActive` / `debugDump`) est
  inchangé.
- `versionName` 0.7.0 → 0.8.0, `versionCode` 4 → 5.

### Ce qui change (Ubuntu/Python + GTK)

- `app/core/android_bridge.py` : dataclasses `DeviceStatus` et
  `AndroidNotification` ; méthodes `get_device_status()` (ne lève jamais →
  `reachable=False` si indisponible) et `list_notifications()` (lève
  `BridgeError` sur erreur de transport pour que l'UI affiche un message
  clair ; `[]` en mock ou si `listener_not_connected`) ; parsing + fonctions de
  commodité au niveau module.
- `app/ui/main_window.py` : groupe « Téléphone Android » (batterie %, charge,
  serveur Android, SMS, notifications), alimenté par `get_device_status()` dans
  le thread de rafraîchissement existant (`_fetch_status` → `GLib.idle_add` →
  `_apply_device_status`). Action « Notifications Android » qui ouvre la
  nouvelle fenêtre.
- `app/ui/notifications_window.py` (**nouveau**) : fenêtre GTK lecture seule,
  bouton Rafraîchir, chargement en thread + `GLib.idle_add`, message clair si
  vide ou téléphone non connecté. Pas de bouton répondre, pas de `RemoteInput`.

### Ce qui ne change PAS (garanti)

- `/v1/health` et endpoints V0.6/V0.7 strictement identiques.
- Modèle provider-first SMS/MMS/RCS **inchangé** ; lecture SMS/MMS/RCS
  intacte ; envoi SMS classique non touché.
- Foreground Service V0.7 reste le mode de fonctionnement du serveur Android.
- `RemoteInput` / envoi RCS toujours **hors scope**.

### Tests effectués

- `python3 -m py_compile` sur `android_bridge.py`, `sms.py`, `main_window.py`,
  `notifications_window.py` : OK.
- `assembleDebug` : **BUILD SUCCESSFUL**, APK debug (~5,7 Mo).
- `git diff --check` : OK.

### Limites restantes V0.8

- `/v1/notifications` ne renvoie pas les icônes/images des notifications.
- Le snapshot est un instantané live (`getActiveNotifications()`) : pas
  d'historique des notifications déjà balayées.
- Tests terrain (APK 0.8.0 installée, `curl` des deux endpoints, affichage
  GTK) à valider sur le téléphone.

## Architecture actuelle

Android
↓
NanoHTTPD
↓
ADB Forward
↓
android_bridge.py
↓
sms.py
↓
GTK Messages

## Ce qui fonctionne

* Bluetooth
* Photos
* Galerie
* ADB
* Appairage PIN
* Token
* Conversations de démonstration
* Messages de démonstration

## Ce qui reste à faire

### V0.5

* READ_SMS
* SEND_SMS
* READ_CONTACTS
* SMS réels

### V0.6

* Contacts réels
* Notifications Android
* Batterie
* Presse-papiers

### V0.7

* ADB Wi-Fi automatique
* Plus besoin de câble USB

### V1.0

* SMS réels
* Contacts
* Notifications
* Photos
* Batterie
* Presse-papiers
* ADB Wi-Fi
* Appairage complet

## V0.9 — Temps réel + appairage depuis l'accueil

Objectif : afficher automatiquement les nouveaux SMS/MMS/RCS et notifications
sans bouton Rafraîchir, et appairer depuis la fenêtre principale.

Endpoint ajouté (token requis) :
* `GET /v1/events?since=<id>&timeout_ms=<ms>` — long polling.
  Réponse : `{ "events": [ {id, type, timestamp, payload?} ], "last_event_id": N }`.
  Aucun événement ⇒ attente jusqu'à `timeout_ms` (borné 1–30 s, défaut 25 000)
  puis réponse (liste vide possible). `since` négatif/absent ⇒ resynchro initiale.
  File en mémoire bornée (`EventBus.kt`). N'altère aucun endpoint existant.

Types d'événements : `notification_changed`, `sms_changed`, `device_status_changed`.

Déclencheurs Android :
* `notification_changed` ← `RcsNotificationListener` (posted/removed, toutes apps
  sauf la notification de service).
* `sms_changed` ← `ContentObserver` sur `content://sms`, `content://mms`,
  `content://mms-sms` (Foreground Service) + message RCS capté. L'observateur
  signale seulement « changement » ; Ubuntu recharge ensuite les endpoints.
* `device_status_changed` ← receiver `ACTION_POWER_CONNECTED/DISCONNECTED`.

Côté Ubuntu :
* `BridgeEvent` + `list_events()` dans `app/core/android_bridge.py` ;
* `app/core/event_listener.py` : `AndroidEventListener` (thread long polling,
  backoff, arrêt propre, token invalide sans spam) + `DesktopNotifier`
  (`Gio.Notification`, dédup) ;
* `main_window.py` orchestre : bouton « Appairer Android Companion », routage des
  événements vers les fenêtres Messages/Notifications, notifications bureau ;
* `/v1/conversations` porte désormais `last_outgoing` (direction du dernier
  message) → preview correcte + suppression des notifications de SMS sortants.

Inchangé : provider-first, endpoints existants, Foreground Service V0.7.
Hors scope : `RemoteInput`, envoi RCS.

`versionName` 0.8.0 → 0.9.0, `versionCode` 5 → 6.

## Phase temps réel — validation terrain

**Date de validation : 2026-06-08.**

### Composants Android ajoutés

- `EventBus.kt` : file d'événements **en mémoire**, bornée (256), long polling
  (`wait/notify`), timeout borné 1–30 s (défaut 25 000 ms).
- `CompanionServer.kt` : route `GET /v1/events` (token requis).
- `CompanionForegroundService.kt` : `ContentObserver` sur `content://sms`,
  `content://mms`, `content://mms-sms` (débounce 800 ms) → `sms_changed` ;
  receiver `ACTION_POWER_CONNECTED/DISCONNECTED` → `device_status_changed`.
  Tout est best-effort (échecs avalés, jamais de crash du service).
- `RcsNotificationListener.kt` : `notification_changed` sur
  `onNotificationPosted` / `onNotificationRemoved` (toutes apps sauf la
  notification du service) ; `sms_changed` quand un message RCS est capté.
- `SmsRepository.kt` : champ `last_outgoing` ajouté au résumé
  `/v1/conversations` (direction du dernier message).

### Composants Ubuntu ajoutés

- `app/core/android_bridge.py` : dataclass `BridgeEvent`, `list_events(since,
  timeout_ms)`, `is_realtime_available()`, constantes `EVENT_*`, parsing
  `last_outgoing`, timeout réseau spécifique pour le long polling.
- `app/core/event_listener.py` (**nouveau**) : `AndroidEventListener` (thread
  long polling, backoff réseau, arrêt propre, token invalide géré sans spam) ;
  `DesktopNotifier` (notification bureau).
- `app/ui/main_window.py` : bouton **« Appairer Android Companion »**, routage
  des événements vers les fenêtres Messages/Notifications, notifications bureau.
- `app/ui/sms_window.py` : `refresh_realtime()` (préserve sélection + saisie),
  `reload_backend()`.
- `app/ui/notifications_window.py` : `reload_async()`.

### Endpoints ajoutés

- `GET /v1/events?since=<id>&timeout_ms=<ms>` (token requis) :
  `{ "events": [ {id, type, timestamp, payload?} ], "last_event_id": N }`.
- `last_outgoing` ajouté à `GET /v1/conversations` (rétro-compatible).

### Fonctionnement général

Android pousse des événements légers dans `EventBus` ; Ubuntu fait du long
polling sur `/v1/events` (thread dédié) et, à réception, recharge les fenêtres
concernées + affiche une **notification bureau**. La délivrance bureau passe par
`notify-send` (vérifié via `shutil.which`, lancé sans `shell=True`), avec repli
`Gio.Notification` — car `Gtk.Application.send_notification` est silencieusement
ignoré par GNOME sans fichier `.desktop` correspondant. Les boutons Rafraîchir
manuels restent disponibles en fallback. Aucune notification pour les messages
**sortants** ni pour l'**historique au lancement** (priming).

### Tests terrain validés (2026-06-08)

- appairage depuis la fenêtre principale : **OK** ;
- SMS entrant visible en temps réel dans PhoneLink : **OK** ;
- notifications Android visibles en temps réel dans la fenêtre Notifications
  Android : **OK** ;
- notification bureau Ubuntu « PhoneLink Ubuntu » : **OK** ;
- `notify-send` fonctionne ;
- KDE Connect **n'est plus nécessaire** pour les notifications bureau ;
- envoi SMS classique **non cassé**.

### Limites restantes

- `RemoteInput` RCS toujours **hors scope** ; envoi RCS **non implémenté** ;
- événements **en mémoire** côté Android (perdus au redémarrage du service →
  resynchro via `since=-1`) ;
- persistance **token/PIN** encore améliorable (en mémoire, régénérés au
  redémarrage) ;
- arrêt du thread d'écoute jusqu'à ~35 s (requête en cours) — thread *daemon* ;
- **connexion sans câble** pas encore finalisée (`adb forward` requis) ;
- **design final** repoussé après validation fonctionnelle.

## Roadmap — prochaines phases

### Phase 1 — Explorateur de fichiers Android

Objectif : naviguer dans les fichiers du téléphone depuis Ubuntu.
- afficher les dossiers Android (type « Mes fichiers ») ;
- naviguer dans `DCIM`, `Download`, `Pictures`, `Movies`, `Documents` selon
  permissions ;
- copier un fichier téléphone → Ubuntu et Ubuntu → téléphone ;
- déplacer / renommer / supprimer si raisonnable et sûr ;
- privilégier une API Companion propre, ADB en fallback éventuel ;
- ne pas casser l'import photos existant.

### Phase 2 — Contacts

Objectif : bouton « Contacts » dans l'application Ubuntu.
- afficher les contacts Android + barre de recherche + fiche simple ;
- envoyer un SMS à un contact ; lancer un appel si possible ;
- préparer l'intégration future audio Bluetooth/HFP ;
- `READ_CONTACTS` côté Android ; ne pas refondre le module SMS.

### Phase 3 — Connexion sans câble

Objectif : ne plus dépendre du câble USB.
- connexion **Wi-Fi prioritaire** (découverte réseau local, appairage, serveur
  joignable sans `adb forward`, config IP/port côté Ubuntu, reconnexion auto) ;
- Bluetooth en complément si possible ;
- garder ADB USB en fallback ; documenter les limites Android/réseau local.

### Phase 4 — Design / UX finale

Objectif : moderniser l'interface une fois les fonctions principales fiables.
- interface modernisée, meilleure page d'accueil, cartes
  téléphone/statut/messages/notifications, icônes, thème cohérent ;
- meilleures fenêtres Messages et Notifications, meilleure navigation ;
- captures d'écran dans le README ; préparation d'une version installable ;
- **repoussée après validation fonctionnelle.**

## Commandes utiles

adb devices

adb forward tcp:8765 tcp:8765

curl http://127.0.0.1:8765/v1/health

curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8765/v1/events?since=0&timeout_ms=5000"

curl -X POST http://127.0.0.1:8765/v1/pair 
-H "Content-Type: application/json" 
-d '{"pin":"PIN","client":"phonelink-ubuntu"}'

## Dernière validation

Date : 2026-06-08

Validation V0.9 — phase temps réel + appairage depuis l'accueil :

Android Companion (Foreground Service)
→ EventBus (file en mémoire)
→ /v1/events (long polling)
→ android_bridge.list_events
→ event_listener.AndroidEventListener
→ GTK (Messages / Notifications rafraîchis sans clic)
→ DesktopNotifier (notify-send → notification bureau « PhoneLink Ubuntu »)

Statut :
V0.9 validée terrain (2026-06-08).
SMS/MMS/RCS et notifications Android en temps réel, notification bureau OK via
notify-send (KDE Connect plus nécessaire), appairage depuis la fenêtre
principale OK, envoi SMS classique non cassé.
Reste hors scope : RemoteInput / envoi RCS. Événements en mémoire côté Android ;
token/PIN en mémoire ; connexion sans câble et design final à venir (roadmap).

---

Validation V0.6 — modèle provider-first + dédup SMS/MMS/RCS :

Android Companion
→ ADB
→ Port Forward
→ Pairing
→ Token
→ Conversations (provider canonique : sms + mms + mms/part)
→ Notifications RCS (complément, dédupliqué)
→ GTK Messages (doublons corrigés)

Statut :
V0.6 validée.
Doublons SMS/MMS/RCS corrigés, comportement rapproché de KDE Connect.
Reste : noms MMS-only vides (hors scope), RemoteInput / réponse RCS (V0.6.1+).
