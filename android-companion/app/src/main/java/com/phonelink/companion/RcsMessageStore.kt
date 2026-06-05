package com.phonelink.companion

import android.content.Context
import android.util.Log
import org.json.JSONObject
import org.json.JSONArray
import java.io.File
import java.text.Normalizer
import java.util.Collections
import java.util.Locale

/**
 * Cache des messages RCS captés via les notifications (cf. [RcsNotificationListener]
 * et docs/rcs-v0.6.md).
 *
 * V0.6.0 (révisé) :
 *  - **accumulateur** : on conserve les messages déjà vus même s'ils quittent les
 *    notifications actives (KDE Connect, lui, ne re-dérive que le live) ;
 *  - **persistance locale** (JSON dans `filesDir`) : survit au redémarrage du
 *    service/app — ce qui dépasse KDE Connect, qui ne persiste pas ;
 *  - **dédup** par fil (clé `timestamp|body`).
 *
 * Thread-safe : notifications (thread du service) + lectures HTTP (threads serveur).
 */
object RcsMessageStore {

    private const val TAG = "RcsStore"
    private const val MAX_PER_THREAD = 500
    private const val STORE_FILE = "rcs_store.json"

    private data class Msg(
        val body: String,
        val timestamp: Long,
        val outgoing: Boolean,
        val sender: String,
    )

    private class SnapshotThread(var id: String, var contactName: String) {
        val messages = ArrayList<Msg>()
        val seen = HashSet<String>()
    }

    private class Thread(var contactName: String) {
        val messages = ArrayList<Msg>()
        val seen = HashSet<String>()
    }

    private val threads = Collections.synchronizedMap(LinkedHashMap<String, Thread>())

    @Volatile
    private var appContext: Context? = null

    /** À appeler une fois (service onCreate) : mémorise le contexte et charge le disque. */
    fun attach(context: Context) {
        appContext = context.applicationContext
        loadFromDisk()
    }

    /** Ajoute un message (dédup) puis persiste. Renvoie true si nouveau. */
    fun add(
        conversationKey: String,
        contactName: String,
        body: String,
        timestamp: Long,
        outgoing: Boolean,
        sender: String,
    ): Boolean {
        val added = addInternal(conversationKey, contactName, body, timestamp, outgoing, sender)
        if (added) persist()
        return added
    }

    private fun addInternal(
        conversationKey: String,
        contactName: String,
        body: String,
        timestamp: Long,
        outgoing: Boolean,
        sender: String,
    ): Boolean {
        val canonicalKey = canonicalConversationKey(conversationKey)
        if (body.isBlank() || canonicalKey.isBlank()) return false
        synchronized(threads) {
            val thread = threads.getOrPut(canonicalKey) { Thread(contactName) }
            if (contactName.isNotBlank()) thread.contactName = contactName
            val dedupKey = "$timestamp|$body"
            if (!thread.seen.add(dedupKey)) return false
            thread.messages.add(Msg(body, timestamp, outgoing, sender))
            thread.messages.sortBy { it.timestamp }
            while (thread.messages.size > MAX_PER_THREAD) {
                val removed = thread.messages.removeAt(0)
                thread.seen.remove("${removed.timestamp}|${removed.body}")
            }
            return true
        }
    }

    /**
     * Instantané JSON, le plus récent en premier :
     * `{ "conversations": [ {id, contact_name, last_timestamp,
     * messages:[{body,timestamp,outgoing,sender}]} ] }`.
     */
    fun snapshot(): JSONObject {
        val conversations = JSONArray()
        synchronized(threads) {
            val ordered = deduplicatedThreads()
            for (thread in ordered) {
                conversations.put(thread.toJson())
            }
        }
        return JSONObject().put("conversations", conversations)
    }

    private fun rawSnapshot(): JSONObject {
        val conversations = JSONArray()
        synchronized(threads) {
            val ordered = threads.entries.sortedByDescending {
                it.value.messages.lastOrNull()?.timestamp ?: 0L
            }
            for ((key, thread) in ordered) {
                conversations.put(
                    SnapshotThread(key, thread.contactName).also {
                        mergeMessages(it, thread.messages)
                    }.toJson()
                )
            }
        }
        return JSONObject().put("conversations", conversations)
    }

    private fun deduplicatedThreads(): List<SnapshotThread> {
        val groups = ArrayList<SnapshotThread>()
        for ((key, thread) in threads) {
            val canonicalKey = canonicalConversationKey(key)
            val group = groups.firstOrNull {
                it.id == canonicalKey || isDuplicateThread(it, thread)
            } ?: SnapshotThread(canonicalKey, thread.contactName).also { groups.add(it) }

            group.id = preferredConversationKey(group.id, canonicalKey)
            if (group.contactName.isBlank() && thread.contactName.isNotBlank()) {
                group.contactName = thread.contactName
            }
            mergeMessages(group, thread.messages)
        }
        return groups.sortedByDescending { it.messages.lastOrNull()?.timestamp ?: 0L }
    }

    private fun isDuplicateThread(group: SnapshotThread, thread: Thread): Boolean {
        val leftContact = normaliseContact(group.contactName)
        val rightContact = normaliseContact(thread.contactName)
        if (leftContact.isBlank() || leftContact != rightContact) return false

        val leftLast = group.messages.lastOrNull() ?: return false
        val rightLast = thread.messages.lastOrNull() ?: return false
        if (leftLast.timestamp != rightLast.timestamp) return false

        return sameMessages(group.messages, thread.messages) ||
            sameBoundaryMessages(group.messages, thread.messages)
    }

