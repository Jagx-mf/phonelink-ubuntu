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
import java.util.Locale

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

    private data class CaptureResult(
        val added: Int = 0,
        val extracted: Int = 0,
        val conversationKey: String = "",
        val contactName: String = "",
        val timestamps: List<Long> = emptyList(),
        val source: String = "",
    )

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
        val result = handle(sbn, log = true)
        Log.d(TAG, "onNotificationPosted key=${sbn.key} → +${result.added} message(s)")
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
        var extracted = 0
        val details = ArrayList<CaptureResult>()
        for (sbn in actives) {
            if (sbn.packageName != TARGET_PACKAGE) continue
            processed++
            val result = handle(sbn, log = false)
            added += result.added
            extracted += result.extracted
            details.add(result)
        }
        Log.i(
            TAG,
            "refreshFromActive — $processed notif Messages, " +
                "$extracted message(s) extraits, +$added message(s), " +
                "total cache=${RcsMessageStore.totalMessages()}",
        )
        details.forEach { result ->
            Log.i(
                TAG,
                "refreshFromActive detail — source=${result.source} " +
                    "conversation=${result.conversationKey.q()} " +
                    "contact=${result.contactName.q()} extracted=${result.extracted} " +
                    "added=${result.added} timestamps=${result.timestamps}",
            )
        }
        return processed
    }

    // ---- extraction -------------------------------------------------------

    /** Traite une notification : ajoute ses messages au store et renvoie le diagnostic. */
    private fun handle(sbn: StatusBarNotification, log: Boolean): CaptureResult {
        return try {
            capture(sbn, log)
        } catch (e: Exception) {
            Log.w(TAG, "capture échouée key=${sbn.key}: ${e.message}")
            CaptureResult()
        }
    }

    private fun capture(sbn: StatusBarNotification, log: Boolean): CaptureResult {
        val n = sbn.notification ?: return CaptureResult()
        val extras = n.extras
        val title = extras?.getCharSequence(NotificationCompat.EXTRA_TITLE)?.toString().orEmpty()
        val text = extras?.getCharSequence(NotificationCompat.EXTRA_TEXT)?.toString().orEmpty()
        val bigText = extras?.getCharSequence(NotificationCompat.EXTRA_BIG_TEXT)?.toString().orEmpty()
        val style = messagingStyleOf(n)
        val convoTitle = style?.conversationTitle?.toString()
        val isGroup = style?.isGroupConversation ?: false
        val shortcut = shortcutIdOf(n)
        val category = n.category ?: ""

        var added = 0
        var extractedCount = 0
        var lastSender = ""
        var conversationKey = stableConversationKey(shortcut, convoTitle, title, "", sbn.key)
        var contactName = firstNonBlank(convoTitle, title)
        var source = "none"
        val timestamps = ArrayList<Long>()

        if (style != null && style.messages.isNotEmpty()) {
            source = "MessagingStyle"
            for (message in style.messages) {
                extractedCount++
                val sender = message.person?.name?.toString().orEmpty()
                if (sender.isNotBlank()) lastSender = sender
                val outgoing = message.person == null
                val key = stableConversationKey(shortcut, convoTitle, title, sender, sbn.key)
                val contact = firstNonBlank(convoTitle, sender, title)
                conversationKey = key
                contactName = contact
                timestamps.add(message.timestamp)
                if (RcsMessageStore.add(key, contact, message.text?.toString().orEmpty(),
                        message.timestamp, outgoing, sender)) added++
            }
        } else {
            // Fallback 1 : tableau brut EXTRA_MESSAGES (si l'extraction a échoué).
            val rawAdded = captureFromExtraMessages(sbn, extras, shortcut, convoTitle, title)
            extractedCount = rawAdded.seen
            added += rawAdded.added
            if (rawAdded.seen > 0) {
                source = "EXTRA_MESSAGES"
                conversationKey = rawAdded.conversationKey
                contactName = rawAdded.contactName
                timestamps.addAll(rawAdded.timestamps)
            }
            // Fallback 2 : notification texte simple.
            if (extractedCount == 0 && title.isNotBlank()) {
                val body = bigText.ifBlank { text }
                if (body.isNotBlank() &&
                    RcsMessageStore.add(
                        stableConversationKey(shortcut, null, title, "", sbn.key),
                        title,
                        body,
                        sbn.postTime, false, title)) {
                    source = "text"
                    conversationKey = stableConversationKey(shortcut, null, title, "", sbn.key)
                    contactName = title
                    timestamps.add(sbn.postTime)
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
        return CaptureResult(
            added = added,
            extracted = extractedCount,
            conversationKey = conversationKey,
            contactName = contactName,
            timestamps = timestamps,
            source = source,
        )
    }

    /**
     * Parse manuellement `Notification.EXTRA_MESSAGES` (tableau de Bundle :
     * "text"/"time"/"sender"). Utile si MessagingStyle n'a pas pu être extrait.
     * Renvoie les messages ajoutés/vus et leurs métadonnées.
     */
    private data class ExtraCaptureResult(
        val added: Int,
        val seen: Int,
        val conversationKey: String,
        val contactName: String,
        val timestamps: List<Long>,
    )

    private fun captureFromExtraMessages(
        sbn: StatusBarNotification,
        extras: Bundle?,
        shortcut: String,
        convoTitle: String?,
        title: String,
    ): ExtraCaptureResult {
        val raw = extraMessageBundles(extras)
        if (raw.isEmpty()) {
            return ExtraCaptureResult(
                added = 0,
                seen = 0,
                conversationKey = stableConversationKey(shortcut, convoTitle, title, "", sbn.key),
                contactName = firstNonBlank(convoTitle, title),
                timestamps = emptyList(),
            )
        }
        var added = 0
        var seen = 0
        var conversationKey = stableConversationKey(shortcut, convoTitle, title, "", sbn.key)
        var contactName = firstNonBlank(convoTitle, title)
        val timestamps = ArrayList<Long>()
        for (b in raw) {
            val body = b.getCharSequence("text")?.toString().orEmpty()
            if (body.isBlank()) continue
            seen++
            val time = b.getLong("time", sbn.postTime)
            val sender = b.getCharSequence("sender")?.toString().orEmpty()
            val outgoing = sender.isBlank()
            val key = stableConversationKey(shortcut, convoTitle, title, sender, sbn.key)
            val contact = firstNonBlank(convoTitle, sender, title)
            conversationKey = key
            contactName = contact
            timestamps.add(time)
            if (RcsMessageStore.add(key, contact, body, time, outgoing, sender)) added++
        }
        return ExtraCaptureResult(added, seen, conversationKey, contactName, timestamps)
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
            try {
                arr.put(debugObjectFor(sbn))
            } catch (e: Exception) {
                arr.put(
                    JSONObject()
                        .put("key", sbn.key)
                        .put("package", sbn.packageName)
                        .put("error", e.javaClass.simpleName)
                        .put("message", e.message ?: "")
                )
            }
        }
        return arr
    }

    // ---- helpers ----------------------------------------------------------

    private fun debugObjectFor(sbn: StatusBarNotification): JSONObject {
        val n = sbn.notification
        if (n == null) {
            return JSONObject()
                .put("key", sbn.key)
                .put("package", sbn.packageName)
                .put("error", "missing_notification")
        }
        val extras = n.extras
        val style = messagingStyleOf(n)
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
        val extraMsgs = JSONArray()
        rawMessages.forEach { b ->
            extraMsgs.put(
                JSONObject()
                    .put("sender", b.getCharSequence("sender")?.toString() ?: "")
                    .put("timestamp", b.getLong("time", sbn.postTime))
                    .put("text", b.getCharSequence("text")?.toString() ?: "")
            )
        }
        return JSONObject()
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
            .put("extraMessagesCount", rawMessages.size)
            .put("messages", msgs)
            .put("extraMessages", extraMsgs)
    }

    private fun messagingStyleOf(n: Notification): NotificationCompat.MessagingStyle? =
        try {
            NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(n)
        } catch (e: Exception) {
            Log.w(TAG, "MessagingStyle extraction échouée: ${e.message}")
            null
        }

    private fun shortcutIdOf(n: Notification): String =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) n.shortcutId ?: "" else ""

    private fun extraMessageBundles(extras: Bundle?): List<Bundle> {
        extras ?: return emptyList()
        @Suppress("DEPRECATION")
        return extras.getParcelableArray(Notification.EXTRA_MESSAGES)
            ?.mapNotNull { it as? Bundle }
            .orEmpty()
    }

    private fun firstNonBlank(vararg values: String?): String =
        values.firstOrNull { !it.isNullOrBlank() } ?: ""

    private fun stableConversationKey(
        shortcut: String,
        convoTitle: String?,
        title: String,
        sender: String,
        fallback: String,
    ): String {
        val shortcutValue = shortcut.trim().let {
            if (it.lowercase(Locale.ROOT).startsWith("shortcut:")) it.substringAfter(':') else it
        }
        val shortcutKey = normalisedKeyPart(shortcutValue)
        if (shortcutKey.isNotBlank()) return "shortcut:$shortcutKey"
        val titleKey = normalisedKeyPart(firstNonBlank(convoTitle, title))
        if (titleKey.isNotBlank()) return "title:$titleKey"
        val senderKey = normalisedKeyPart(sender)
        if (senderKey.isNotBlank()) return "sender:$senderKey"
        return "notification:${fallback.trim()}"
    }

    private fun normalisedKeyPart(value: String): String =
        value.trim()
            .lowercase(Locale.ROOT)
            .replace(Regex("\\s+"), " ")

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
