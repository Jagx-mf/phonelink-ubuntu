# Installation de PhoneLink Ubuntu

## Prérequis système

### Python et GTK4 / libadwaita

```bash
sudo apt update
sudo apt install python3 python3-gi python3-gi-cairo \
    gir1.2-gtk-4.0 gir1.2-adw-1
```

### Bluetooth

BlueZ est inclus dans Ubuntu. Vérifiez que le service est actif :

```bash
sudo systemctl enable --now bluetooth
bluetoothctl show
```

### Audio — contrôle graphique

PipeWire est installé par défaut sur Ubuntu 22.04+. Pour le panneau de contrôle :

```bash
sudo apt install pavucontrol
```

### ADB (Android Debug Bridge)

```bash
sudo apt install adb
```

**Activer le débogage USB sur le téléphone :**
1. Paramètres → À propos du téléphone → appuyez 7× sur "Numéro de build"
2. Paramètres → Options développeurs → **Débogage USB** : activé
3. Connectez le téléphone en USB
4. Acceptez la demande de confiance qui s'affiche sur le téléphone

Vérification :

```bash
adb devices
# Doit afficher : <serial>  device  (et non "unauthorized")
```

### scrcpy

```bash
sudo apt install scrcpy
# ou version plus récente via snap :
sudo snap install scrcpy
```

## Lancement

Aucune installation Python supplémentaire n'est nécessaire.

```bash
cd phonelink-ubuntu
python main.py
```

## Vérification rapide

Depuis l'interface, cliquez **Diagnostic système** pour voir l'état de chaque outil.

Depuis le terminal :

```bash
bluetoothctl devices Paired   # Liste les appareils appairés
pactl list cards               # Cartes audio et profils actifs
adb devices                    # Appareils ADB connectés
which scrcpy                   # scrcpy installé ?
```
