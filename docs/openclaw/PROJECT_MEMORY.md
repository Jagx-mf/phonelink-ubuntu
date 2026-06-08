# Analyse du dépôt PhoneLink Ubuntu

Date d'analyse : 2026-05-31

## État projet — 2026-06-04 — après validation terrain V0.6

Branche actuelle : `feat/v0.6-rcs-notifications`.

La V0.5 est validée : SMS réels Android, appairage PIN/token, backend Android
automatique après appairage, fallback mock conservé et interface GTK
fonctionnelle.

La V0.6 est validée sur le terrain pour la lecture étendue SMS/MMS/RCS-like :
PhoneLink Ubuntu affiche maintenant l'historique récent de la conversation
Cathy au-delà du 28/05, comme KDE Connect.

### Point technique découvert

PhoneLink lisait initialement uniquement `Telephony.Sms` / `content://sms`. Cela
bloquait l'historique de certaines conversations, notamment Cathy après le
28/05.

KDE Connect lit plus largement les providers Android publics :

- `content://mms-sms` ;
- `content://mms` / `Telephony.Mms` ;
- `content://mms/part`.

Pour Cathy, `content://sms` s'arrêtait au 28/05, mais
`content://mms-sms/conversations` voyait le `thread_id=4` au 04/06. La ligne
récente exposait des métadonnées MMS/RCS-like (`ct_t=text/plain`, `m_type=132`,
`msg_box=1`) avec `body=null` et `address=null`. Le texte était récupérable dans
les parts MMS via `content://mms/part`, filtré par `mid = _id`.

Cause résolue : la lecture provider était trop limitée. Le correctif validé est
la lecture `mms-sms` / `mms` + parts MMS `text/plain` / `text/*`, avec fallback
`_data` via `ContentResolver.openInputStream()`, plus lazy loading pour éviter
les timeouts.

### Ce qui fonctionne maintenant

- SMS classiques via `Telephony.Sms`.
- Conversations via provider `mms-sms` / `mms`.
- Lecture des parts MMS via `content://mms/part`.
- Conversation Cathy validée visuellement dans GTK avec les messages après le
  28/05.
- `/v1/conversations` reste léger et rapide ; il ne lit pas les parts MMS.
- `/v1/messages?conversation_id=<ID>` charge les détails uniquement au clic :
  SMS + MMS + parts MMS, tri ancien -> récent.
- Cache GTK/Python par `conversation_id` fonctionnel : retour instantané sur une
  conversation déjà ouverte ; le bouton Rafraîchir force le rechargement.
- Plus de timeout GTK après optimisation du lazy loading.
- Appairage GTK avec cadenas fonctionnel.
- Backend Android automatique fonctionnel après appairage.
- Notifications Android ajoutées pour préparer les RCS via
  `NotificationListenerService`, `getActiveNotifications()` et
  `MessagingStyle`.
- Fallback mock conservé.

### Ce qui reste à faire

- Stabiliser encore la V0.6 avec plusieurs conversations réelles.
- Tester redémarrage téléphone et redémarrage app companion.
- Tester la persistance du cache RCS local.
- Tester l'envoi SMS classique après les changements provider/MMS.
- Corriger ou valider définitivement les endpoints debug si besoin :
  `/v1/debug/notifications`, `/v1/debug/sms-provider`,
  `/v1/debug/mms-parts`.
- Préparer la V0.6.1 : réponse RCS via `RemoteInput`.
- Ne pas merger dans `main` avant validation complète.

### Contraintes importantes

- Ne pas lire la base privée Google Messages.
- Pas de root.
- Pas de contournement Android.
- Garder l'approche propre type KDE Connect : providers publics Android +
  notifications officielles.
- Garder le mock/fallback.
- Garder `RemoteInput` hors V0.6 actuelle.

### Dernière validation terrain

- Date : 2026-06-04.
- Résultat : PhoneLink Ubuntu affiche enfin l'historique récent de Cathy comme
  KDE Connect.
- Cause résolue : lecture provider trop limitée.
- Correctif validé : lecture `mms-sms` + parts MMS + lazy loading.

### Validation terrain complémentaire — 2026-06-08

- Validation après redémarrage du téléphone et de l'application Android Companion.
- L'application GTK redémarre correctement.
- Les conversations SMS/MMS/RCS restent visibles après redémarrage.
- La conversation Cathy récente reste lisible.
- Les doublons principaux ne réapparaissent pas visuellement.
- L'envoi SMS classique fonctionne encore après les changements provider-first
  SMS/MMS/RCS.
- Le modèle provider-first reste validé.
- `RemoteInput` / envoi RCS reste hors scope.

