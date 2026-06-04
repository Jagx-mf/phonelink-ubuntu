package com.phonelink.companion

import android.content.Context
import fi.iki.elonen.NanoHTTPD
import org.json.JSONArray
import org.json.JSONObject

/**
 * Serveur HTTP local de PhoneLink Companion (NanoHTTPD).
 *
 * Endpoints (préfixe `/v1`) :
 *  - `GET  /health`        public
 *  - `POST /pair`          PIN → token
 *  - `GET  /conversations` token requis
 *  - `GET  /messages`      token requis
 *  - `POST /send`          token requis (envoi réel via SmsManager)
 *  - `GET  /rcs/messages`  token requis (RCS captés via notifications)
 *  - `GET  /debug/notifications` token requis (diagnostic notifications)
 *  - `GET  /debug/sms-provider` token requis (diagnostic providers SMS/MMS)
 *  - `GET  /debug/mms-parts` token requis (diagnostic parts MMS)
 *
 * V0.5 — SMS réels : si les permissions SMS sont accordées, les endpoints
 * lisent/écrivent les vrais SMS via [SmsRepository]. Sinon ils retombent sur
 * [DemoData] (fallback de démo, même format JSON). `/health` reflète honnêtement
 * l'état (`sms_permission`).
 *
 * Réponses toujours en JSON. Le token est attendu dans l'en-tête
 * `Authorization: Bearer <token>`.
 */
