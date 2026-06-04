Créer ou mettre à jour le fichier :

docs/openclaw/PROJECT_MEMORY.md

Objectif :
Conserver un état complet et factuel du projet PhoneLink Ubuntu afin de pouvoir reprendre le développement à tout moment.

Structure obligatoire :

# PhoneLink Ubuntu - Mémoire Projet

## Vision du projet

* Concurrent Linux de Microsoft Phone Link
* Communication Ubuntu ↔ Android
* Fonctionnement USB puis Wi-Fi
* Interface GTK moderne
* Aucune dépendance KDE Connect / GSConnect

## État actuel du projet

### V0.1

* Connexion Bluetooth
* Détection téléphone
* Diagnostic système

### V0.2

* Import photos ADB
* Galerie photos GTK
* Correctifs Bluetooth et ADB

### V0.3

* Interface Messages GTK
* Backend SMS abstrait
* Mock backend fonctionnel

### V0.4

* Android Companion créé
* Application Android Kotlin
* Serveur HTTP NanoHTTPD embarqué
* Endpoints :

  * GET /v1/health
  * POST /v1/pair
  * GET /v1/conversations
  * GET /v1/messages
  * POST /v1/send

### Validation effectuée

Ubuntu :

adb devices → OK

adb forward tcp:8765 tcp:8765 → OK

curl /v1/health → OK

curl /v1/pair → OK

curl /v1/conversations → OK

PhoneLink Ubuntu :

* AndroidBridge fonctionnel
* Appairage PIN → token fonctionnel
* Messages visibles dans GTK
* Backend Android sélectionnable

Android :

* APK compilé
* Installation sur Samsung S21 FE
* Serveur HTTP démarré
* Appairage fonctionnel

## Architecture actuelle

Android
↓
NanoHTTPD
↓
ADB Forward
↓
android_bridge.py
↓
sms.py
↓
GTK Messages

## Ce qui fonctionne

* Bluetooth
* Photos
* Galerie
* ADB
* Appairage PIN
* Token
* Conversations de démonstration
* Messages de démonstration

## Ce qui reste à faire

### V0.5

* READ_SMS
* SEND_SMS
* READ_CONTACTS
* SMS réels

### V0.6

* Contacts réels
* Notifications Android
* Batterie
* Presse-papiers

### V0.7

* ADB Wi-Fi automatique
* Plus besoin de câble USB

### V1.0

* SMS réels
* Contacts
* Notifications
* Photos
* Batterie
* Presse-papiers
* ADB Wi-Fi
* Appairage complet

## Commandes utiles

adb devices

adb forward tcp:8765 tcp:8765

curl http://127.0.0.1:8765/v1/health

curl -X POST http://127.0.0.1:8765/v1/pair 
-H "Content-Type: application/json" 
-d '{"pin":"PIN","client":"phonelink-ubuntu"}'

## Dernière validation

Date : 2026-06-03

Validation complète de la chaîne :

Android Companion
→ ADB
→ Port Forward
→ Pairing
→ Token
→ Conversations
→ GTK Messages

Statut :
V0.4 validée.
Prêt pour V0.5 SMS réels.