## État projet — V0.7 — serveur Android dans un Foreground Service (en cours)

Branche : `feat/v0.7-android-foreground-service`.

Objectif : stabiliser l'app Android Companion. Le serveur HTTP NanoHTTPD
(`CompanionServer`) est déplacé de `MainActivity` vers un Foreground Service
Android (`CompanionForegroundService`) afin de **survivre** à la fermeture ou la
mise en arrière-plan de l'activité.

Changements (Android uniquement) :

- nouveau `CompanionForegroundService.kt` : héberge `CompanionServer`,
  notification persistante + canal Android 8+, `startForeground` type
  `dataSync`, `START_STICKY`, action `STOP` ;
- `MainActivity` pilote le service (start/stop) au lieu d'héberger le serveur ;
  l'UI affiche toujours statut/IP/port/PIN/appairage/SMS/RCS ;
- `PairingManager.shared` : singleton de processus partagé Activity ↔ Service
  (PIN affiché = token vérifié) ;
- manifest : `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_DATA_SYNC`,
  `POST_NOTIFICATIONS` + `foregroundServiceType="dataSync"` ;
- `versionName` 0.6.0 → 0.7.0, `versionCode` 3 → 4.

Inchangé : endpoints V0.6, appairage PIN/token, modèle provider-first
SMS/MMS/RCS, `RemoteInput`/envoi RCS hors scope, aucun fichier Python touché,
client Ubuntu non modifié.

Tests : `assembleDebug` OK (APK debug ~5,6 Mo), `git diff --check` OK, aucun
`.py` modifié.

Limites restantes : PIN/token en mémoire (perdus si processus tué / régénérés
au redémarrage `START_STICKY`), persistance à ajouter plus tard ; test de
redémarrage complet du téléphone avec serveur survivant en arrière-plan à
valider sur le terrain.

## État projet — V0.8 — batterie/statut téléphone + notifications Android (en cours)

Branche : `feat/v0.8-device-status-notifications`.

Objectif : deux fonctionnalités complémentaires, sans casser la lecture
SMS/MMS/RCS ni le modèle provider-first, sans `RemoteInput`, sans envoi RCS.

Endpoints ajoutés (Android, token requis) :

- `GET /v1/device/status` : batterie (`battery_level`, `battery_charging`,
  `battery_status`) lue via `Intent.ACTION_BATTERY_CHANGED` / `BatteryManager`
  (API standard, aucune dépendance), + `device`, `server_running`,
  `sms_permission`, `notification_access`, `default_sms_app`, `api_version`.
- `GET /v1/notifications` : snapshot lecture seule des notifications actives
  (toutes apps) via `RcsNotificationListener.activeNotificationsSnapshot()` ;
  filtre les résumés de groupe, notifications en cours et vides ; renvoie
  `{ status: "listener_not_connected", notifications: [] }` (HTTP 200) si le
  listener n'est pas connecté.

Changements :

- Android : `CompanionServer.kt` (2 routes guarded + helper batterie),
  `RcsNotificationListener.kt` (snapshot lecture seule, aucune écriture store),
  `versionName` 0.7.0 → 0.8.0, `versionCode` 4 → 5.
- Python : `android_bridge.py` (dataclasses `DeviceStatus` /
  `AndroidNotification`, `get_device_status()` qui ne lève jamais,
  `list_notifications()`).
- GTK : `main_window.py` (section « Téléphone Android » + action «
  Notifications Android », alimentées par le thread de refresh existant),
  nouveau `app/ui/notifications_window.py` (fenêtre lecture seule).

Inchangé : `/v1/health` et endpoints V0.6/V0.7, modèle provider-first
SMS/MMS/RCS, envoi SMS classique, Foreground Service V0.7. `RemoteInput` /
envoi RCS hors scope.

Tests : `py_compile` OK (4 fichiers .py), `assembleDebug` BUILD SUCCESSFUL (APK
debug ~5,7 Mo), `git diff --check` OK. Tests terrain (APK 0.8.0 + curl + GTK) à
valider.

Les sections ci-dessous restent l'analyse historique initiale du dépôt en V0.1.

## Synthèse

PhoneLink Ubuntu est une application desktop Python/GTK4 destinée à piloter un téléphone Android depuis Ubuntu/GNOME. Le projet est en V0.1, avec une architecture simple et lisible : une fenêtre principale GTK/libadwaita, des modules `core` spécialisés par domaine, et un wrapper central pour les appels système.

Le dépôt est cohérent avec son ambition actuelle : fournir une interface locale autour de `bluetoothctl`, `pactl`, `adb`, `scrcpy`, `pavucontrol` et quelques outils XDG/GNOME. Il n'y a pas encore de tests automatisés, pas de persistance de configuration utilisateur, ni de packaging installable réellement éprouvé.

