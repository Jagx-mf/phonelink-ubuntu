# RCS, MMS et notifications Android — V0.6

PhoneLink Ubuntu V0.6 lit les conversations Android à partir de deux surfaces
officielles :

- le provider SMS/MMS Android (`content://sms`, `content://mms`,
  `content://mms-sms`, `content://mms/part`) pour l'historique disponible ;
- les notifications Google Messages (`NotificationListenerService`) pour la
  fenêtre récente exposée par `MessagingStyle`.

> V0.6.0 = lecture + affichage GTK. L'envoi RCS via `RemoteInput` est repoussé
> à V0.6.1.

---

## 1. Diagnostic terrain validé

Le cas Cathy a confirmé l'écart avec KDE Connect :

- `Telephony.Sms` / `content://sms` s'arrêtait au 28/05.
- KDE Connect affichait l'historique récent jusqu'au 04/06.
- `content://mms-sms/conversations` voyait le thread récent (`thread_id=4`) au
  04/06.
- La ligne récente exposait des métadonnées MMS/RCS-like (`ct_t=text/plain`,
  `m_type=132`, `msg_box=1`, `body=null`, `address=null`), mais pas le texte.
- Le texte était récupérable via les parts MMS :
  `content://mms/part` filtré par `mid = _id` du message MMS.

Cause résolue : PhoneLink lisait seulement `Telephony.Sms`, alors que KDE Connect
lit aussi les sources SMS/MMS combinées et les parts MMS texte.

Validation du 04/06 : PhoneLink Ubuntu affiche maintenant l'historique récent de
la conversation Cathy au-delà du 28/05, comme KDE Connect.

## 2. Ce que fait KDE Connect

KDE Connect a deux chemins complémentaires :

| Sous-système | Source Android | Usage |
|---|---|---|
| SMS | `Telephony.Sms`, `Telephony.Mms`, `content://mms-sms`, `content://mms/part` | Historique SMS/MMS et messages RCS-like visibles via le provider |
| Notifications | `getActiveNotifications()` + `MessagingStyle` | Fenêtre récente des notifications Google Messages, réponses via `RemoteInput` |

Points importants :

- KDE Connect ne lit pas directement une base privée Google Messages.
- Le plugin SMS lit les providers Android publics et les parts MMS texte.
- Le plugin Notifications relit `getActiveNotifications()` à chaque demande
  desktop et extrait tous les messages `MessagingStyle`.
- Le provider `content://mms-sms` peut exposer des lignes récentes dont le corps
  est nul ; il faut alors lire `content://mms/part`.

## 3. Implémentation PhoneLink V0.6

### Lecture SMS/MMS provider

`SmsRepository.kt` lit maintenant :

- SMS classiques depuis `content://sms` / `Telephony.Sms` ;
- MMS depuis `content://mms` / `Telephony.Mms` ;
- parts MMS texte depuis `content://mms/part`, avec filtre `mid = _id` ;
- parts `text/plain` ou plus généralement `text/*` ;
- colonne `text` si présente ;
- sinon `_data` via `ContentResolver.openInputStream()`.

Le résultat de `/v1/messages?conversation_id=<thread_id>` fusionne SMS + MMS,
puis trie les messages ancien -> récent pour l'affichage GTK.

### Chargement lazy

Pour éviter les timeouts GTK :

- `GET /v1/conversations` reste léger et rapide ;
- il ne lit pas les parts MMS ;
- il retourne seulement les résumés de fils : `id`, `contact_name`,
  `phone_number` si disponible, aperçu, `last_timestamp`, `unread` ;
- `GET /v1/messages?conversation_id=<thread_id>` est le seul endpoint qui lit
  le contenu complet du fil et les parts MMS.

Logs Android attendus :

- `/v1/conversations`: temps, nombre de conversations, nombre de SMS/MMS vus,
  `mmsParts=0` ;
- `/v1/messages`: temps, thread sélectionné, nombre de SMS/MMS retournés,
  nombre de parts MMS lues.

### Cache GTK

L'interface GTK charge les messages au clic sur une conversation, puis les garde
en cache par `conversation_id`.

