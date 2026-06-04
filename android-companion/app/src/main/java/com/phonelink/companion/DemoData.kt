package com.phonelink.companion

import org.json.JSONArray
import org.json.JSONObject

/**
 * Données fictives renvoyées par `/v1/conversations` et `/v1/messages` lorsque
 * les permissions SMS ne sont pas accordées (fallback de démo).
 *
 * Le format JSON est **strictement aligné sur le contrat** (cf.
 * docs/android-backend-v0.4.md §2) et sur ce que renvoie [SmsRepository] :
 * `contact_name` (pas `title`), `last_timestamp` (pas `timestamp`), `unread`
 * entier. Ainsi le client Ubuntu se comporte de façon identique en démo et en
 * réel.
 */
object DemoData {

    private const val DEMO_TS = 1_710_000_000_000L

    fun conversations(): JSONObject {
        val conversation = JSONObject()
            .put("id", "demo-1")
            .put("contact_name", "Maman")
            .put("phone_number", "+33000000000")
            .put("last_message", "Message de test")
            .put("last_timestamp", DEMO_TS)
            .put("unread", 0)

        return JSONObject().put("conversations", JSONArray().put(conversation))
    }

    fun messages(conversationId: String): JSONObject {
        val message = JSONObject()
            .put("body", "Salut depuis Android Companion")
            .put("timestamp", DEMO_TS)
            .put("outgoing", false)

        return JSONObject()
            .put("conversation_id", conversationId)
            .put("messages", JSONArray().put(message))
    }
}