## Architecture

```text
phonelink-ubuntu/
├── main.py
├── app/
│   ├── ui/
│   │   ├── main_window.py
│   │   └── widgets.py
│   ├── core/
│   │   ├── adb.py
│   │   ├── audio.py
│   │   ├── bluetooth.py
│   │   ├── photos.py
│   │   ├── scrcpy.py
│   │   └── system_checks.py
│   └── utils/
│       ├── commands.py
│       └── logger.py
├── docs/
│   ├── architecture.md
│   ├── installation.md
│   ├── roadmap.md
│   └── troubleshooting.md
├── assets/
│   └── .gitkeep
├── pyproject.toml
├── requirements.txt
├── README.md
└── .gitignore
```

### Découpage fonctionnel

- `main.py` initialise le logging, crée une `Adw.Application` si libadwaita est disponible, sinon une `Gtk.Application`, puis affiche `MainWindow`.
- `app/ui/main_window.py` contient la majeure partie de l'application : construction UI, rafraîchissement de statut, handlers des actions utilisateur.
- `app/ui/widgets.py` fournit un helper de dialogue compatible Adwaita ou GTK pur.
- `app/core/bluetooth.py` encapsule `bluetoothctl`.
- `app/core/audio.py` encapsule `pactl` et `pavucontrol`.
- `app/core/adb.py` encapsule `adb devices`, `adb pull` et quelques lectures de propriétés.
- `app/core/scrcpy.py` lance et garde une référence au processus `scrcpy`.
- `app/core/photos.py` orchestre l'import photo vers le dossier XDG Pictures.
- `app/core/system_checks.py` diagnostique les commandes et le service Bluetooth.
- `app/utils/commands.py` centralise `subprocess.run`, `subprocess.Popen` et `shutil.which`.
- `app/utils/logger.py` configure les logs console et fichier.

### Flux d'exécution

1. L'application démarre via `python main.py` ou l'entrée console `phonelink-ubuntu`.
2. La fenêtre affiche des statuts initiaux.
3. `_refresh_status()` lance un thread daemon.
4. Le thread interroge Bluetooth, audio, ADB et scrcpy.
5. Le résultat revient dans le thread GTK via `GLib.idle_add()`.
6. Les actions utilisateur lancent elles aussi les opérations longues dans des threads daemon.

Cette séparation est saine pour une application GTK : les appels bloquants restent hors du thread UI, et les mises à jour GTK repassent par la boucle principale.

## Technologies utilisées

- Python 3.11+.
- PyGObject avec GTK 4.
- libadwaita si disponible, avec fallback GTK4.
- Subprocess Python pour orchestrer les outils système.
- BlueZ via `bluetoothctl`.
- PulseAudio/PipeWire-pulse via `pactl`.
- Android Debug Bridge via `adb`.
- scrcpy pour l'affichage du téléphone.
- XDG via `xdg-open` et `xdg-user-dir`.
- systemd via `systemctl is-active bluetooth`.
- Packaging Python via `setuptools`.

## Dépendances

### Dépendances Python

Le projet ne déclare aucune dépendance PyPI dans `pyproject.toml`. C'est volontaire : PyGObject est attendu comme dépendance système Ubuntu.

`requirements.txt` est documentaire et ne contient pas de paquet à installer.

### Dépendances système

- `python3`
- `python3-gi`
- `python3-gi-cairo`
- `gir1.2-gtk-4.0`
- `gir1.2-adw-1`
- `bluez`
- `pavucontrol`
- `adb`
- `scrcpy`
- `xdg-open`
- `xdg-user-dir`
- `gnome-control-center`
- `pactl`
- `wpctl` pour le diagnostic, même s'il n'est pas utilisé ailleurs.

### Dépendances implicites

- Session graphique GTK fonctionnelle.
- Environnement GNOME ou proche GNOME pour `gnome-control-center`.
- Bluetooth géré par BlueZ.
- Audio exposé par PulseAudio ou PipeWire-pulse.
- Téléphone Android avec appairage Bluetooth et/ou débogage USB activé.

## Points forts

- Architecture simple et facile à lire.
- Bon isolement des commandes système dans `app/utils/commands.py`.
- Pas d'utilisation de `shell=True`.
- Pas de `sudo` automatique.
- Timeouts présents sur les commandes bloquantes.
- Logging structuré vers `~/.local/share/phonelink-ubuntu/phonelink.log`.
- Documentation déjà correcte pour installation, dépannage, architecture et roadmap.
- Fallback prévu si libadwaita n'est pas disponible.
- Opérations longues exécutées dans des threads pour préserver la réactivité de l'UI.

