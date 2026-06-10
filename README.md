# PhoneLink Ubuntu v0.1

Interface GTK4/Adwaita pour contrôler votre téléphone Android depuis GNOME Ubuntu.

Conçu pour **Samsung Galaxy S21 FE** (et tout Android) avec Bluetooth appairé et/ou ADB.

## Fonctionnalités V0.1

| Fonctionnalité                | Outil utilisé         |
|-------------------------------|-----------------------|
| État Bluetooth en temps réel  | bluetoothctl          |
| Profil audio actif A2DP/HSP   | pactl                 |
| Reconnexion en un clic        | bluetoothctl connect  |
| Ouverture pavucontrol         | pavucontrol           |
| Guide mode appel (5 étapes)   | —                     |
| Affichage téléphone           | scrcpy + adb          |
| Import photos                 | adb pull              |
| Diagnostic système complet    | which + systemctl     |

## Démarrage rapide

```bash
# Installer les dépendances système (une seule fois)
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
                 bluez pavucontrol adb scrcpy

# Lancer l'application
cd phonelink-ubuntu
python main.py
```

## Installation du lanceur Linux

Pour lancer PhoneLink Ubuntu comme une application normale (menu
Applications GNOME, icône, recherche), sans taper `python3 main.py` :

```bash
chmod +x scripts/install-desktop-launcher.sh
./scripts/install-desktop-launcher.sh
```

Le script installe, **sans sudo**, dans votre dossier utilisateur :

