package com.phonelink.companion

import org.json.JSONArray
import org.json.JSONObject

/**
 * Données fictives renvoyées par `/v1/conversations` et `/v1/messages`.
 *
 * Aucun accès SMS réel en V0.4.1 — ces objets servent uniquement à valider le
 * transport et le contrat JSON avec le client Ubuntu.
 */
object DemoData {

    private const val DEMO_TS = 1_710_000_000_000L

    fun conversations(): JSONObject {
        val conversation = JSONObject()
            .put("id", "demo-1")
            .put("title", "Maman")
            .put("phone_number", "+33000000000")
            .put("last_message", "Message de test")
            .put("timestamp", DEMO_TS)
            .put("unread", false)

        return JSONObject().put("conversations", JSONArray().put(conversation))
    }

    fun messages(conversationId: String): JSONObject {
        val message = JSONObject()
            .put("id", "msg-1")
            .put("conversation_id", conversationId)
            .put("body", "Salut depuis Android Companion")
            .put("timestamp", DEMO_TS)
            .put("outgoing", false)

        return JSONObject().put("messages", JSONArray().put(message))
    }
}