class CompanionServer(
    port: Int,
    private val pairing: PairingManager,
    private val deviceName: String,
    private val context: Context,
    private val appVersion: String,
) : NanoHTTPD(port) {

    init {
        RcsMessageStore.attach(context)
    }

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
                guarded(session) { conversations() }
            method == Method.GET && uri == "/v1/messages" ->
                guarded(session) { messages(session) }
            method == Method.POST && uri == "/v1/send" ->
                guarded(session) { send(session) }
            method == Method.GET && uri == "/v1/rcs/messages" ->
                guarded(session) { rcsMessages() }
            method == Method.GET && uri == "/v1/debug/notifications" ->
                guarded(session) { debugNotifications() }
            method == Method.GET && uri == "/v1/debug/sms-provider" ->
                guarded(session) { debugSmsProvider(session) }
            method == Method.GET && uri == "/v1/debug/mms-parts" ->
                guarded(session) { debugMmsParts(session) }
            else -> jsonError(Response.Status.NOT_FOUND, "not_found")
        }
    }

    // ---- endpoints -------------------------------------------------------

    private fun health(): Response {
        val smsPermission =
            SmsRepository.hasReadSms(context) && SmsRepository.hasSendSms(context)
        val body = JSONObject()
            // Champs du contrat (docs/android-backend-v0.4.md §6) consommés par
            // app/core/android_bridge.py.
            .put("status", "ok")
            .put("app_version", appVersion)
            .put("sms_permission", smsPermission)
            .put("default_sms_app", SmsRepository.isDefaultSmsApp(context))
            .put("notification_access", RcsNotificationListener.hasAccess(context))
            .put("device", deviceName)
            // Champs historiques conservés pour rétro-compatibilité de l'app.
            .put("paired", pairing.isPaired)
            .put("api_version", "v1")
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

    private fun conversations(): Response {
        val data = if (SmsRepository.hasReadSms(context)) {
            SmsRepository.conversations(context)
        } else {
            DemoData.conversations()
        }
        return json(Response.Status.OK, data)
    }

    private fun messages(session: IHTTPSession): Response {
        val conversationId =
            session.parameters["conversation_id"]?.firstOrNull() ?: "demo-1"
        val limit = session.parameters["limit"]?.firstOrNull()?.toIntOrNull()
            ?: SmsRepository.DEFAULT_MESSAGE_LIMIT
        val data = if (SmsRepository.hasReadSms(context)) {
            SmsRepository.messages(context, conversationId, limit)
        } else {
            DemoData.messages(conversationId)
        }
        return json(Response.Status.OK, data)
    }

    private fun send(session: IHTTPSession): Response {
        if (!SmsRepository.hasSendSms(context)) {
            return json(
                Response.Status.SERVICE_UNAVAILABLE,
                JSONObject()
                    .put("sent", false)
                    .put("error", "permission SEND_SMS manquante"),
            )
        }
        val payload = readJsonBody(session)
        val body = payload?.optString("body").orEmpty()
        // Le client peut fournir phone_number (nouveau fil). Si seul
        // conversation_id est fourni, on tente d'en déduire le numéro.
        var phoneNumber = payload?.optString("phone_number").orEmpty()
        val conversationId = payload?.optString("conversation_id").orEmpty()
        if (phoneNumber.isBlank() && conversationId.isNotBlank()) {
            phoneNumber = phoneNumberForThread(conversationId)
        }

        val outcome = SmsRepository.send(context, phoneNumber, body)
        val result = JSONObject().put("sent", outcome.sent)
        outcome.error?.let { result.put("error", it) }
        outcome.echo?.let { result.put("message", it) }
        val status = if (outcome.sent) {
            Response.Status.OK
        } else {
            Response.Status.BAD_REQUEST
        }
        return json(status, result)
    }

    private fun rcsMessages(): Response {
        RcsNotificationListener.instance?.refreshFromActive()
        return json(Response.Status.OK, RcsMessageStore.snapshot())
    }

    private fun debugNotifications(): Response {
        val body = try {
            val listener = RcsNotificationListener.instance
            if (listener != null) {
                val notifications = listener.debugDump()
                JSONObject()
                    .put("status", "ok")
                    .put("target_package", RcsNotificationListener.TARGET_PACKAGE)
                    .put("notification_count", notifications.length())
                    .put("notifications", notifications)
            } else {
                JSONObject()
                    .put("status", "listener_not_connected")
                    .put("error", "notification_listener_not_connected")
                    .put("target_package", RcsNotificationListener.TARGET_PACKAGE)
                    .put("notification_count", 0)
                    .put("notifications", JSONArray())
            }
        } catch (e: Exception) {
            JSONObject()
                .put("status", "error")
                .put("error", e.javaClass.simpleName)
                .put("message", e.message ?: "")
                .put("target_package", RcsNotificationListener.TARGET_PACKAGE)
                .put("notification_count", 0)
                .put("notifications", JSONArray())
        }
        return json(Response.Status.OK, body)
    }

    private fun debugSmsProvider(session: IHTTPSession): Response {
        val address = session.parameters["address"]?.firstOrNull()
        val body = SmsProviderDebug.dump(context, address)
        return json(Response.Status.OK, body)
    }

    private fun debugMmsParts(session: IHTTPSession): Response {
        val mid = session.parameters["mid"]?.firstOrNull()?.toLongOrNull()
        if (mid == null) {
            return jsonError(Response.Status.BAD_REQUEST, "invalid_mid")
        }
        return json(Response.Status.OK, SmsRepository.debugMmsParts(context, mid))
    }

    /** Numéro associé à un thread, lu depuis le résumé des conversations. */
    private fun phoneNumberForThread(conversationId: String): String {
        if (!SmsRepository.hasReadSms(context)) return ""
        val convos = SmsRepository.conversations(context)
            .optJSONArray("conversations") ?: return ""
        for (i in 0 until convos.length()) {
            val c = convos.optJSONObject(i) ?: continue
            if (c.optString("id") == conversationId) {
                return c.optString("phone_number")
            }
        }
        return ""
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

    private fun json(status: Response.IStatus, obj: JSONObject): Response =
        newFixedLengthResponse(status, "application/json", obj.toString())

    private fun jsonError(status: Response.Status, code: String): Response =
        newFixedLengthResponse(
            status,
            "application/json",
            JSONObject().put("error", code).toString(),
        )
}
