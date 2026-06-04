package com.phonelink.companion

import android.content.Context
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

/**
 * Capture les messages RCS via les notifications de Google Messages
 * (cf. docs/rcs-v0.6.md). API officielle « accès aux notifications » : pas de
 * root, pas de lecture de base privée.
 *
 * V0.6.0 : **lecture seule**. On extrait le contenu MessagingStyle des
 * notifications de `com.google.android.apps.messaging` et on le pousse dans
 * [RcsMessageStore]. Aucune réponse (`RemoteInput`) n'est envoyée ici — repoussé
 * à la V0.6.1.
 */
class RcsNotificationListener : NotificationListenerService() {

    override fun onListenerConnected() {
        // Au branchement, on amorce le cache avec les notifications déjà
        // affichées (sinon il faut attendre un nouveau message pour voir
        // quelque chose).
        try {
            activeNotifications?.forEach { handle(it) }
        } catch (e: Exception) {
            // getActiveNotifications peut échouer si non encore connecté.
        }
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        handle(sbn)
    }

    private fun handle(sbn: StatusBarNotification) {
        if (sbn.packageName != TARGET_PACKAGE) return
        try {
            capture(sbn)
        } catch (e: Exception) {
            // Une notification malformée ne doit jamais faire planter le service.
        }
    }

    private fun capture(sbn: StatusBarNotification) {
        val notification = sbn.notification ?: return
        val extras = notification.extras
        val title = extras?.getCharSequence(NotificationCompat.EXTRA_TITLE)?.toString().orEmpty()

        val style =
            NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(notification)

        if (style != null && style.messages.isNotEmpty()) {
            val convoTitle = style.conversationTitle?.toString()
            for (message in style.messages) {
                val sender = message.person?.name?.toString().orEmpty()
                // Dans MessagingStyle, un message sans Person provient de
                // l'utilisateur courant (donc sortant).
                val outgoing = message.person == null
                val key = firstNonBlank(convoTitle, sender, title, sbn.key)
                val contact = firstNonBlank(convoTitle, sender, title)
                RcsMessageStore.add(
                    conversationKey = key,
                    contactName = contact,
                    body = message.text?.toString().orEmpty(),
                    timestamp = message.timestamp,
                    outgoing = outgoing,
                    sender = sender,
                )
            }
            return
        }

        // Fallback : notification non-MessagingStyle (ex. ancienne mise en forme).
        val text = (extras?.getCharSequence(NotificationCompat.EXTRA_BIG_TEXT)
            ?: extras?.getCharSequence(NotificationCompat.EXTRA_TEXT))?.toString().orEmpty()
        if (text.isNotBlank() && title.isNotBlank()) {
            RcsMessageStore.add(
                conversationKey = title,
                contactName = title,
                body = text,
                timestamp = sbn.postTime,
                outgoing = false,
                sender = title,
            )
        }
    }

    private fun firstNonBlank(vararg values: String?): String =
        values.firstOrNull { !it.isNullOrBlank() } ?: ""

    companion object {
        const val TARGET_PACKAGE = "com.google.android.apps.messaging"

        /** True si l'utilisateur a accordé l'accès aux notifications à cette app. */
        fun hasAccess(context: Context): Boolean =
            NotificationManagerCompat.getEnabledListenerPackages(context)
                .contains(context.packageName)
    }
}
