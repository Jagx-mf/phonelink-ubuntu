# Roadmap PhoneLink Ubuntu

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
- [x] Import photos via adb pull
- [x] Ouverture du dossier photos local
- [x] Diagnostic système (tous les outils)
- [x] Logging structuré (~/.local/share/phonelink-ubuntu/phonelink.log)
- [x] Fallback GTK4 pur si libadwaita absent

## V0.2 — UX et réactivité

- [ ] Adw.Toast notifications (remplacer les dialogs d'info simples)
- [ ] Spinner/indicateur pendant les opérations longues (connexion, import)
- [ ] Auto-refresh toutes les 30 secondes
- [ ] Mémorisation de la MAC du téléphone configuré (fichier JSON)
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
