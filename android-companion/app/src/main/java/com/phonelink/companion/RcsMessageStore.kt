package com.phonelink.companion

import android.content.Context
import android.util.Log
import org.json.JSONObject
import org.json.JSONArray
import java.io.File
import java.util.Collections

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
        if (body.isBlank() || conversationKey.isBlank()) return false
        synchronized(threads) {
            val thread = threads.getOrPut(conversationKey) { Thread(contactName) }
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
            val ordered = threads.entries.sortedByDescending {
                it.value.messages.lastOrNull()?.timestamp ?: 0L
            }
            for ((key, thread) in ordered) {
                val msgs = JSONArray()
                for (m in thread.messages) {
                    msgs.put(
                        JSONObject()
                            .put("body", m.body)
                            .put("timestamp", m.timestamp)
                            .put("outgoing", m.outgoing)
                            .put("sender", m.sender)
                    )
                }
                conversations.put(
                    JSONObject()
                        .put("id", key)
                        .put("contact_name", thread.contactName)
                        .put("last_timestamp", thread.messages.lastOrNull()?.timestamp ?: 0L)
                        .put("messages", msgs)
                )
            }
        }
        return JSONObject().put("conversations", conversations)
    }

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
            file.writeText(snapshot().toString())
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
