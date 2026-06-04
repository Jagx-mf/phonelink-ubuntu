# PhoneLink Companion (Android) — V0.4.1

Application Android compagnon de **PhoneLink Ubuntu**. Cette première version
démarre un **petit serveur HTTP local** sur le téléphone (port `8765`) et répond
aux premiers endpoints attendus par le client Ubuntu (`app/core/android_bridge.py`).

> ⚠️ **Démo locale.** Cette version **ne lit et n'envoie aucun vrai SMS** et ne
> demande **aucune** permission `READ_SMS` / `SEND_SMS`. Les endpoints
> `/conversations` et `/messages` renvoient des **données fictives** ; `/send`
> ne fait rien. Objectif : valider le transport, l'appairage et le contrat JSON.

---

## Choix techniques

| Choix | Raison |
|-------|--------|
| **Kotlin + Android Gradle** | demandé ; pile standard, maintenable. |
| **NanoHTTPD** (`org.nanohttpd:nanohttpd:2.3.1`) | serveur HTTP embarqué minimal (~50 Ko, une classe à étendre). Plus simple et plus fiable qu'un `ServerSocket` brut à parser à la main. Seule dépendance ajoutée. |
| **org.json** | fourni par la plateforme Android → **aucune** dépendance JSON tierce. |
| **ViewBinding** | accès typé aux vues, sans `findViewById`. |
| `minSdk = 24` (Android 7.0) | couvre la grande majorité du parc, API réseau/Base64 disponibles. |
| `compileSdk/targetSdk = 34`, Java 17 | exigés par AGP 8.5. |
| Serveur lié à l'`Activity` | le plus simple pour une démo ; un *foreground service* viendra ensuite. |
| `usesCleartextTraffic="true"` | trafic HTTP local en clair assumé (pas de TLS en démo). |

Le **PIN** est un code à 6 chiffres (régénérable). Sur appairage réussi, un
**token opaque** (32 octets aléatoires, `SecureRandom`, Base64 URL-safe) est émis
et le PIN est régénéré (usage unique). L'état tient **en mémoire** : tout est
réinitialisé au redémarrage de l'app.

---

## Ouvrir le projet dans Android Studio

1. Android Studio → **File ▸ Open** → sélectionner le dossier `android-companion/`.
2. Laisser Gradle **synchroniser** (Android Studio télécharge AGP, le wrapper
   Gradle et NanoHTTPD automatiquement à la première ouverture).
3. Si un bandeau propose de générer le **Gradle Wrapper**, accepter — le fichier
   binaire `gradle/wrapper/gradle-wrapper.jar` n'est volontairement pas versionné
   (cf. `.gitignore`). En ligne de commande, on peut le générer avec :
   ```bash
   cd android-companion
   gradle wrapper --gradle-version 8.9   # nécessite un Gradle système installé
   ```

> **Pré-requis** : Android Studio (Giraffe/Koala ou plus récent) avec le SDK
> Android 34 et un JDK 17 (fourni par Android Studio).

---

## Générer l'APK

**Via Android Studio** : menu **Build ▸ Build Bundle(s) / APK(s) ▸ Build APK(s)**.
L'APK debug est produit dans :
```
android-companion/app/build/outputs/apk/debug/app-debug.apk
```

**En ligne de commande** (une fois le wrapper présent) :
```bash
cd android-companion
./gradlew assembleDebug
```

---

## Installer l'APK sur le téléphone

Activer **Options développeur ▸ Débogage USB**, brancher le téléphone, puis :
```bash
adb install -r android-companion/app/build/outputs/apk/debug/app-debug.apk
```
Ou copier l'APK sur le téléphone et l'ouvrir (autoriser l'installation de
sources inconnues). **Aucun Play Store requis.**

---

## Lancer le serveur

1. Ouvrir **PhoneLink Companion** sur le téléphone.
2. Appuyer sur **Démarrer le serveur**.
3. L'écran affiche : statut (Démarré), **adresse IP locale**, **port 8765**, et
   le **PIN d'appairage**. Bouton **Nouveau PIN** pour le régénérer.
4. Le téléphone et le PC doivent être sur le **même réseau Wi-Fi** (ou utiliser
   un port-forward ADB — voir plus bas).

---

## Tester depuis Ubuntu (curl)

