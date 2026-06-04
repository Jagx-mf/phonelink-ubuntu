package com.phonelink.companion

import org.json.JSONArray
import org.json.JSONObject
import java.util.Collections

/**
 * Cache mémoire simple des messages RCS capturés via les notifications
 * (cf. [RcsNotificationListener] et docs/rcs-v0.6.md).
 *
 * V0.6.0 : **volatil** (perdu si le service est tué), **lecture seule**. Pas de
 * persistance ni de déduplication forte — on évite seulement les doublons
 * évidents (même horodatage + même corps dans un fil).
 *
 * Thread-safe : les notifications arrivent sur le thread du service tandis que
 * le serveur HTTP lit sur ses propres threads.
 */
object RcsMessageStore {

    /** Nombre max de messages conservés par conversation (fenêtre récente). */
    private const val MAX_PER_THREAD = 200

    private data class Msg(
        val body: String,
        val timestamp: Long,
        val outgoing: Boolean,
        val sender: String,
    )

    private class Thread(var contactName: String) {
        val messages = ArrayList<Msg>()
        val seen = HashSet<String>()  // clé de dedup "timestamp|body"
    }

    // conversationKey → Thread
    private val threads = Collections.synchronizedMap(LinkedHashMap<String, Thread>())

    /**
     * Ajoute un message capté. [conversationKey] identifie le fil (titre de
     * conversation ou expéditeur). Les doublons (même horodatage + corps) sont
     * ignorés.
     */
    fun add(
        conversationKey: String,
        contactName: String,
        body: String,
        timestamp: Long,
        outgoing: Boolean,
        sender: String,
    ) {
        if (body.isBlank()) return
        synchronized(threads) {
            val thread = threads.getOrPut(conversationKey) { Thread(contactName) }
            if (contactName.isNotBlank()) thread.contactName = contactName
            val dedupKey = "$timestamp|$body"
            if (!thread.seen.add(dedupKey)) return  // déjà vu
            thread.messages.add(Msg(body, timestamp, outgoing, sender))
            thread.messages.sortBy { it.timestamp }
            // Borne la fenêtre : on garde les plus récents.
            while (thread.messages.size > MAX_PER_THREAD) {
                val removed = thread.messages.removeAt(0)
                thread.seen.remove("${removed.timestamp}|${removed.body}")
            }
        }
    }

    /**
     * Instantané JSON, le plus récent en premier :
     * `{ "conversations": [ {id, contact_name, last_timestamp,
     * messages: [{body, timestamp, outgoing, sender}, …]} ] }`.
     * Messages d'un fil triés ancien → récent (pour l'affichage).
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

    /** Vide le cache (utile en test). */
    fun clear() {
        synchronized(threads) { threads.clear() }
    }
}
