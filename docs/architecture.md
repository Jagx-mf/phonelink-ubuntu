# Architecture PhoneLink Ubuntu

## Principe

PhoneLink Ubuntu est une **interface de contrôle**, pas une réimplémentation
de la stack Bluetooth/audio. Elle orchestre des outils système existants
(`bluetoothctl`, `pactl`, `adb`, `scrcpy`) via subprocess encapsulé.

## Arborescence

```
main.py                    → Point d'entrée, Adw.Application / Gtk.Application
app/
  ui/
    main_window.py         → Fenêtre principale (status + actions)
    widgets.py             → Helpers UI partagés (show_dialog)
  core/
    bluetooth.py           → bluetoothctl
    audio.py               → pactl
    adb.py                 → adb
    scrcpy.py              → scrcpy
    photos.py              → adb pull + xdg-open
    system_checks.py       → vérification de tous les outils
  utils/
    commands.py            → subprocess wrapper (jamais shell=True)
    logger.py              → logging structuré (console + fichier)
```

## Flux de données

```
[GTK Main Thread]
    │
    ├─ _refresh_status()
    │       └─ threading.Thread → _fetch_status()
    │               ├─ bt_core.get_paired_devices()   → bluetoothctl (subprocess)
    │               ├─ audio_core.get_bt_card_profile()→ pactl (subprocess)
    │               ├─ adb_core.is_device_connected() → adb (subprocess)
    │               └─ scrcpy_core.is_installed()     → shutil.which()
    │                       └─ GLib.idle_add(_apply_status)
    │                               └─ Met à jour les Gtk.Label
    │
    └─ Bouton Action cliqué
            └─ threading.Thread → core module → subprocess
                    └─ GLib.idle_add → show_dialog() / _refresh_status()
```

## Règles de threading

- **Tout appel bloquant** (subprocess avec timeout > 0) se fait dans un
  `threading.Thread(daemon=True)`.
- **Tout retour vers l'UI** se fait via `GLib.idle_add()` — jamais d'appel
  GTK depuis un thread non-principal.
- `daemon=True` garantit que les threads s'arrêtent avec l'application.

## Couche commands.py

`app/utils/commands.py` est le seul endroit où `subprocess` est appelé.

- `run(cmd, timeout)` → `CommandResult` (stdout, stderr, returncode, .ok)
- `launch_background(cmd)` → `Popen` non bloquant (pour scrcpy, pavucontrol…)
- `is_installed(name)` → `shutil.which()` (pas de subprocess)
- **Jamais** `shell=True`, **jamais** de sudo automatique

## Compatibilité

| Composant       | Requis         | Fallback                       |
|-----------------|----------------|--------------------------------|
| libadwaita 1.5+ | Adw.AlertDialog| Gtk.Window custom              |
| libadwaita 1.x  | AdwApplicationWindow, PreferencesPage | Gtk.ApplicationWindow + Gtk.Box |
| GTK 4.x         | minimum requis | –                              |
| Python 3.11+    | union types    | –                              |

## Sécurité

- Zéro `shell=True` → protection contre l'injection de commandes
- Zéro sudo automatique → l'utilisateur garde le contrôle
- Zéro réseau externe → 100% local
- Zéro modification de config Bluetooth sans confirmation utilisateur
