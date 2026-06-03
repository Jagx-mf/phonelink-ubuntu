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
    main_window.py         → Fenêtre principale (status + actions + ADB Wi-Fi)
    gallery_window.py      → Galerie photo intégrée (miniatures locales)
    widgets.py             → Helpers UI partagés (show_dialog)
  core/
    bluetooth.py           → bluetoothctl
    audio.py               → pactl
    adb.py                 → adb (USB + Wi-Fi : tcpip / connect / disconnect)
    scrcpy.py              → scrcpy
    photos.py              → adb pull + listing local + xdg-open
    config.py              → config persistante JSON (~/.config/phonelink-ubuntu)
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

## Connectivité : ce qui marche avec ou sans câble

PhoneLink combine deux canaux indépendants : **Bluetooth** (audio/appels) et
**ADB** (écran, photos, fichiers). Aucun des deux ne couvre tout seul l'ensemble
des usages.

| Fonction                       | USB (câble) | Sans câble                         |
|--------------------------------|-------------|------------------------------------|
| Audio A2DP / appels HSP/HFP    | –           | ✅ Bluetooth                        |
| Reconnexion / scan Bluetooth   | –           | ✅ Bluetooth                        |
| Affichage écran (scrcpy)       | ✅ ADB USB  | ✅ ADB Wi-Fi                        |
| Import photos (`adb pull`)     | ✅ ADB USB  | ✅ ADB Wi-Fi                        |
| Galerie photo intégrée         | ✅ (photos déjà importées) | ✅ (photos déjà importées) |

### Limite du Bluetooth pur

Le Bluetooth tel qu'utilisé ici sert **uniquement à l'audio** (profils A2DP et
HSP/HFP). Il ne permet **pas** de parcourir la galerie Android ni de récupérer
des photos : ces opérations passent obligatoirement par ADB. L'app
n'implémente pas de transfert OBEX/MTP par Bluetooth.

### Méthode recommandée sans câble : ADB over Wi-Fi

Pour les photos et l'écran sans câble, la voie recommandée est **ADB over
Wi-Fi** :

1. **Bootstrap initial** — soit brancher le téléphone une fois en USB et cliquer
   « Activer TCP/IP (via USB) » (`adb tcpip 5555`), soit activer le **débogage
   sans fil** d'Android (Options développeurs) pour s'appairer sans câble.
2. Saisir l'IP du téléphone puis « Connecter ADB Wi-Fi » (`adb connect IP:5555`).
3. Import photos et scrcpy fonctionnent alors sans câble.

Le téléphone et l'ordinateur doivent être sur le même réseau Wi-Fi. L'IP et le
port (5555 par défaut) sont mémorisés dans la config persistante.

### Galerie photo intégrée

`gallery_window.py` affiche, sous forme de miniatures, **les photos déjà
importées localement** dans `~/Images/PhoneLinkUbuntu` (chemin XDG Pictures). Le
clic ouvre la photo via `xdg-open`. La galerie ne lit pas le téléphone en direct :
elle reflète uniquement le contenu importé par `adb pull`.

## Sécurité

- Zéro `shell=True` → protection contre l'injection de commandes
- Zéro sudo automatique → l'utilisateur garde le contrôle
- Zéro réseau externe → 100% local
- Zéro modification de config Bluetooth sans confirmation utilisateur