## Bugs potentiels et risques

### Import PyGObject avant fallback réel

`main.py` importe `gi`, exige GTK 4, puis tente Adwaita. Si `gi` ou GTK 4 est absent, l'application échoue immédiatement avant d'afficher un message utilisateur clair. C'est normal pour une dépendance système dure, mais le diagnostic pourrait être plus explicite côté CLI.

### API Adwaita potentiellement trop récente

Le code utilise `Adw.ToolbarView` et `Adw.AlertDialog`. Ces APIs ne sont pas disponibles sur toutes les versions de libadwaita installées sur Ubuntu. Le fallback ne s'active que si `gi.require_version("Adw", "1")` échoue, pas si la bibliothèque existe mais ne fournit pas certaines classes. Une Ubuntu avec libadwaita plus ancienne peut donc crasher au moment de construire l'UI.

### Sélection du téléphone fragile

`PHONE_NAME = "S21 FE de Mickael"` et `_find_phone()` cherchent des mots-clés (`s21`, `mickael`, `samsung`, `galaxy`) puis prennent le premier appareil appairé si aucun match n'est trouvé. Sur une machine avec plusieurs périphériques Bluetooth, l'action "Reconnecter le téléphone" peut viser le mauvais appareil.

### Pas de configuration persistante

La MAC du téléphone n'est gardée qu'en mémoire. Au redémarrage, l'application redéduit la cible depuis les noms Bluetooth. Cela limite fortement la fiabilité hors du cas personnel initial.

### Scan Bluetooth sans gestion d'échec

`scan_start()` retourne toujours `True`, même si `bluetoothctl scan on` ou `scan off` échoue. L'UI relance ensuite un refresh, mais l'utilisateur ne voit pas forcément que le scan n'a pas démarré.

### Rafraîchissements concurrents possibles

Chaque clic sur rafraîchir lance un nouveau thread. Il n'y a pas de verrou ou de token de génération. Plusieurs refreshs simultanés peuvent mettre à jour l'UI dans un ordre non déterministe, surtout si `bluetoothctl`, `pactl` ou `adb` répondent lentement.

### Erreurs des callbacks GLib peu visibles

Plusieurs callbacks passés à `GLib.idle_add()` ne retournent pas explicitement `False`. En PyGObject, un retour `None` est généralement traité comme faux, mais ce comportement implicite rend les intentions moins nettes et peut compliquer le debug.

### Parsing Bluetooth et audio très dépendant des sorties locales

Le parsing repose sur les chaînes de sortie de `bluetoothctl` et `pactl`. Cela peut varier selon versions, locale, profils audio ou périphériques. Le code couvre le cas nominal mais pas beaucoup de variantes.

### Diagnostic de versions incomplet

`system_checks._get_version()` appelle `--version` pour tous les outils. Certains outils comme `bluetoothctl` ou `pavucontrol` peuvent ne pas répondre de manière utile à cette option selon distribution. Ce n'est pas bloquant, mais le diagnostic peut afficher peu d'information.

### Import photos monolithique

`adb pull /sdcard/DCIM/Camera` copie tout le dossier à chaque import. Il n'y a pas de sélection, de progression, de limite, de déduplication explicite côté UI ni d'annulation. Sur une grosse galerie, l'opération peut être longue et opaque.

### Pas de tests automatisés

Il n'y a pas de dossier `tests/`, pas de pytest configuré, et les parsers de sorties système ne sont pas couverts. Les régressions sur les fonctions de parsing ou de sélection d'appareil seront difficiles à détecter.

### Packaging console script discutable

`pyproject.toml` déclare `phonelink-ubuntu = "main:main"`. Cela peut fonctionner si le projet est installé depuis la racine, mais `main.py` n'est pas dans un package. Pour un packaging plus robuste, un module `app.__main__` ou `app.main` serait préférable.

### Couplage fort à GNOME/Ubuntu

L'application annonce Ubuntu/GNOME, donc ce n'est pas forcément un bug. Mais `gnome-control-center`, `pavucontrol`, `systemctl`, `xdg-user-dir` et les paquets apt limitent fortement la portabilité.

## Améliorations possibles

1. Ajouter une configuration utilisateur :
   - MAC du téléphone cible,
   - nom d'affichage,
   - dossier d'import,
   - préférence scrcpy.

2. Rendre la sélection du téléphone explicite :
   - liste des appareils appairés,
   - bouton "définir comme téléphone principal",
   - aucun fallback silencieux vers le premier appareil.

