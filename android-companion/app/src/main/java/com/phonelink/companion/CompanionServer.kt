package com.phonelink.companion

import fi.iki.elonen.NanoHTTPD
import org.json.JSONObject

/**
 * Serveur HTTP local de PhoneLink Companion (NanoHTTPD).
 *
 * Endpoints (préfixe `/v1`) :
 *  - `GET  /health`        public
 *  - `POST /pair`          PIN → token
 *  - `GET  /conversations` token requis (démo)
 *  - `GET  /messages`      token requis (démo)
 *  - `POST /send`          token requis (n'envoie aucun vrai SMS)
 *
 * Réponses toujours en JSON. Le token est attendu dans l'en-tête
 * `Authorization: Bearer <token>`.
 */
class CompanionServer(
    port: Int,
    private val pairing: PairingManager,
    private val deviceName: String,
) : NanoHTTPD(port) {

    override fun serve(session: IHTTPSession): Response {
        return try {
            route(session)
        } catch (e: Exception) {
            jsonError(Response.Status.INTERNAL_ERROR, "server_error")
        }
    }

    private fun route(session: IHTTPSession): Response {
        val uri = session.uri
        val method = session.method
        return when {
            method == Method.GET && uri == "/v1/health" -> health()
            method == Method.POST && uri == "/v1/pair" -> pair(session)
            method == Method.GET && uri == "/v1/conversations" ->
                guarded(session) { json(Response.Status.OK, DemoData.conversations()) }
            method == Method.GET && uri == "/v1/messages" ->
                guarded(session) { messages(session) }
            method == Method.POST && uri == "/v1/send" ->
                guarded(session) { send() }
            else -> jsonError(Response.Status.NOT_FOUND, "not_found")
        }
    }

    // ---- endpoints -------------------------------------------------------

    private fun health(): Response {
        val body = JSONObject()
            .put("ok", true)
            .put("device_name", deviceName)
            .put("api_version", "v1")
            .put("paired", pairing.isPaired)
        return json(Response.Status.OK, body)
    }

    private fun pair(session: IHTTPSession): Response {
        val pin = readJsonBody(session)?.optString("pin")
        val token = pairing.verifyPinAndIssueToken(pin)
        return if (token != null) {
            json(Response.Status.OK, JSONObject().put("token", token))
        } else {
            jsonError(Response.Status.UNAUTHORIZED, "invalid_pin")
        }
    }

    private fun messages(session: IHTTPSession): Response {
        val conversationId = session.parameters["conversation_id"]?.firstOrNull() ?: "demo-1"
        return json(Response.Status.OK, DemoData.messages(conversationId))
    }

    private fun send(): Response {
        val body = JSONObject()
            .put("sent", false)
            .put("detail", "SMS réel non implémenté dans cette version")
        return json(Response.Status.OK, body)
    }

    // ---- sécurité --------------------------------------------------------

    /** Exécute [block] seulement si un token Bearer valide est présent. */
    private fun guarded(session: IHTTPSession, block: () -> Response): Response {
        // NanoHTTPD met les noms d'en-têtes en minuscules.
        val header = session.headers["authorization"].orEmpty()
        val token = header.removePrefix("Bearer ").trim()
        return if (pairing.isValidToken(token)) {
            block()
        } else {
            jsonError(Response.Status.UNAUTHORIZED, "unauthorized")
        }
    }

    // ---- helpers ---------------------------------------------------------

    private fun readJsonBody(session: IHTTPSession): JSONObject? {
        return try {
            val files = HashMap<String, String>()
            session.parseBody(files)            // place le corps brut sous "postData"
            val data = files["postData"] ?: return null
            JSONObject(data)
        } catch (e: Exception) {
            null
        }
    }

    private fun json(status: Response.Status, obj: JSONObject): Response =
        newFixedLengthResponse(status, "application/json", obj.toString())

    private fun jsonError(status: Response.Status, code: String): Response =
        newFixedLengthResponse(
            status,
            "application/json",
            JSONObject().put("error", code).toString(),
        )
}
