package com.phonelink.companion

import android.app.Notification
import android.content.Context
import android.os.Build
import android.os.Bundle
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import org.json.JSONArray
import org.json.JSONObject

/**
 * Capture des messages RCS via les notifications de Google Messages
 * (cf. docs/rcs-v0.6.md). API officielle « accès aux notifications » : pas de
 * root, pas de lecture de base privée.
 *
 * V0.6.0 (révisé pour parité KDE Connect) :
 *  - extrait **tous** les messages de MessagingStyle (+ fallback `EXTRA_MESSAGES`) ;
 *  - **relit les notifications actives en direct** sur demande
 *    ([refreshFromActive]) — c'est ainsi que KDE Connect montre les messages
 *    « déjà présents » (`getActiveNotifications()` à chaque requête) ;
 *  - logs détaillés + dump debug ([debugDump]) ;
 *  - alimente [RcsMessageStore] (accumulateur + persistance).
 *
 * Lecture seule : aucune réponse (`RemoteInput`) — repoussé à la V0.6.1.
 */
class RcsNotificationListener : NotificationListenerService() {

    override fun onCreate() {
        super.onCreate()
        RcsMessageStore.attach(applicationContext)
    }

    override fun onListenerConnected() {
        instance = this
        val count = try {
            activeNotifications?.size ?: 0
        } catch (e: Exception) {
            -1
        }
        Log.i(TAG, "onListenerConnected — notifications actives: $count")
        refreshFromActive()
    }

    override fun onListenerDisconnected() {
        Log.i(TAG, "onListenerDisconnected")
        instance = null
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (sbn.packageName != TARGET_PACKAGE) return
        val added = handle(sbn, log = true)
        Log.d(TAG, "onNotificationPosted key=${sbn.key} → +$added message(s)")
    }

    /**
     * Relit les notifications actives de Google Messages et les pousse dans le
     * store. Renvoie le nombre de notifications traitées (ou -1 si indisponible).
     */
    fun refreshFromActive(): Int {
        val actives = try {
            activeNotifications
        } catch (e: Exception) {
            Log.w(TAG, "getActiveNotifications indisponible: ${e.message}")
            return -1
        } ?: return 0
        var processed = 0
        var added = 0
        for (sbn in actives) {
            if (sbn.packageName != TARGET_PACKAGE) continue
            processed++
            added += handle(sbn, log = false)
        }
        Log.i(TAG, "refreshFromActive — $processed notif Messages, +$added message(s), total cache=${RcsMessageStore.totalMessages()}")
        return processed
    }

    // ---- extraction -------------------------------------------------------

    /** Traite une notification : ajoute ses messages au store. Renvoie le nombre ajouté. */
    private fun handle(sbn: StatusBarNotification, log: Boolean): Int {
        return try {
            capture(sbn, log)
        } catch (e: Exception) {
            Log.w(TAG, "capture échouée key=${sbn.key}: ${e.message}")
            0
        }
    }

    private fun capture(sbn: StatusBarNotification, log: Boolean): Int {
        val n = sbn.notification ?: return 0
        val extras = n.extras
        val title = extras?.getCharSequence(NotificationCompat.EXTRA_TITLE)?.toString().orEmpty()
        val text = extras?.getCharSequence(NotificationCompat.EXTRA_TEXT)?.toString().orEmpty()
        val bigText = extras?.getCharSequence(NotificationCompat.EXTRA_BIG_TEXT)?.toString().orEmpty()
        val style = NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(n)
        val convoTitle = style?.conversationTitle?.toString()
        val isGroup = style?.isGroupConversation ?: false
        val shortcut = shortcutIdOf(n)
        val category = n.category ?: ""

        var added = 0
        var extractedCount = 0
        var lastSender = ""

        if (style != null && style.messages.isNotEmpty()) {
            for (message in style.messages) {
                extractedCount++
                val sender = message.person?.name?.toString().orEmpty()
                if (sender.isNotBlank()) lastSender = sender
                val outgoing = message.person == null
                val key = firstNonBlank(shortcut, convoTitle, sender, title, sbn.key)
                val contact = firstNonBlank(convoTitle, sender, title)
                if (RcsMessageStore.add(key, contact, message.text?.toString().orEmpty(),
                        message.timestamp, outgoing, sender)) added++
            }
        } else {
            // Fallback 1 : tableau brut EXTRA_MESSAGES (si l'extraction a échoué).
            val rawAdded = captureFromExtraMessages(sbn, extras, shortcut, convoTitle, title)
            extractedCount = rawAdded.second
            added += rawAdded.first
            // Fallback 2 : notification texte simple.
            if (extractedCount == 0 && title.isNotBlank()) {
                val body = bigText.ifBlank { text }
                if (body.isNotBlank() &&
                    RcsMessageStore.add(firstNonBlank(shortcut, title), title, body,
                        sbn.postTime, false, title)) {
                    added++; extractedCount = 1
                }
            }
        }

        if (log) {
            Log.d(TAG, buildString {
                append("notif key=${sbn.key} pkg=${sbn.packageName}")
                append(" title=${title.q()} text=${text.q()} bigText=${bigText.take(40).q()}")
                append(" convoTitle=${(convoTitle ?: "").q()} shortcut=${shortcut.q()}")
                append(" category=$category isGroup=$isGroup")
                append(" msgStyle=$extractedCount lastSender=${lastSender.q()} postTime=${sbn.postTime}")
            })
        }
        return added
    }

