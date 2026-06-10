# Roadmap PhoneLink Ubuntu

> **État réel au 2026-06-10.** Le projet a dépassé le plan initial ci-dessous
> (rédigé en V0.1). Fonctions livrées et validées terrain : SMS/MMS/RCS réels
> provider-first (V0.6), envoi SMS classique (V0.6), serveur Android en
> Foreground Service (V0.7), batterie/statut + fenêtre Notifications Android
> (V0.8), **temps réel** SMS/notifications + notification bureau `notify-send` +
> appairage depuis l'accueil (V0.9). Les **phases 1–4** ci-dessous sont
> implémentées en V1.0 (branche `feat/full-phone-link-completion-test`,
> validation terrain à faire). Détails : `docs/PROJECT_MEMORY.md` et README.
>
> `RemoteInput` / envoi RCS restent **hors scope**.

## Phases V1.0 (implémentées — à valider terrain)

### Phase 1 — Explorateur de fichiers Android ✓ (implémentée)

- [x] Afficher les dossiers Android (racines publiques type « Mes fichiers »).
- [x] Naviguer dans `DCIM`, `Download`, `Pictures`, `Movies`, `Music`,
      `Documents` selon permissions (`/v1/files/roots`, `/v1/files/list`).
- [x] Copier un fichier téléphone → Ubuntu (`/v1/files/download`, streaming)
      et Ubuntu → téléphone (`/v1/files/upload`, octet-stream brut).
- [x] Renommer / supprimer (récursif, racines protégées) / nouveau dossier,
      avec confirmation côté UI (`/v1/files/rename|delete|mkdir`).
- [x] API Companion propre (token requis, anti path-traversal) ; ADB reste le
      fallback photos.
- [x] Import photos existant inchangé.
- [ ] Validation terrain (téléchargement/upload réels, gros fichiers).

### Phase 2 — Contacts ✓ (implémentée)

- [x] Bouton « Contacts » : liste, barre de recherche, fiche simple
      (`/v1/contacts`, `/v1/contacts/search`).
- [x] Envoyer un SMS à un contact (fil existant ou nouveau numéro via
      `compose_to`) ; appel via `POST /v1/call/start` (**ACTION_DIAL** : le
      dialer s'ouvre sur le téléphone, confirmation sur place).
- [x] Audio appel côté Ubuntu : documenté comme dépendant du Bluetooth/HFP
      (intégration future).
- [x] `READ_CONTACTS` côté Android (déjà demandée avec les permissions SMS) ;
      module SMS non refondu.
- [ ] Validation terrain (gros carnets d'adresses, contacts sans numéro).

### Phase 3 — Connexion sans câble ✓ (implémentée)

- [x] Connexion Wi-Fi (fenêtre « Connexion Android » : IP/port, test
      `/v1/health`, persistance `config.json`, appairage possible ensuite).
- [x] Serveur Android joignable **sans** `adb forward` (NanoHTTPD écoute déjà
      sur toutes les interfaces, IP affichée dans l'app Companion).
- [x] Découverte automatique : scan léger du /24 local sur le port 8765,
      confirmation `/v1/health`, sans bloquer GTK (`app/core/discovery.py`).
- [x] ADB USB conservé en fallback ; affichage clair du mode (USB / Wi-Fi /
      indisponible) sur la page principale.
- [x] Bluetooth : documenté comme réservé à l'audio (pas de transport sync).
- [ ] Reconnexion automatique avancée (re-scan auto en cas de changement d'IP).
- [ ] Validation terrain (réseaux avec isolation client Wi-Fi, IP dynamique).

### Phase 4 — Design / UX ✓ (première passe)

- [x] Page d'accueil réorganisée : sections Téléphone Android / Communication /
      Fichiers et photos / Connexion / Audio et affichage (Adwaita + GTK pur).
- [x] Icônes symboliques, états OK ✓ / indisponible / « — » plus clairs,
      ligne « Connexion » (USB / Wi-Fi / indisponible).
- [ ] Captures d'écran dans le README ; version installable (plus tard).

---

## Plan initial (historique V0.1)

## V0.1 — Interface de contrôle de base ✓ (actuel)

- [x] Fenêtre GTK4/Adwaita — zone status + zone actions
- [x] Détection des appareils Bluetooth appairés (bluetoothctl)
- [x] Détection du profil audio actif A2DP / HSP/HFP (pactl)
- [x] Affichage micro Ubuntu actif et sortie audio active
- [x] Reconnexion au téléphone en un clic
- [x] Scan Bluetooth (bluetoothctl scan on/off)
- [x] Ouverture pavucontrol et paramètres GNOME Bluetooth
- [x] Guide mode appel (5 étapes)
- [x] Lancement scrcpy avec vérification ADB préalable
- [x] Import photos via adb pull (USB ou ADB Wi-Fi)
- [x] Ouverture du dossier photos local
- [x] Galerie photo intégrée (miniatures des photos importées localement)
- [x] Accès sans câble via ADB over Wi-Fi (tcpip / connect / disconnect)
- [x] Config persistante JSON (MAC téléphone + hôte/port ADB Wi-Fi)
- [x] Diagnostic système (tous les outils)
- [x] Logging structuré (~/.local/share/phonelink-ubuntu/phonelink.log)
- [x] Fallback GTK4 pur si libadwaita absent

## V0.2 — UX et réactivité

- [ ] Adw.Toast notifications (remplacer les dialogs d'info simples)
- [ ] Spinner/indicateur pendant les opérations longues (connexion, import)
- [ ] Auto-refresh toutes les 30 secondes
- [x] Mémorisation de la MAC du téléphone configuré (fichier JSON)
- [ ] Changement de profil audio BT directement depuis l'UI (pactl set-card-profile)
- [ ] Affichage du niveau de batterie du téléphone (adb shell dumpsys battery)
- [ ] Icône de statut dans l'en-tête (vert/rouge selon connexion BT)

## V0.3 — Surveillance en temps réel

- [ ] Écoute des events D-Bus BlueZ (connexion/déconnexion automatique)
- [ ] Notification GNOME quand le téléphone se connecte ou déconnecte
- [ ] Indicateur dans la zone système GNOME (via StatusNotifierItem)
- [ ] Mode daemon optionnel (tourne en arrière-plan sans fenêtre)

## V0.4 — Fichiers et MTP

- [ ] Parcourir les fichiers du téléphone via MTP (go-mtpfs ou aft-mtp-mount)
- [ ] Transfert bidirectionnel drag & drop dans Nautilus
- [ ] Montage automatique du téléphone à la connexion USB

## V0.5 — SMS et notifications

- [ ] Lecture des SMS via ADB (content provider android.provider.Telephony)
- [ ] Historique d'appels
- [ ] Notification GNOME pour les SMS entrants (polling ADB)
- [ ] Réponse aux SMS depuis le bureau (via scrcpy input ou ADB)

## V1.0 — Application complète et publiable

- [ ] Packaging Flatpak (sandboxé, portails XDG pour Bluetooth et fichiers)
- [ ] Intégration D-Bus native python-dbus (sans bluetoothctl)
- [ ] Support multi-téléphones avec profils
- [ ] Thème sombre/clair automatique (suit le thème GNOME)
- [ ] Localisation i18n (français, anglais)
- [ ] Documentation utilisateur complète (help.gnome.org style)
- [ ] Tests unitaires et intégration (pytest-gtk)
- [ ] Publication sur Flathub
