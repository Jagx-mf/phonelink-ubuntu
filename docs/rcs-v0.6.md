# RCS via notifications Android — V0.6

PhoneLink Ubuntu lit les SMS/MMS via le provider `Telephony` (cf.
[`android-backend-v0.5.md`](android-backend-v0.5.md)). **Les messages RCS** (chat
« Google Messages ») **n'y figurent pas**. La V0.6 ajoute leur capture via l'API
officielle d'**accès aux notifications**, comme le fait KDE Connect.

> V0.6.0 = **lecture seule + affichage fusionné** dans GTK. L'envoi RCS via
> `RemoteInput` est repoussé à **V0.6.1**.

---

## 1. Pourquoi `Telephony.Sms` ne voit pas le RCS

- Le RCS (Universal Profile / Jibe) arrive **par IP** via *Carrier Services* +
  *Google Messages*, stocké dans le **stockage privé de Google Messages**, pas
  dans `content://sms` ni `content://mms`.
- Il **n'existe aucun content provider RCS public** pour les apps tierces.
  L'« Android RCS API » est réservée à Google Messages + une **allowlist** (apps
  Samsung). Source : doc Google Messages + XDA.
- Donc une requête `ContentResolver` sur `Telephony.Sms` ne peut **pas** remonter
  le RCS — par conception, pas par bug. Notre `SmsRepository.kt` est correct mais
  limité au périmètre SMS/MMS.

## 2. Comment KDE Connect obtient ces messages (code vérifié)

KDE Connect (dépôt `KDE/kdeconnect-android`, migré en Kotlin) a **deux
sous-systèmes indépendants** :

| Sous-système | Fichiers | Source |
|---|---|---|
| SMS/Conversations | `plugins/sms/SMSPlugin.kt`, `SmsMmsUtils.kt`, `SMSHelper` | **Telephony uniquement** (`Telephony.Threads`, `content://mms-sms`, parties MMS). Aucune trace de RCS. |
| Notifications | `plugins/notifications/NotificationReceiver.java` (`extends NotificationListenerService`), `NotificationsPlugin.kt`, `RepliableNotification.kt` | **Les notifications** postées par Google Messages. |

Le RCS visible dans KDE Connect vient du **module Notifications**, pas du module
SMS. Mécanisme exact (vérifié) :

1. `NotificationReceiver extends NotificationListenerService` ; reçoit
   `onNotificationPosted()`. Permission spéciale « accès aux notifications »
   (réglage système `enabled_notification_listeners`), pas une permission runtime.
   À chaque demande côté desktop, le plugin Notifications relit aussi les
   notifications actives via `getActiveNotifications()` ; cela permet de voir
   les notifications déjà présentes, pas seulement les nouvelles notifications.
2. Extraction du contenu via
   `NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification()`
   (liste complète des messages exposés par la notification : expéditeur +
   texte + horodatage), avec repli sur
   `EXTRA_BIG_TEXT` / `EXTRA_TEXT` / `EXTRA_TITLE`, puis `tickerText`.
3. Réponse via `RemoteInput` : `RepliableNotification` stocke
   `pendingIntent` + `remoteInputs: List<RemoteInput>` + `packageName` ;
   `RemoteInput.addResultsToIntent(...)` puis déclenchement du `PendingIntent`.

**KDE Connect ne distingue jamais SMS et RCS** : il relaie le contenu de la
notification et l'action de réponse ; c'est Google Messages qui renvoie en RCS.

## 3. Approche V0.6 pour PhoneLink (et contraintes respectées)

`NotificationListenerService` est une API **officielle**, accordée explicitement
par l'utilisateur. Donc : **pas de root**, **pas de lecture de base privée
Google**, **aucun contournement de protection**. Distribution sideload assumée
(l'accès notifications est restreint sur le Play Store).

```
Google Messages RCS → notification Android → RcsNotificationListener
→ RcsMessageStore (mémoire + JSON local) → GET /v1/rcs/messages
→ android_bridge (Python)
→ AndroidCompanionBackend (fusion SMS + RCS) → GTK (affichage unifié, badge RCS)
```

Depuis le correctif V0.6.0 RC :

- `GET /v1/rcs/messages` appelle d'abord
  `RcsNotificationListener.instance?.refreshFromActive()`, donc PhoneLink relit
  les notifications Google Messages actives à chaque appel API, comme KDE
  Connect.
- `RcsNotificationListener` extrait tous les messages `MessagingStyle` exposés
  par la notification, avec un fallback sur `Notification.EXTRA_MESSAGES`, puis
  sur `EXTRA_BIG_TEXT` / `EXTRA_TEXT` pour les notifications non structurées.
- `RcsMessageStore` est un cache accumulateur persistant : il déduplique par fil
  (`timestamp|body`), garde au plus 500 messages par conversation et écrit un
  JSON local dans `filesDir/rcs_store.json`. Les messages déjà vus restent donc
  visibles même si la notification Android disparaît.
- `GET /v1/debug/notifications` (token requis) expose un dump JSON des
  notifications actives Google Messages : clé système, titre, texte, shortcut,
  catégorie, nombre de messages `MessagingStyle`, nombre de messages
  `EXTRA_MESSAGES` et contenu extrait. Si le listener n'est pas connecté,
  l'endpoint renvoie `status=listener_not_connected`.

## 4. Limites connues (V0.6.0)

- **Seuls les messages exposés par les notifications sont visibles** : entrants
  ayant généré une notification et petite fenêtre récente portée par
  `MessagingStyle`. **Pas d'historique RCS complet**, pas de backfill depuis une
  base privée Google Messages.
- **RCS sortants** (envoyés depuis le téléphone) ne sont pas notifiés → absents.
- MessagingStyle ne fournit qu'une **petite fenêtre récente** de messages.
- **Pas d'ID fiable** → déduplication heuristique (horodatage + texte).
- **Appariement conversation** heuristique (titre/expéditeur, pas de `thread_id`).
  En V0.6.0 les fils RCS sont une **liste à part** (id préfixé `rcs:`), affichés
  avec un badge, pas fusionnés au thread SMS du même contact.
- **Cache local non canonique** : il améliore l'affichage PhoneLink, mais ne
  remplace pas l'historique réel Google Messages et peut contenir des doublons
  si Google émet des notifications avec horodatages différents pour le même
  texte.
- **Pas d'envoi** en V0.6.0 (RemoteInput → V0.6.1).

## 5. Sources

- Dépôt `KDE/kdeconnect-android` — `plugins/notifications/NotificationsPlugin.kt`,
  `NotificationReceiver.java`, `RepliableNotification.kt`, `plugins/sms/SMSPlugin.kt`,
  `SmsMmsUtils.kt`.
- Google Messages : « hidden RCS API » réservée à une allowlist (XDA), FAQ RCS Google.