    /**
     * Parse manuellement `Notification.EXTRA_MESSAGES` (tableau de Bundle :
     * "text"/"time"/"sender"). Utile si MessagingStyle n'a pas pu être extrait.
     * Renvoie (ajoutés, vus).
     */
    private fun captureFromExtraMessages(
        sbn: StatusBarNotification,
        extras: Bundle?,
        shortcut: String,
        convoTitle: String?,
        title: String,
    ): Pair<Int, Int> {
        val raw = extraMessageBundles(extras)
        if (raw.isEmpty()) return 0 to 0
        var added = 0
        var seen = 0
        for (b in raw) {
            val body = b.getCharSequence("text")?.toString().orEmpty()
            if (body.isBlank()) continue
            seen++
            val time = b.getLong("time", sbn.postTime)
            val sender = b.getCharSequence("sender")?.toString().orEmpty()
            val outgoing = sender.isBlank()
            val key = firstNonBlank(shortcut, convoTitle, sender, title, sbn.key)
            val contact = firstNonBlank(convoTitle, sender, title)
            if (RcsMessageStore.add(key, contact, body, time, outgoing, sender)) added++
        }
        return added to seen
    }

    // ---- debug ------------------------------------------------------------

    /** Dump JSON des notifications Google Messages actives (champs extraits). */
    fun debugDump(): JSONArray {
        val arr = JSONArray()
        val actives = try {
            activeNotifications
        } catch (e: Exception) {
            return arr.put(JSONObject().put("error", e.message ?: "unavailable"))
        } ?: return arr
        for (sbn in actives) {
            if (sbn.packageName != TARGET_PACKAGE) continue
            val n = sbn.notification ?: continue
            val extras = n.extras
            val style = NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(n)
            val msgs = JSONArray()
            style?.messages?.forEach { m ->
                msgs.put(
                    JSONObject()
                        .put("sender", m.person?.name?.toString() ?: "")
                        .put("timestamp", m.timestamp)
                        .put("text", m.text?.toString() ?: "")
                        .put("outgoing", m.person == null)
                )
            }
            val rawMessages = extraMessageBundles(extras)
            val rawMsgs = rawMessages.size
            val extraMsgs = JSONArray()
            rawMessages.forEach { b ->
                extraMsgs.put(
                    JSONObject()
                        .put("sender", b.getCharSequence("sender")?.toString() ?: "")
                        .put("timestamp", b.getLong("time", sbn.postTime))
                        .put("text", b.getCharSequence("text")?.toString() ?: "")
                )
            }
            arr.put(
                JSONObject()
                    .put("key", sbn.key)
                    .put("package", sbn.packageName)
                    .put("postTime", sbn.postTime)
                    .put("title", extras?.getCharSequence(NotificationCompat.EXTRA_TITLE)?.toString() ?: "")
                    .put("text", extras?.getCharSequence(NotificationCompat.EXTRA_TEXT)?.toString() ?: "")
                    .put("bigText", extras?.getCharSequence(NotificationCompat.EXTRA_BIG_TEXT)?.toString() ?: "")
                    .put("conversationTitle", style?.conversationTitle?.toString() ?: "")
                    .put("isGroupConversation", style?.isGroupConversation ?: false)
                    .put("shortcutId", shortcutIdOf(n))
                    .put("category", n.category ?: "")
                    .put("messagingStyleCount", style?.messages?.size ?: 0)
                    .put("extraMessagesCount", rawMsgs)
                    .put("messages", msgs)
                    .put("extraMessages", extraMsgs)
            )
        }
        return arr
    }

    // ---- helpers ----------------------------------------------------------

    private fun shortcutIdOf(n: Notification): String =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) n.shortcutId ?: "" else ""

    private fun extraMessageBundles(extras: Bundle?): List<Bundle> {
        extras ?: return emptyList()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            extras.getParcelableArray(Notification.EXTRA_MESSAGES, Bundle::class.java)
                ?.toList()
                .orEmpty()
        } else {
            @Suppress("DEPRECATION")
            extras.getParcelableArray(Notification.EXTRA_MESSAGES)
                ?.mapNotNull { it as? Bundle }
                .orEmpty()
        }
    }

    private fun firstNonBlank(vararg values: String?): String =
        values.firstOrNull { !it.isNullOrBlank() } ?: ""

    private fun String.q(): String = "\"${this.take(60)}\""

    companion object {
        const val TARGET_PACKAGE = "com.google.android.apps.messaging"
        private const val TAG = "RcsListener"

        /** Instance du service connecté (pour relecture live depuis le serveur HTTP). */
        @Volatile
        var instance: RcsNotificationListener? = null
            private set

        fun hasAccess(context: Context): Boolean =
            NotificationManagerCompat.getEnabledListenerPackages(context)
                .contains(context.packageName)
    }
}