- Retour sur une conversation déjà ouverte : réaffichage instantané depuis le
  cache.
- Bouton Rafraîchir : invalidation du cache du fil courant et rechargement via
  `/v1/messages`.
- Le backend Python garde aussi les métadonnées de la dernière liste de
  conversations pour éviter de rappeler `/v1/conversations` à chaque ouverture
  de fil.

### Notifications RCS

Le chemin notifications reste actif et utile pour diagnostiquer ce que Google
Messages expose :

- `GET /v1/rcs/messages` appelle
  `RcsNotificationListener.instance?.refreshFromActive()` à chaque requête ;
- le listener extrait les messages `MessagingStyle` et a un fallback sur
  `Notification.EXTRA_MESSAGES`, `EXTRA_BIG_TEXT`, `EXTRA_TEXT` ;
- `RcsMessageStore` conserve un cache accumulateur persistant dans
  `filesDir/rcs_store.json` ;
- `GET /v1/debug/notifications` retourne toujours un JSON exploitable, même si
  le listener n'est pas connecté.

## 4. Endpoints de diagnostic

Endpoints utiles, avec token requis sauf `/v1/health` :

```bash
curl http://127.0.0.1:8765/v1/health

curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8765/v1/debug/notifications

curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8765/v1/debug/sms-provider?address=+33786635741"

curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8765/v1/debug/mms-parts?mid=3696"

curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8765/v1/messages?conversation_id=4"
```

## 5. Statut V0.6 validé

- Lecture SMS classiques : OK.
- Lecture MMS/RCS-like via provider `mms-sms` / `mms` : OK.
- Lecture parts MMS `text/plain` / `text/*` : OK.
- Conversation Cathy au-delà du 28/05 : OK, validée visuellement.
- Affichage GTK : OK.
- `/v1/conversations` optimisé en lazy loading : OK.
- `/v1/messages` charge les détails au clic : OK.
- `/v1/debug/mms-parts` conservé pour vérifier les parts.
- `/v1/debug/notifications` conservé pour comparer avec `MessagingStyle`.

## 5.1 Validation terrain complémentaire du 08/06/2026

- Validation après redémarrage du téléphone et de l'application Android Companion.
- L'application GTK redémarre correctement.
- Les conversations SMS/MMS/RCS restent visibles après redémarrage.
- La conversation Cathy récente reste lisible.
- Les doublons principaux ne réapparaissent pas visuellement.
- L'envoi SMS classique fonctionne encore après les changements provider-first
  SMS/MMS/RCS.
- Le modèle provider-first reste validé.
- `RemoteInput` et l'envoi RCS restent hors scope.

## 5.2 V0.7 — hébergement du serveur (endpoints inchangés)

À partir de V0.7, `CompanionServer` est hébergé par un Foreground Service
Android (`CompanionForegroundService`) au lieu d'être lié à l'activité. Le
serveur survit donc à la fermeture/mise en arrière-plan de l'app. **Les
endpoints décrits ici, le contrat JSON et le modèle provider-first SMS/MMS/RCS
sont strictement inchangés** : seul l'hébergement du serveur change. `RemoteInput`
/ envoi RCS reste hors scope.

## 6. Limites restantes

- Pas d'envoi RCS en V0.6.0.
- `RemoteInput` n'est pas encore implémenté.
- Tous les messages RCS Google Messages ne sont pas garantis dans les providers
  publics ; PhoneLink affiche ce qu'Android expose via SMS/MMS providers et
  notifications.
- Les messages sortants RCS peuvent rester absents s'ils ne sont ni dans le
  provider SMS/MMS ni dans une notification active.
- Le cache local notifications est utile mais non canonique : il ne remplace pas
  l'historique interne Google Messages.

## 7. Sources

- KDE Connect Android : `SMSHelper.kt`, `SmsMmsUtils.kt`,
  `NotificationsPlugin.kt`, `NotificationReceiver.java`,
  `RepliableNotification.kt`.
- Android `Telephony.Sms`, `Telephony.Mms`, `Telephony.Mms.Part`.
- Validation terrain PhoneLink Ubuntu V0.6 sur la conversation Cathy, 04/06.
