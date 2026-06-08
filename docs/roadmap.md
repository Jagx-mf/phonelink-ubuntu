# Roadmap PhoneLink Ubuntu

> **État réel au 2026-06-08.** Le projet a dépassé le plan initial ci-dessous
> (rédigé en V0.1). Fonctions livrées et validées terrain : SMS/MMS/RCS réels
> provider-first (V0.6), envoi SMS classique (V0.6), serveur Android en
> Foreground Service (V0.7), batterie/statut + fenêtre Notifications Android
> (V0.8), **temps réel** SMS/notifications + notification bureau `notify-send` +
> appairage depuis l'accueil (V0.9). Détails : `docs/PROJECT_MEMORY.md`.
>
> `RemoteInput` / envoi RCS restent **hors scope**.

## Prochaines phases (après la phase temps réel)

### Phase 1 — Explorateur de fichiers Android

- [ ] Afficher les dossiers Android (type « Mes fichiers »).
- [ ] Naviguer dans `DCIM`, `Download`, `Pictures`, `Movies`, `Documents` selon
      permissions.
- [ ] Copier un fichier téléphone → Ubuntu et Ubuntu → téléphone.
- [ ] Déplacer / renommer / supprimer si raisonnable et sûr.
- [ ] Privilégier une API Companion propre ; ADB en fallback éventuel.
- [ ] Ne pas casser l'import photos existant.

### Phase 2 — Contacts

- [ ] Bouton « Contacts » : liste, barre de recherche, fiche simple.
- [ ] Envoyer un SMS à un contact ; lancer un appel si possible.
- [ ] Préparer l'intégration future audio Bluetooth/HFP.
- [ ] `READ_CONTACTS` côté Android ; ne pas refondre le module SMS.

### Phase 3 — Connexion sans câble

- [ ] Connexion Wi-Fi prioritaire (découverte réseau local, appairage).
- [ ] Serveur Android joignable **sans** `adb forward` ; config IP/port côté Ubuntu.
- [ ] Reconnexion automatique.
- [ ] Bluetooth en complément si possible ; ADB USB en fallback.
- [ ] Documenter les limites Android / réseau local.

### Phase 4 — Design / UX finale

- [ ] Interface modernisée, meilleure page d'accueil.
- [ ] Cartes téléphone / statut / messages / notifications, icônes, thème cohérent.
- [ ] Meilleures fenêtres Messages et Notifications, meilleure navigation.
- [ ] Captures d'écran dans le README ; préparation d'une version installable.
- [ ] Repoussée après validation fonctionnelle des phases précédentes.

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
