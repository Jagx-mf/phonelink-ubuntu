package com.phonelink.companion

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
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
 *  - `GET  /device/status` token requis (batterie + statut téléphone, V0.8)
 *  - `GET  /notifications`  token requis (snapshot notifications actives, V0.8)
 *  - `GET  /events`        token requis (long polling temps réel, V0.9)
 *  - `GET  /files/roots`   token requis (racines autorisées, V1.0)
 *  - `GET  /files/list`    token requis (contenu d'un dossier, V1.0)
 *  - `GET  /files/download` token requis (téléchargement binaire, V1.0)
 *  - `POST /files/upload`  token requis (upload binaire brut, V1.0)
 *  - `POST /files/mkdir`   token requis (V1.0)
 *  - `POST /files/delete`  token requis (V1.0)
 *  - `POST /files/rename`  token requis (V1.0)
 *  - `GET  /contacts`      token requis (carnet d'adresses, V1.0)
 *  - `GET  /contacts/search` token requis (filtre q=, V1.0)
 *  - `POST /call/start`    token requis (ouvre le dialer ACTION_DIAL, V1.0)
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
            method == Method.GET && uri == "/v1/device/status" ->
                guarded(session) { deviceStatus() }
            method == Method.GET && uri == "/v1/notifications" ->
                guarded(session) { notifications() }
            method == Method.GET && uri == "/v1/events" ->
                guarded(session) { events(session) }
            method == Method.GET && uri == "/v1/files/roots" ->
                guarded(session) { filesRoots() }
            method == Method.GET && uri == "/v1/files/list" ->
                guarded(session) { filesList(session) }
            method == Method.GET && uri == "/v1/files/download" ->
                guarded(session) { filesDownload(session) }
            method == Method.POST && uri == "/v1/files/upload" ->
                guarded(session) { filesUpload(session) }
            method == Method.POST && uri == "/v1/files/mkdir" ->
                guarded(session) { filesMkdir(session) }
            method == Method.POST && uri == "/v1/files/delete" ->
                guarded(session) { filesDelete(session) }
            method == Method.POST && uri == "/v1/files/rename" ->
                guarded(session) { filesRename(session) }
            method == Method.GET && uri == "/v1/contacts" ->
                guarded(session) { contacts(session, search = false) }
            method == Method.GET && uri == "/v1/contacts/search" ->
                guarded(session) { contacts(session, search = true) }
            method == Method.POST && uri == "/v1/call/start" ->
                guarded(session) { callStart(session) }
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
            // V1.0 — capacités fichiers/contacts (champs additifs, le client
            // V0.x les ignore simplement).
            .put("files_permission", FileRepository.hasFullAccess(context))
            .put("contacts_permission", ContactsRepository.hasReadContacts(context))
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

    /**
     * V0.8 — batterie + statut téléphone. N'ajoute aucune dépendance : la
     * batterie est lue via le sticky broadcast [Intent.ACTION_BATTERY_CHANGED]
     * (API standard) et les autres champs réutilisent les helpers existants
     * ([SmsRepository], [RcsNotificationListener]). `/v1/health` reste inchangé.
     */
    private fun deviceStatus(): Response {
        val battery = batteryInfo()
        val body = JSONObject()
            .put("battery_level", battery.level)
            .put("battery_charging", battery.charging)
            .put("battery_status", battery.status)
            .put("device", deviceName)
            .put("server_running", CompanionForegroundService.isRunning)
            .put("sms_permission", SmsRepository.hasReadSms(context) && SmsRepository.hasSendSms(context))
            .put("notification_access", RcsNotificationListener.hasAccess(context))
            .put("default_sms_app", SmsRepository.isDefaultSmsApp(context))
            .put("api_version", "v1")
        return json(Response.Status.OK, body)
    }

    private data class BatteryInfo(val level: Int, val charging: Boolean, val status: String)

    /** Lit l'état batterie depuis le sticky broadcast ACTION_BATTERY_CHANGED. */
    private fun batteryInfo(): BatteryInfo {
        val intent = try {
            context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        } catch (e: Exception) {
            null
        }
        val level = intent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = intent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val pct = if (level >= 0 && scale > 0) level * 100 / scale else -1
        val statusRaw = intent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val charging = statusRaw == BatteryManager.BATTERY_STATUS_CHARGING ||
            statusRaw == BatteryManager.BATTERY_STATUS_FULL
        val status = when (statusRaw) {
            BatteryManager.BATTERY_STATUS_CHARGING -> "charging"
            BatteryManager.BATTERY_STATUS_DISCHARGING -> "discharging"
            BatteryManager.BATTERY_STATUS_FULL -> "full"
            BatteryManager.BATTERY_STATUS_NOT_CHARGING -> "not_charging"
            else -> "unknown"
        }
        return BatteryInfo(pct, charging, status)
    }

    /**
     * V0.8 — snapshot lecture seule des notifications Android actives (toutes
     * applications), via [RcsNotificationListener]. Si le listener n'est pas
     * connecté, renvoie `{ "status": "listener_not_connected", "notifications":
     * [] }` avec HTTP 200 (pas d'erreur serveur). Lecture seule : aucune action
     * RemoteInput. N'impacte pas `/v1/rcs/messages` ni `/v1/debug/notifications`.
     */
    private fun notifications(): Response {
        val listener = RcsNotificationListener.instance
            ?: return json(
                Response.Status.OK,
                JSONObject()
                    .put("status", "listener_not_connected")
                    .put("notifications", JSONArray()),
            )
        return json(
            Response.Status.OK,
            JSONObject().put("notifications", listener.activeNotificationsSnapshot()),
        )
    }

    /**
     * V0.9 — long polling temps réel. `GET /v1/events?since=<id>&timeout_ms=<ms>`.
     *
     * Renvoie les événements d'id > `since` ; si aucun, **attend** jusqu'à
     * `timeout_ms` (borné 1–30 s, défaut 25 s) qu'un nouvel événement arrive,
     * puis répond (liste possiblement vide). Permet à Ubuntu d'afficher les
     * nouveaux SMS/notifications sans bouton « Rafraîchir ».
     *
     * `since` absent/invalide ⇒ resynchro initiale (liste vide + `last_event_id`
     * courant). Voir [EventBus]. N'impacte aucun endpoint existant.
     */
    private fun events(session: IHTTPSession): Response {
        val since = session.parameters["since"]?.firstOrNull()?.toLongOrNull() ?: -1L
        val timeoutMs = session.parameters["timeout_ms"]?.firstOrNull()?.toLongOrNull()
            ?: EventBus.DEFAULT_TIMEOUT_MS
        return json(Response.Status.OK, EventBus.poll(since, timeoutMs))
    }

    // ---- fichiers (V1.0 — Phase 1) ----------------------------------------

    /** Garde commune : permission stockage requise pour tous les endpoints /v1/files. */
    private fun requireFilesAccess(): Response? {
        if (FileRepository.hasFullAccess(context)) return null
        return json(
            Response.Status.FORBIDDEN,
            JSONObject().put("error", "files_permission_missing"),
        )
    }

    private fun filesRoots(): Response {
        requireFilesAccess()?.let { return it }
        return json(Response.Status.OK, FileRepository.roots())
    }

    private fun filesList(session: IHTTPSession): Response {
        requireFilesAccess()?.let { return it }
        val raw = session.parameters["path"]?.firstOrNull()
        val dir = FileRepository.resolve(raw)
            ?: return jsonError(Response.Status.BAD_REQUEST, "forbidden_path")
        if (!dir.isDirectory) {
            return jsonError(Response.Status.BAD_REQUEST, "not_a_directory")
        }
        return json(Response.Status.OK, FileRepository.list(dir))
    }

    /**
     * Téléchargement binaire en streaming (pas de chargement en mémoire). Le
     * nom de fichier est fourni en en-tête `Content-Disposition` pour le client.
     */
    private fun filesDownload(session: IHTTPSession): Response {
        requireFilesAccess()?.let { return it }
        val raw = session.parameters["path"]?.firstOrNull()
        val file = FileRepository.resolve(raw)
            ?: return jsonError(Response.Status.BAD_REQUEST, "forbidden_path")
        if (!file.isFile) {
            return jsonError(Response.Status.NOT_FOUND, "not_found")
        }
        return try {
            val response = newFixedLengthResponse(
                Response.Status.OK,
                FileRepository.mimeOf(file.name),
                file.inputStream(),
                file.length(),
            )
            val safeName = file.name.replace("\"", "_")
            response.addHeader(
                "Content-Disposition",
                "attachment; filename=\"$safeName\"",
            )
            response
        } catch (e: Exception) {
            jsonError(Response.Status.INTERNAL_ERROR, "read_failed")
        }
    }

    /**
     * Upload binaire **brut** : `POST /v1/files/upload?path=<dossier>&name=<nom>`
     * avec le contenu du fichier en corps de requête (octet-stream). On lit
     * directement le flux de la session (pas de `parseBody` : il bufferiserait
     * et corromprait le binaire).
     */
    private fun filesUpload(session: IHTTPSession): Response {
        requireFilesAccess()?.let { return it }
        val rawDir = session.parameters["path"]?.firstOrNull()
        val name = session.parameters["name"]?.firstOrNull()
        val dir = FileRepository.resolve(rawDir)
            ?: return jsonError(Response.Status.BAD_REQUEST, "forbidden_path")
        val contentLength = session.headers["content-length"]?.toLongOrNull() ?: -1L
        if (contentLength < 0) {
            return jsonError(Response.Status.BAD_REQUEST, "missing_content_length")
        }
        val result = FileRepository.upload(
            context, dir, name, session.inputStream, contentLength
        )
        val status = if (result.optBoolean("ok")) {
            Response.Status.OK
        } else {
            Response.Status.BAD_REQUEST
        }
        return json(status, result)
    }

    private fun filesMkdir(session: IHTTPSession): Response {
        requireFilesAccess()?.let { return it }
        val payload = readJsonBody(session)
        val dir = FileRepository.resolve(payload?.optString("path"))
            ?: return jsonError(Response.Status.BAD_REQUEST, "forbidden_path")
        val result = FileRepository.mkdir(dir, payload?.optString("name"))
        val status = if (result.optBoolean("ok")) {
            Response.Status.OK
        } else {
            Response.Status.BAD_REQUEST
        }
        return json(status, result)
    }

    private fun filesDelete(session: IHTTPSession): Response {
        requireFilesAccess()?.let { return it }
        val payload = readJsonBody(session)
        val target = FileRepository.resolve(payload?.optString("path"))
            ?: return jsonError(Response.Status.BAD_REQUEST, "forbidden_path")
        if (!target.exists()) {
            return jsonError(Response.Status.NOT_FOUND, "not_found")
        }
        val result = FileRepository.delete(context, target)
        val status = if (result.optBoolean("ok")) {
            Response.Status.OK
        } else {
            Response.Status.BAD_REQUEST
        }
        return json(status, result)
    }

    private fun filesRename(session: IHTTPSession): Response {
        requireFilesAccess()?.let { return it }
        val payload = readJsonBody(session)
        val source = FileRepository.resolve(payload?.optString("path"))
            ?: return jsonError(Response.Status.BAD_REQUEST, "forbidden_path")
        val result = FileRepository.rename(context, source, payload?.optString("new_name"))
        val status = if (result.optBoolean("ok")) {
            Response.Status.OK
        } else {
            Response.Status.BAD_REQUEST
        }
        return json(status, result)
    }

    // ---- contacts & appel (V1.0 — Phase 2) --------------------------------

    private fun contacts(session: IHTTPSession, search: Boolean): Response {
        if (!ContactsRepository.hasReadContacts(context)) {
            return json(
                Response.Status.FORBIDDEN,
                JSONObject().put("error", "contacts_permission_missing"),
            )
        }
        val query = if (search) session.parameters["q"]?.firstOrNull() else null
        return json(Response.Status.OK, ContactsRepository.contacts(context, query))
    }

    private fun callStart(session: IHTTPSession): Response {
        val payload = readJsonBody(session)
        val result = ContactsRepository.startDial(
            context, payload?.optString("phone_number")
        )
        val status = if (result.optBoolean("ok")) {
            Response.Status.OK
        } else {
            Response.Status.BAD_REQUEST
        }
        return json(status, result)
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