    private fun sameMessages(left: List<Msg>, right: List<Msg>): Boolean {
        if (left.size != right.size) return false
        return left.map { messageSignature(it) }.toSet() ==
            right.map { messageSignature(it) }.toSet()
    }

    private fun sameBoundaryMessages(left: List<Msg>, right: List<Msg>): Boolean {
        val leftFirst = left.firstOrNull() ?: return false
        val rightFirst = right.firstOrNull() ?: return false
        val leftLast = left.lastOrNull() ?: return false
        val rightLast = right.lastOrNull() ?: return false
        return messageSignature(leftFirst) == messageSignature(rightFirst) &&
            messageSignature(leftLast) == messageSignature(rightLast)
    }

    private fun mergeMessages(group: SnapshotThread, messages: List<Msg>) {
        for (message in messages) {
            val signature = messageSignature(message)
            if (!group.seen.add(signature)) continue
            group.messages.add(message)
        }
        group.messages.sortBy { it.timestamp }
    }

    private fun SnapshotThread.toJson(): JSONObject {
        val msgs = JSONArray()
        for (m in messages) {
            msgs.put(
                JSONObject()
                    .put("body", m.body)
                    .put("timestamp", m.timestamp)
                    .put("outgoing", m.outgoing)
                    .put("sender", m.sender)
            )
        }
        return JSONObject()
            .put("id", id)
            .put("contact_name", contactName)
            .put("last_timestamp", messages.lastOrNull()?.timestamp ?: 0L)
            .put("messages", msgs)
    }

    private fun canonicalConversationKey(value: String): String {
        val raw = value.trim()
        if (raw.isBlank()) return ""
        val lower = raw.lowercase(Locale.ROOT)
        return when {
            lower.startsWith("shortcut:") ->
                prefixedKey("shortcut", raw.substringAfter(':'))
            lower.startsWith("title:") ->
                prefixedKey("title", raw.substringAfter(':'))
            lower.startsWith("sender:") ->
                prefixedKey("sender", raw.substringAfter(':'))
            lower.startsWith("notification:") ->
                raw.substringAfter(':').trim().let {
                    if (it.isBlank()) "" else "notification:$it"
                }
            looksLikeShortcut(raw) ->
                "shortcut:${raw.filter { it.isDigit() }}"
            else ->
                prefixedKey("title", raw)
        }
    }

    private fun prefixedKey(prefix: String, value: String): String {
        val part = normaliseKeyPart(value)
        return if (part.isBlank()) "" else "$prefix:$part"
    }

    private fun preferredConversationKey(current: String, candidate: String): String {
        if (current.isBlank()) return candidate
        if (current.startsWith("shortcut:")) return current
        if (candidate.startsWith("shortcut:")) return candidate
        if (current.startsWith("title:")) return current
        if (candidate.startsWith("title:")) return candidate
        return current
    }

    private fun looksLikeShortcut(value: String): Boolean {
        val digits = value.filter { it.isDigit() }
        if (digits.isBlank()) return false
        return value.all {
            it.isDigit() || it.isWhitespace() ||
                it == '+' || it == '-' || it == '(' || it == ')' || it == '.'
        }
    }

    private fun normaliseContact(value: String): String = normaliseKeyPart(value)

    private fun normaliseKeyPart(value: String): String {
        val decomposed = Normalizer.normalize(value, Normalizer.Form.NFKD)
        return decomposed
            .replace(Regex("\\p{Mn}+"), "")
            .lowercase(Locale.ROOT)
            .replace(Regex("[^0-9a-z]+"), " ")
            .trim()
            .replace(Regex("\\s+"), " ")
    }

    private fun messageSignature(message: Msg): String =
        "${message.timestamp}|${message.outgoing}|${message.body}"

    /** Nombre total de messages en cache (pour les logs/diagnostic). */
    fun totalMessages(): Int = synchronized(threads) { threads.values.sumOf { it.messages.size } }

    // ---- persistance ------------------------------------------------------

    private fun storeFile(): File? {
        val ctx = appContext ?: return null
        return File(ctx.filesDir, STORE_FILE)
    }

    private fun persist() {
        val file = storeFile() ?: return
        try {
            file.writeText(rawSnapshot().toString())
        } catch (e: Exception) {
            Log.w(TAG, "persist échoué: ${e.message}")
        }
    }

    private fun loadFromDisk() {
        val file = storeFile() ?: return
        if (!file.exists()) return
        try {
            val root = JSONObject(file.readText())
            val convos = root.optJSONArray("conversations") ?: return
            for (i in 0 until convos.length()) {
                val c = convos.optJSONObject(i) ?: continue
                val key = c.optString("id")
                val contact = c.optString("contact_name")
                val msgs = c.optJSONArray("messages") ?: continue
                for (j in 0 until msgs.length()) {
                    val m = msgs.optJSONObject(j) ?: continue
                    addInternal(
                        conversationKey = key,
                        contactName = contact,
                        body = m.optString("body"),
                        timestamp = m.optLong("timestamp"),
                        outgoing = m.optBoolean("outgoing"),
                        sender = m.optString("sender"),
                    )
                }
            }
            Log.i(TAG, "cache RCS chargé: ${totalMessages()} messages")
        } catch (e: Exception) {
            Log.w(TAG, "load échoué: ${e.message}")
        }
    }

    fun clear() {
        synchronized(threads) { threads.clear() }
        persist()
    }
}
