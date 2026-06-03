# Dépannage PhoneLink Ubuntu

## Le téléphone n'apparaît pas dans la liste

**Cause :** téléphone non appairé, ou bluetoothctl renvoie une erreur.

```bash
bluetoothctl devices Paired
# Si vide → appairer le téléphone depuis GNOME Bluetooth
```

Pour appairer manuellement :

```bash
bluetoothctl scan on
# (attendez que le nom du téléphone apparaisse)
bluetoothctl pair AA:BB:CC:DD:EE:FF
bluetoothctl trust AA:BB:CC:DD:EE:FF
```

---

## Profil audio détecté comme "Non détecté"

**Cause :** PipeWire n'a pas encore chargé la carte Bluetooth, ou le téléphone
vient juste de se connecter.

```bash
pactl list cards
# Cherchez un bloc "Name: bluez_card.*"
# Ligne "Active Profile:" = profil en cours
```

Si le bloc bluez est absent, reconnectez le téléphone.

---

## La reconnexion Bluetooth échoue

```bash
sudo systemctl status bluetooth
sudo systemctl restart bluetooth
```

Si le message est "Not Available" :

```bash
rfkill list bluetooth          # Vérifiez que BT n'est pas bloqué
rfkill unblock bluetooth       # Débloquer si nécessaire
```

---

## scrcpy — "Aucun appareil ADB connecté"

Étapes de diagnostic dans l'ordre :

```bash
# 1. Vérifier ADB
adb devices
# Doit afficher "<serial>  device" (pas "unauthorized")

# 2. Si "unauthorized" → sur le téléphone, accepter la popup de confiance ADB

# 3. Si le téléphone n'apparaît pas du tout
adb kill-server
adb start-server
adb devices

# 4. Vérifier que le débogage USB est activé
# Paramètres → Options développeurs → Débogage USB
```

---

## L'import de photos échoue

```bash
# Tester manuellement
adb pull /sdcard/DCIM/Camera /tmp/test-photos/

# Vérifier que le dossier existe sur le téléphone
adb shell ls /sdcard/DCIM/
```

Si le téléphone demande une autorisation d'accès aux fichiers, acceptez-la.

> Rappel : les photos passent par ADB, **pas** par Bluetooth. Le Bluetooth ne
> sert qu'à l'audio/appels et ne permet pas de parcourir la galerie Android.

---

## ADB Wi-Fi — la connexion sans câble échoue

L'accès sans câble (photos, scrcpy) passe par **ADB over Wi-Fi**. Il faut un
bootstrap initial avant de pouvoir se connecter en Wi-Fi.

```bash
# 1. Brancher le téléphone en USB (débogage activé), vérifier la connexion
adb devices            # doit afficher "<serial>  device"

# 2. Basculer en TCP/IP (bouton « Activer TCP/IP (via USB) »)
adb tcpip 5555

# 3. Récupérer l'IP Wi-Fi du téléphone, puis débrancher le câble
adb shell ip -f inet addr show wlan0    # cherchez "inet 192.168.x.x"

# 4. Se connecter sans câble
adb connect 192.168.x.x:5555            # doit répondre "connected to ..."
```

Alternative sans aucun câble : activer le **débogage sans fil** dans les Options
développeurs Android, puis utiliser l'appairage sans fil du téléphone.

Points à vérifier :
- Téléphone et PC sur **le même réseau Wi-Fi**.
- `adb connect` renvoie 0 même en cas d'échec : fiez-vous au message
  ("connected" = succès).
- Après un redémarrage du téléphone, le mode TCP/IP est perdu → refaire le
  bootstrap USB.

---

## Erreur "ModuleNotFoundError: gi" ou "cannot import gi"

```bash
sudo apt install python3-gi gir1.2-gtk-4.0
```

**Ne pas** utiliser `pip install PyGObject` sur Ubuntu : cela entre en conflit
avec les paquets système.

---

## Erreur "Cannot open display" ou fenêtre qui ne s'ouvre pas

Assurez-vous de lancer `python main.py` depuis un terminal GNOME (pas via SSH
sans redirection X11).

```bash
echo $DISPLAY   # Doit afficher :0 ou :1
```

---

## pavucontrol n'ouvre pas le bon profil BT

Dans pavucontrol :
- Onglet **Configuration** → cherchez votre carte Bluetooth
- Changez le profil : **A2DP Sink** pour l'audio haute qualité, ou
  **Headset Head Unit (HSP/HFP)** pour les appels avec micro

---

## Consulter les logs

```bash
cat ~/.local/share/phonelink-ubuntu/phonelink.log

# En temps réel pendant l'exécution
python main.py 2>&1 | tee /tmp/phonelink-debug.log
```