Remplacer `IP_DU_TELEPHONE` par l'IP affichée dans l'app.

```bash
# 1) Santé (public)
curl http://IP_DU_TELEPHONE:8765/v1/health

# 2) Appairage avec le PIN affiché à l'écran
curl -X POST http://IP_DU_TELEPHONE:8765/v1/pair \
  -H "Content-Type: application/json" \
  -d '{"pin":"123456","client":"phonelink-ubuntu"}'
# → {"token":"..."}  (copier ce token)

# 3) Endpoints protégés (token requis)
TOKEN=collez_le_token_ici
curl http://IP_DU_TELEPHONE:8765/v1/conversations -H "Authorization: Bearer $TOKEN"
curl "http://IP_DU_TELEPHONE:8765/v1/messages?conversation_id=demo-1" -H "Authorization: Bearer $TOKEN"
curl -X POST http://IP_DU_TELEPHONE:8765/v1/send -H "Authorization: Bearer $TOKEN" \
  -d '{"conversation_id":"demo-1","body":"test"}'
# → {"sent":false,"detail":"SMS réel non implémenté dans cette version"}
```

### Variante sans Wi-Fi partagé : port-forward ADB
```bash
adb forward tcp:8765 tcp:8765
curl http://127.0.0.1:8765/v1/health
```

---

## Endpoints disponibles

| Méthode | Chemin | Auth | Réponse |
|--------|--------|------|---------|
| `GET`  | `/v1/health` | publique | `{"ok":true,"device_name":"…","api_version":"v1","paired":false}` |
| `POST` | `/v1/pair` | PIN | `200 {"token":"…"}` ou `401 {"error":"invalid_pin"}` |
| `GET`  | `/v1/conversations` | Bearer | `{"conversations":[…]}` (fictif) |
| `GET`  | `/v1/messages?conversation_id=demo-1` | Bearer | `{"messages":[…]}` (fictif) |
| `POST` | `/v1/send` | Bearer | `{"sent":false,"detail":"SMS réel non implémenté…"}` |

Sans token valide, les routes protégées renvoient `401 {"error":"unauthorized"}`.
Route inconnue → `404 {"error":"not_found"}`.

---

## Limites actuelles

- **Aucun vrai SMS** : `/conversations` et `/messages` sont fictifs, `/send` est inerte.
- **Pas de permission SMS** demandée (volontaire).
- **État en mémoire** : PIN et token perdus au redémarrage de l'app.
- **Pas de foreground service** : le serveur s'arrête si l'activité est détruite
  ou l'app tuée par le système.
- **Pas de TLS** : HTTP en clair, à réserver à un réseau local de confiance.
- **Schéma `/health` à réconcilier** : le client Ubuntu (`android_bridge`) lit
  aujourd'hui `sms_permission` / `app_version` / `device` ; cette V0.4.1 renvoie
  `ok` / `device_name` / `api_version` / `paired` (format demandé pour l'app).
  L'alignement des deux schémas est une prochaine étape côté client **ou** app.

---

## Prochaines étapes pour lire les vrais SMS Android

1. Ajouter les permissions `READ_SMS`, `SEND_SMS`, `RECEIVE_SMS` au manifeste et
   les **demander à l'exécution** (runtime permissions, Android 6+).
2. Lire les conversations via `ContentResolver` sur
   `Telephony.Sms.Conversations` / `Telephony.Sms.Inbox`/`Sent`.
3. Implémenter l'envoi réel via `SmsManager` (et persistance dans `Telephony.Sms`
   si l'app devient l'app SMS par défaut).
4. Brancher `/conversations`, `/messages`, `/send` sur ces données réelles.
5. Passer le serveur en **foreground service** (notification persistante) pour
   survivre en arrière-plan.
6. Persister le token (et option de **révocation** « oublier cet appareil »).
7. Réconcilier le schéma `/health` avec le client Ubuntu (champ `sms_permission`).
8. (Optionnel) TLS auto-signé + pinning si écoute sur le LAN.

---

## Lien avec le client Ubuntu

Le client est déjà prêt côté Ubuntu : `app/core/android_bridge.py` sait appeler
ces endpoints (mode `http`), s'appairer (`pair()` / `pair_and_save()`) et
persister le token. Voir `docs/android-backend-v0.4.md` pour la spécification
complète de l'API et du modèle de données.