- `~/.local/bin/phonelink-ubuntu` — lanceur (lien symbolique vers
  `scripts/phonelink-ubuntu`, qui retrouve la racine du projet et lance
  l'application avec le bon répertoire de travail) ;
- `~/.local/share/applications/phonelink-ubuntu.desktop` — entrée de menu
  (le champ `Exec=` est réécrit avec le chemin absolu du lanceur) ;
- `~/.local/share/icons/hicolor/scalable/apps/phonelink-ubuntu.svg` — icône.

Lancement ensuite :

- depuis le **menu Applications** (« PhoneLink Ubuntu ») ;
- ou en ligne de commande : `phonelink-ubuntu`.

Désinstallation :

```bash
./scripts/uninstall-desktop-launcher.sh
```

Notes :

- le lanceur étant un lien symbolique vers le dépôt, **ne déplacez pas le
  dossier du projet** après installation (relancez simplement le script
  d'installation si vous le déplacez) ;
- la configuration (`~/.config/phonelink-ubuntu`) et les téléchargements ne
  sont pas touchés par la désinstallation.

## Prérequis détaillés

→ [docs/installation.md](docs/installation.md)

## Architecture

→ [docs/architecture.md](docs/architecture.md)

## Dépannage

→ [docs/troubleshooting.md](docs/troubleshooting.md)

## Roadmap V0.1 → V1.0

→ [docs/roadmap.md](docs/roadmap.md)

## Règles de développement

- **Zéro `shell=True`** — protection contre l'injection de commandes
- **Zéro sudo automatique** — l'utilisateur voit et valide toute commande élevée
- **Zéro réseau externe** — 100 % local
- **Zéro modification de config BT** sans confirmation utilisateur
- Toute opération bloquante tourne dans un thread daemon avec callback `GLib.idle_add`

## Logs

```
~/.local/share/phonelink-ubuntu/phonelink.log
```

## Validation terrain V0.6

- Date : 08/06/2026.
- Validation après redémarrage du téléphone et de l'application Android Companion.
- L'application GTK redémarre correctement.
- Les conversations SMS/MMS/RCS restent visibles après redémarrage.
- La conversation Cathy récente reste lisible.
- Les doublons principaux ne réapparaissent pas visuellement.
- L'envoi SMS classique fonctionne encore après les changements provider-first SMS/MMS/RCS.
- Le modèle provider-first reste validé.
- `RemoteInput` et l'envoi RCS restent hors scope.

## V0.7 — Serveur Android en Foreground Service (en cours)

- Le serveur HTTP de l'app Android Companion tourne désormais dans un
  **Foreground Service** (`CompanionForegroundService`).
- Le serveur **survit** à la fermeture ou la mise en arrière-plan de l'activité.
- Les boutons « Démarrer / Arrêter le serveur » pilotent le service ; une
  notification persistante indique que PhoneLink Companion est actif.
- Les endpoints V0.6 restent **inchangés**.
- Le modèle provider-first SMS/MMS/RCS reste le modèle validé.
- `RemoteInput` / envoi RCS reste **hors scope**.
- Limites restantes : PIN/token en mémoire (à persister plus tard), test de
  redémarrage complet du téléphone à valider sur le terrain.

## V0.8 — Batterie / statut téléphone + notifications Android (en cours)

- Deux nouveaux endpoints **protégés** (token requis) côté Android Companion :
  - `GET /v1/device/status` : batterie (`battery_level`, `battery_charging`,
    `battery_status`), modèle (`device`), `server_running`, `sms_permission`,
    `notification_access`, `default_sms_app`. Lecture batterie via l'API
    standard `Intent.ACTION_BATTERY_CHANGED` / `BatteryManager` — aucune
    dépendance ajoutée.
  - `GET /v1/notifications` : snapshot **lecture seule** des notifications
    Android actives (`getActiveNotifications()` via le `NotificationListener`).
    Si le listener n'est pas connecté : `{ "status": "listener_not_connected",
    "notifications": [] }` avec HTTP 200.
- Côté GTK :
  - section **« Téléphone Android »** dans l'écran principal : batterie %,
    charge oui/non, serveur Android OK/indisponible, SMS OK/non, Notifications
    OK/non — rafraîchie par le bouton de rafraîchissement existant ;
  - fenêtre **« Notifications Android »** (lecture seule) : liste application /
    titre / texte / heure, bouton Rafraîchir, message clair si vide ou
    téléphone non connecté. Aucune réponse, aucun `RemoteInput`.
- `/v1/health` reste **inchangé** (compatibilité). Les endpoints V0.6/V0.7
  (`/v1/conversations`, `/v1/messages`, `/v1/send`, `/v1/rcs/messages`,
  `/v1/debug/*`) sont **inchangés**.
- Le modèle provider-first SMS/MMS/RCS reste inchangé ; le serveur Android
  reste hébergé par le Foreground Service V0.7. `RemoteInput` / envoi RCS
  restent **hors scope**.
- `versionName` 0.7.0 → 0.8.0, `versionCode` 4 → 5.

## V0.9 — Temps réel + appairage depuis l'accueil (validé terrain — 2026-06-08)

Objectif : plus besoin de cliquer sur **Rafraîchir** pour voir un nouveau
SMS/MMS/RCS ou une nouvelle notification, et appairage accessible directement
depuis la fenêtre principale.

- **Bouton « Appairer Android Companion »** dans l'écran principal GTK : boîte de
  dialogue PIN → `android_bridge.pair_and_save(pin)` (token persisté dans
  `~/.config/phonelink-ubuntu/config.json`), reconstruction du pont, rechargement
  du backend SMS, rafraîchissement de la section « Téléphone Android » et
  redémarrage de l'écoute temps réel. Messages affichés : succès / PIN invalide /
  serveur indisponible. Le bouton d'appairage de la fenêtre Messages est conservé.
- **Nouvel endpoint protégé** (token requis) côté Android Companion :
  - `GET /v1/events?since=<id>&timeout_ms=<ms>` — **long polling**. Renvoie
    `{ "events": [ {id, type, timestamp, payload?} ], "last_event_id": N }`.
    Si aucun événement : attend jusqu'à `timeout_ms` (borné 1–30 s, défaut
    25 000) puis répond (liste vide possible). `since` absent/négatif ⇒
    resynchro initiale (liste vide + `last_event_id` courant). File d'événements
    **en mémoire**, bornée (`EventBus.kt`).
- **Types d'événements** : `notification_changed`, `sms_changed`,
  `device_status_changed`.
- **Déclencheurs Android** :
  - `notification_changed` : `RcsNotificationListener.onNotificationPosted` /
    `onNotificationRemoved` (toutes apps, sauf notre propre notification de
    service) ;
  - `sms_changed` : `ContentObserver` sur `content://sms`, `content://mms`,
    `content://mms-sms` enregistré par le Foreground Service (+ un message RCS
    capté). L'observateur **signale** seulement un changement ; Ubuntu recharge
    ensuite les endpoints. Échecs avalés (jamais de crash du service) ;
  - `device_status_changed` : receiver `ACTION_POWER_CONNECTED/DISCONNECTED`
    (branchement secteur). Le niveau % reste rafraîchi à la demande.
- **Côté Ubuntu** :
  - `app/core/android_bridge.py` : dataclass `BridgeEvent` + `list_events(since,
    timeout_ms)` ;
  - `app/core/event_listener.py` : `AndroidEventListener` (thread long polling,
    backoff réseau, arrêt propre, token invalide géré sans spam) et
    `DesktopNotifier` (notifications bureau natives `Gio.Notification`,
    dédupliquées) ;
  - mises à jour GTK toujours via `GLib.idle_add` ; pas deux refresh SMS ni deux
    refresh notifications concurrents ; la **saisie en cours** n'est jamais vidée.
- **Notifications bureau Ubuntu** sobres : « Nouveau SMS — Contact » et
  « App — Titre » pour une notification Android. Messages **sortants** ignorés
  (le résumé `/v1/conversations` porte désormais `last_outgoing`), pas de popup
  si la fenêtre concernée est active, dédup par id/timestamp.
- Les **boutons Rafraîchir** manuels restent en place (fallback). Les endpoints
  existants et le modèle provider-first sont **inchangés**. `RemoteInput` et
  envoi RCS restent **hors scope**.

### Phase temps réel — validation terrain

**Date de validation : 2026-06-08.**

Composants Android ajoutés :
- `EventBus.kt` — file d'événements **en mémoire**, bornée, avec long polling
  (`wait/notify`) ;
- route `GET /v1/events` dans `CompanionServer.kt` ;
- `ContentObserver` SMS/MMS (`content://sms`, `content://mms`,
  `content://mms-sms`) + receiver batterie dans `CompanionForegroundService` ;
- `notification_changed` émis depuis `RcsNotificationListener` (posted/removed) ;
- `last_outgoing` ajouté au résumé `SmsRepository.conversations`.

Composants Ubuntu ajoutés :
- `BridgeEvent` + `list_events()` + `is_realtime_available()` dans
  `app/core/android_bridge.py` ;
- `app/core/event_listener.py` : `AndroidEventListener` (long polling) +
  `DesktopNotifier` (notification bureau) ;
- bouton **« Appairer Android Companion »** et orchestration temps réel dans
  `app/ui/main_window.py` ;
- `refresh_realtime()` dans `app/ui/sms_window.py`, `reload_async()` dans
  `app/ui/notifications_window.py`.

Endpoints ajoutés :
- `GET /v1/events?since=<id>&timeout_ms=<ms>` (token requis) ;
- champ `last_outgoing` ajouté à `GET /v1/conversations` (rétro-compatible).

Fonctionnement général : Android pousse des événements légers dans `EventBus`
(NotificationListener, ContentObserver SMS/MMS, receiver batterie) ; Ubuntu fait
du **long polling** sur `/v1/events` dans un thread dédié, ce qui déclenche le
rechargement des fenêtres Messages / Notifications et l'affichage d'une
**notification bureau** (`notify-send`, repli `Gio.Notification`). Les SMS/MMS/RCS
et les notifications Android apparaissent **sans clic sur Rafraîchir**.

Tests terrain validés (2026-06-08) :
- appairage depuis la fenêtre principale : **OK** ;
- SMS entrant visible en temps réel : **OK** ;
- notifications Android visibles en temps réel : **OK** ;
- notification bureau Ubuntu « PhoneLink Ubuntu » via `notify-send` : **OK** ;
- KDE Connect **n'est plus nécessaire** pour les notifications bureau ;
- envoi SMS classique **non cassé**.

Limites restantes :
- `RemoteInput` RCS toujours **hors scope** ;
- envoi RCS **non implémenté** ;
- événements **en mémoire** côté Android (perdus au redémarrage du service →
  resynchro automatique via `since=-1`) ;
- persistance **token/PIN** encore améliorable (en mémoire, régénérés au
  redémarrage du service) ;
- l'arrêt du thread d'écoute peut prendre jusqu'à ~35 s (requête long polling en
  cours) — thread *daemon*, sans impact à la fermeture ;
- **connexion sans câble** pas encore finalisée (`adb forward` requis) ;
- **design final** repoussé après validation fonctionnelle.

## V1.0 — Fichiers, Contacts, Wi-Fi sans câble, UX (en test)

Les quatre phases de la roadmap sont implémentées dans la branche
`feat/full-phone-link-completion-test` (validation terrain à faire).

### Phase 1 — Explorateur de fichiers Android

- Endpoints **protégés** (token requis) côté Companion, limités aux dossiers
  publics (Download, DCIM, Pictures, Movies, Music, Documents), avec
  canonicalisation des chemins et refus de `..` / hors-racine :
  - `GET /v1/files/roots` — racines autorisées ;
  - `GET /v1/files/list?path=…` — contenu d'un dossier
    (`{path, parent, items:[{name, path, is_dir, size, modified, mime}]}`) ;
  - `GET /v1/files/download?path=…` — téléchargement binaire en streaming ;
  - `POST /v1/files/upload?path=…&name=…` — upload binaire brut (octet-stream) ;
  - `POST /v1/files/mkdir {path, name}` ;
  - `POST /v1/files/delete {path}` (récursif, racines protégées) ;
  - `POST /v1/files/rename {path, new_name}` (même dossier).
- Permission Android : « Accès à tous les fichiers » (MANAGE_EXTERNAL_STORAGE)
  sur Android 11+, bouton dédié dans l'app Companion ; READ/WRITE_EXTERNAL_STORAGE
  + `requestLegacyExternalStorage` sur Android ≤ 10. `/v1/health` expose
  `files_permission`.
- Côté Ubuntu : fenêtre **« Fichiers Android »** (navigation, retour parent,
  rafraîchir, télécharger, envoyer un fichier, nouveau dossier, renommer,
  supprimer avec confirmation, tailles/dates lisibles, tout en threads).
  Destination des téléchargements : `~/Téléchargements/PhoneLinkUbuntu`
  (XDG `DOWNLOAD`). L'import photos ADB existant est inchangé.

### Phase 2 — Contacts

- Endpoints protégés : `GET /v1/contacts`, `GET /v1/contacts/search?q=…`
  (`{id, display_name, phones[], emails[], photo_available}`) et
  `POST /v1/call/start {phone_number}`.
- L'appel utilise **ACTION_DIAL** : le dialer s'ouvre sur le téléphone avec le
  numéro prérempli, l'appel est confirmé **sur le téléphone** (jamais
  ACTION_CALL). L'audio côté Ubuntu dépendra du Bluetooth/HFP (plus tard).
- Côté Ubuntu : fenêtre **« Contacts »** (recherche nom/numéro, fiche avec
  numéros + emails, bouton « Envoyer SMS » qui ouvre la fenêtre Messages sur le
  fil existant ou en mode **nouveau message** par numéro, bouton « Appeler »).

### Phase 3 — Connexion sans câble (Wi-Fi)

- Fenêtre **« Connexion Android »** : choix USB/ADB forward
  (`http://127.0.0.1:8765`) ou **Wi-Fi** (`http://IP_TELEPHONE:8765`), champs
  IP/port, **Tester la connexion** (`/v1/health`), **Utiliser cette connexion**
  (persisté dans `config.json`, pont + backend SMS + temps réel reconfigurés
  immédiatement), et **découverte automatique** (scan léger du /24 local sur le
  port 8765, confirmation par `/v1/health`, sans bloquer GTK).
- L'appairage PIN reste possible après bascule Wi-Fi ; le token persiste entre
  les transports. ADB USB reste le fallback. Le Bluetooth reste réservé à
  l'audio (la synchronisation sans câble passe par le Wi-Fi).
- La fenêtre principale affiche le mode courant : **USB / ADB forward**,
  **Wi-Fi (IP)** ou **indisponible**.

### Phase 4 — UX

- Page principale réorganisée en sections : **Téléphone Android** (connexion,
  batterie, serveur, SMS, notifications), **Communication** (Messages,
  Contacts, Notifications), **Fichiers et photos**, **Connexion**,
  **Audio et affichage**, ADB Wi-Fi (avancé). Icônes GTK symboliques, états
  OK ✓ / indisponible / « — » plus clairs, dans les variantes Adwaita et GTK pur.

### Limites restantes (V1.0)

- `RemoteInput` / envoi RCS toujours **hors scope** ;
- l'ouverture du dialer (`/v1/call/start`) peut être bloquée par Android 10+
  quand l'app Companion est en arrière-plan écran éteint (limitation système) ;
- pas de transport Bluetooth pour la synchronisation (Wi-Fi ou ADB) ;
- token/PIN toujours en mémoire côté Android (re-appairage après redémarrage
  du service) ;
- la suppression de fichiers est récursive pour les dossiers — confirmation
  explicite côté UI, racines non supprimables.

## Structure du projet

```
phonelink-ubuntu/
├── main.py                      ← Point d'entrée
├── app/
│   ├── ui/
│   │   ├── main_window.py       ← Fenêtre principale (sections V1.0)
│   │   ├── sms_window.py        ← Messages (SMS/MMS/RCS + compose_to)
│   │   ├── notifications_window.py ← Notifications Android
│   │   ├── files_window.py      ← Fichiers Android (V1.0)
│   │   ├── contacts_window.py   ← Contacts (V1.0)
│   │   ├── connection_window.py ← Connexion USB/Wi-Fi + scan (V1.0)
│   │   ├── gallery_window.py    ← Galerie photos
│   │   └── widgets.py           ← Helpers UI
│   ├── core/
│   │   ├── android_bridge.py    ← client HTTP du Companion (SMS, fichiers, contacts…)
│   │   ├── event_listener.py    ← temps réel (/v1/events) + notifications bureau
│   │   ├── sms.py               ← modèle + backends SMS
│   │   ├── files.py             ← dossier Téléchargements + helpers fichiers
│   │   ├── discovery.py         ← scan réseau local (port 8765)
│   │   ├── config.py            ← config JSON persistée
│   │   ├── bluetooth.py         ← bluetoothctl
│   │   ├── audio.py             ← pactl
│   │   ├── adb.py               ← adb
│   │   ├── scrcpy.py            ← scrcpy
│   │   ├── photos.py            ← adb pull + xdg-open
│   │   └── system_checks.py     ← diagnostic
│   └── utils/
│       ├── commands.py          ← subprocess wrapper
│       └── logger.py            ← logging
├── android-companion/           ← app Android (NanoHTTPD, Foreground Service)
└── docs/
    ├── architecture.md
    ├── installation.md
    ├── troubleshooting.md
    └── roadmap.md
```
