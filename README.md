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
