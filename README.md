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

## Structure du projet

```
phonelink-ubuntu/
├── main.py                  ← Point d'entrée
├── app/
│   ├── ui/
│   │   ├── main_window.py   ← Fenêtre principale
│   │   └── widgets.py       ← Helpers UI
│   ├── core/
│   │   ├── bluetooth.py     ← bluetoothctl
│   │   ├── audio.py         ← pactl
│   │   ├── adb.py           ← adb
│   │   ├── scrcpy.py        ← scrcpy
│   │   ├── photos.py        ← adb pull + xdg-open
│   │   └── system_checks.py ← diagnostic
│   └── utils/
│       ├── commands.py      ← subprocess wrapper
│       └── logger.py        ← logging
└── docs/
    ├── architecture.md
    ├── installation.md
    ├── troubleshooting.md
    └── roadmap.md
```
