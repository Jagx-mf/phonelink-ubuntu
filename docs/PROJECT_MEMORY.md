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

## V0.5 — SMS réels (validée)

* Lecture SMS classiques via `Telephony.Sms` / `content://sms`
* Envoi SMS réel via `SmsManager` (multipart), avec confirmation explicite côté GTK
* Résolution des noms via `ContactsContract` (READ_CONTACTS)
* Garde-fou `allow_real_send` : aucun SMS ne part sans action utilisateur

## V0.6 — Provider canonique + dédup SMS/MMS/RCS (validée)

### Lecture élargie (parité KDE Connect)

* SMS classiques : `Telephony.Sms` / `content://sms`
* Surface élargie : `content://mms-sms`
* MMS : `content://mms`
* Texte MMS : `content://mms/part` (parts `text/plain`) — débloque l'historique récent (ex. Cathy après le 28/05)
* Lazy loading :

  * `/v1/conversations` reste léger (pas de lecture des parts MMS)
  * `/v1/messages?conversation_id=ID` charge le détail au clic (lit les parts MMS)
* Cache GTK par `conversation_id` (rechargement seulement sur « Rafraîchir »)
* Notifications Android via `NotificationListenerService` pour RCS / temps réel / futur RemoteInput

### Découverte importante

Le provider SMS/MMS est la **source canonique de l'historique**.
Les notifications RCS sont un **complément**, pas une source équivalente à afficher
systématiquement comme conversation séparée dans la liste principale.

### Problème rencontré

Après l'ajout des notifications RCS, certaines conversations apparaissaient en doublon :

* 36608
* C3dPasChere
* Fr Travail
* StudiALT
* Weldom
* Cathy en MMS/RCS séparé

### Cause réelle

1. Côté Android :

   * `RcsMessageStore` pouvait contenir deux clés pour le même fil RCS
     (exemple : `53` et `shortcut:53`)
   * ces clés non canoniques venaient du `NotificationListener` (et d'un
     `rcs_store.json` hérité d'une version antérieure)

2. Côté Ubuntu/Python :

   * `app/core/sms.py` ajoutait les fils RCS dans la liste principale même quand
     ils étaient déjà couverts par le provider SMS/MMS

3. Cas Cathy :

   * le fil provider MMS id 4 portait le thread réel avec le placeholder `"MMS"`
   * le fil RCS portait le vrai texte récent
   * les deux représentaient le **même** échange réel récent
   * l'ancien fil Cathy id 40 correspond à un **autre numéro** et doit rester séparé

### Correction appliquée

1. Android :

   * `RcsNotificationListener.kt` stabilise les clés RCS (`stableConversationKey`)
   * `RcsMessageStore.kt` canonicalise et déduplique les fils
     (`canonicalConversationKey` / `deduplicatedThreads`)
   * `53` et `shortcut:53` représentent désormais le **même fil logique**

2. Python/GTK (`app/core/sms.py`) :

   * `/v1/conversations` est traité comme **historique canonique**
   * `_match_rcs_to_provider()` rapproche chaque fil RCS du provider :

     * RCS déjà couvert par le provider → **masqué** dans la liste, **pas** de fusion
     * RCS rattachable de façon fiable à un thread provider → **injecté au chargement**
       du fil (`_merge_rcs_messages`), avec dédup stricte `(seconde, corps normalisé)`
     * RCS réellement non couvert → **conservé visible en lecture seule**
   * désambiguïsation par proximité temporelle (fenêtre bornée 6 h) :
     deux contacts homonymes ne sont **pas** fusionnés aveuglément
   * l'envoi SMS classique reste basé sur le **thread provider**
   * RCS reste **non envoyable** tant que RemoteInput n'est pas implémenté

3. `android_bridge.py` :

   * parsing enrichi avec `sender` pour comparer fils RCS et provider

### État validé après correction

* 36608 apparaît une seule fois
* C3dPasChere apparaît une seule fois
* Fr Travail apparaît une seule fois
* StudiALT / Weldom ne sont plus doublonnés inutilement
* Cathy récente est rattachée proprement au bon fil provider (id 4)
* l'autre Cathy (autre numéro, id 40) reste séparée
* SMS classiques fonctionnent
* MMS restent lisibles
* historique Cathy récent reste visible
* lazy loading conservé
* cache GTK conservé

### Validation terrain datée — 2026-06-08

* Validation après redémarrage du téléphone et de l'application Android Companion
* L'application GTK redémarre correctement
* Les conversations SMS/MMS/RCS restent visibles après redémarrage
* La conversation Cathy récente reste lisible
* Les doublons principaux ne réapparaissent pas visuellement
* L'envoi SMS classique fonctionne encore après les changements provider-first SMS/MMS/RCS
* Le modèle provider-first reste validé
* `RemoteInput` / envoi RCS reste hors scope

* appairage Android conservé
* pas de retour à V0.5
* pas de suppression de `rcs_store.json`

### Tests effectués

* `py_compile` sur les fichiers Python modifiés : OK
* `git diff --check` : OK
* `/v1/health` : OK
* `/v1/conversations` : OK
* `/v1/messages?conversation_id=4` : OK
* `/v1/rcs/messages` : OK
* Test visuel GTK : doublons corrigés
* APK Android rebuild + installée après les modifications Kotlin

### Décision de conception (modèle retenu, proche KDE Connect)

* provider SMS/MMS = **source canonique** de l'historique
* notifications RCS = **complément**
* ne pas afficher les notifications RCS comme conversations séparées si elles sont
  déjà représentées par le provider
* ne pas fusionner aveuglément deux contacts homonymes
* en cas d'identité ambiguë : **mieux vaut garder séparé** que perdre/mélanger des messages

### À ne pas refaire (garde-fous)

* ne pas réintroduire une fusion globale agressive SMS/MMS/RCS
* ne pas supprimer automatiquement le cache RCS (`rcs_store.json`)
* ne pas revenir au modèle V0.5
* garder le modèle canonique **provider + enrichissement notifications**

### Risques restants

* certains fils MMS-only peuvent encore afficher un nom vide ou `"MMS"`
* point **hors scope** pour l'instant afin de préserver les performances de `/v1/conversations`
* une future V0.6.1 / V0.7 pourra résoudre les noms MMS via `content://mms/{id}/addr`
  avec mesure de performance
* RemoteInput / réponse RCS reste **hors** V0.6 actuelle

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

Date : 2026-06-05

Validation V0.6 — modèle provider-first + dédup SMS/MMS/RCS :

Android Companion
→ ADB
→ Port Forward
→ Pairing
→ Token
→ Conversations (provider canonique : sms + mms + mms/part)
→ Notifications RCS (complément, dédupliqué)
→ GTK Messages (doublons corrigés)

Statut :
V0.6 validée.
Doublons SMS/MMS/RCS corrigés, comportement rapproché de KDE Connect.
Reste : noms MMS-only vides (hors scope), RemoteInput / réponse RCS (V0.6.1+).