3. Renforcer la compatibilité libadwaita :
   - tester la présence des classes utilisées,
   - basculer vers GTK pur si `Adw.ToolbarView` ou `Adw.AlertDialog` manque,
   - documenter la version minimale réelle de libadwaita.

4. Améliorer la gestion d'état UI :
   - désactiver temporairement les actions longues,
   - ajouter spinner/progression,
   - éviter les refreshs concurrents,
   - centraliser les notifications non critiques en toasts.

5. Couvrir les parsers par des tests :
   - `bluetoothctl devices`,
   - `bluetoothctl info`,
   - `pactl list cards`,
   - `adb devices`.

6. Améliorer les erreurs utilisateur :
   - distinguer outil absent, timeout, service inactif, permission refusée,
   - afficher des actions correctives concrètes.

7. Ajouter une couche d'abstraction système :
   - interfaces ou classes injectables pour les commandes,
   - mocks faciles en tests,
   - moins de dépendance directe entre UI et modules système.

8. Préparer le packaging :
   - déplacer l'entrée principale dans le package,
   - ajouter fichier desktop,
   - ajouter icône,
   - envisager Flatpak plus tard.

## Roadmap V0.2 proposée

### Objectif V0.2

Faire passer PhoneLink Ubuntu d'une interface personnelle fonctionnelle à une application utilisable de manière fiable sur une machine Ubuntu/GNOME avec un ou plusieurs appareils Bluetooth.

### 1. Configuration persistante

- Créer un fichier de config JSON dans `~/.config/phonelink-ubuntu/config.json`.
- Stocker la MAC du téléphone principal.
- Stocker le nom d'affichage et le dossier d'import.
- Ajouter une migration simple si le fichier est absent ou incomplet.

### 2. Sélection du téléphone

- Ajouter une section "Téléphone principal".
- Afficher les appareils Bluetooth appairés.
- Permettre de choisir explicitement l'appareil cible.
- Supprimer le fallback automatique vers le premier appareil.

### 3. UX des opérations longues

- Ajouter un spinner global ou par ligne d'action.
- Désactiver les boutons pendant scan, reconnexion et import.
- Remplacer les dialogues d'information simples par `Adw.Toast` quand disponible.
- Garder les dialogues seulement pour erreurs bloquantes ou guides détaillés.

### 4. Robustesse du refresh

- Ajouter un flag `_refresh_in_progress` ou un compteur de génération.
- Ignorer les résultats obsolètes si un refresh plus récent s'est terminé.
- Ajouter un auto-refresh optionnel toutes les 30 secondes.
- Éviter de lancer plusieurs threads de refresh simultanément.

### 5. Audio Bluetooth contrôlable

- Lister les profils disponibles de la carte Bluetooth.
- Ajouter une action pour passer en A2DP.
- Ajouter une action pour passer en HSP/HFP.
- Encapsuler `pactl set-card-profile` avec confirmation et message clair.

### 6. Batterie et infos téléphone

- Ajouter `adb shell dumpsys battery`.
- Afficher niveau de batterie, état de charge et modèle.
- Gérer explicitement les états ADB `unauthorized` et `offline`.

### 7. Tests minimaux

- Ajouter `pytest`.
- Tester les parsers sans dépendre des commandes système réelles.
- Tester `CommandResult`, `_fmt_profile()`, `_shorten()` et `_find_phone()`.
- Ajouter un test qui garantit l'absence de `shell=True`.

### 8. Compatibilité et packaging

- Définir la version minimale libadwaita réellement supportée.
- Ajouter un fallback si `Adw.ToolbarView` ou `Adw.AlertDialog` manque.
- Déplacer l'entrée console vers un module packagé.
- Préparer un fichier `.desktop` et une icône dans `assets/`.

## Priorités recommandées

1. Configuration persistante de la MAC téléphone.
2. Sélection explicite de l'appareil cible.
3. Protection contre refreshs concurrents.
4. Compatibilité libadwaita plus robuste.
5. Tests unitaires des parsers.
6. UX des opérations longues.

## Conclusion

Le projet est sain pour une V0.1 : petit, local, compréhensible, et prudent sur les commandes système. Les principaux risques ne sont pas des failles évidentes, mais des hypothèses trop personnelles ou trop liées à un environnement précis : nom du téléphone, version libadwaita, sorties `bluetoothctl`/`pactl`, absence de configuration persistante et absence de tests.

La V0.2 devrait donc se concentrer sur la fiabilité utilisateur : choisir explicitement le téléphone, mémoriser cette configuration, rendre les opérations longues visibles, éviter les états concurrents et couvrir les parsers critiques par des tests.
