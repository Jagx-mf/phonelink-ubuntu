package com.phonelink.companion

import android.Manifest
import android.content.ContentUris
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.SystemClock
import android.provider.ContactsContract
import android.provider.Telephony
import android.telephony.SmsManager
import android.util.Log
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject

/**
 * Accès SMS réel via les API Android, exposé au format JSON du contrat
 * (cf. docs/android-backend-v0.4.md §2). V0.5.
 *
 * - Lecture conversations/messages : `ContentResolver` sur `Telephony.Sms`.
 * - Envoi : `SmsManager.divideMessage()` + `sendMultipartTextMessage()`.
 * - Résolution numéro → nom de contact : `ContactsContract` si READ_CONTACTS
 *   est accordée, sinon le numéro est utilisé comme nom.
 *
 * Toutes les méthodes de lecture supposent que [hasReadSms] est vraie : le
 * routage (CompanionServer) retombe sinon sur [DemoData]. Le format JSON est
 * **identique** à celui du mock pour ne pas casser le client Ubuntu.
 */
object SmsRepository {

    private const val TAG = "SmsRepository"
    private val MMS_PART_URI: Uri = Uri.parse("content://mms/part")

    // ---- permissions -----------------------------------------------------

    fun hasReadSms(context: Context): Boolean =
        granted(context, Manifest.permission.READ_SMS)

    fun hasSendSms(context: Context): Boolean =
        granted(context, Manifest.permission.SEND_SMS)

    fun hasReadContacts(context: Context): Boolean =
        granted(context, Manifest.permission.READ_CONTACTS)

    fun isDefaultSmsApp(context: Context): Boolean =
        Telephony.Sms.getDefaultSmsPackage(context) == context.packageName

    private fun granted(context: Context, permission: String): Boolean =
        ContextCompat.checkSelfPermission(context, permission) ==
            PackageManager.PERMISSION_GRANTED

    // ---- lecture ---------------------------------------------------------

    private data class ProviderMessage(
        val threadId: Long,
        val address: String,
        val body: String,
        val timestamp: Long,
        val outgoing: Boolean,
        val unreadIncoming: Boolean,
    )

    private data class MmsReadResult(
        val messages: List<ProviderMessage>,
        val partsRead: Int,
    )

    private data class MmsTextResult(
        val text: String,
        val partsRead: Int,
    )

    /**
     * Conversations, plus récente d'abord.
     *
     * V0.6 RC : on fusionne SMS (`content://sms`) et métadonnées MMS
     * (`content://mms`) pour atteindre la même surface que KDE Connect sans
     * lire `content://mms/part` dans la liste. Le corps complet des MMS est lu
     * uniquement par [messages] sur le thread ouvert.
     *
     * Renvoie `{ "conversations": [ {id, contact_name, phone_number,
     * last_message, last_timestamp, unread}, … ] }`.
     */
    fun conversations(context: Context, scanLimit: Int = 1000): JSONObject {
        val started = SystemClock.elapsedRealtime()
        data class Summary(
            var address: String,
            var lastBody: String,
            var lastTs: Long,
            var unread: Int,
        )

        val byThread = LinkedHashMap<Long, Summary>()
        val contactCache = HashMap<String, String>()
        val smsMessages = readRecentSmsMessages(context, null, scanLimit)
        val mmsMessages = readRecentMmsMessages(
            context,
            threadId = null,
            limit = scanLimit,
            readTextParts = false,
        )
        val messages = smsMessages + mmsMessages.messages

        for (message in messages.sortedByDescending { it.timestamp }) {
            val existing = byThread[message.threadId]
            if (existing == null) {
                byThread[message.threadId] = Summary(
                    address = message.address,
                    lastBody = message.body,
                    lastTs = message.timestamp,
                    unread = if (message.unreadIncoming) 1 else 0,
                )
            } else {
                if (message.timestamp > existing.lastTs) {
                    existing.lastBody = message.body
                    existing.lastTs = message.timestamp
                }
                if (existing.address.isBlank() && message.address.isNotBlank()) {
                    existing.address = message.address
                }
                if (message.unreadIncoming) {
                    existing.unread += 1
                }
            }
        }

        val array = JSONArray()
        for ((threadId, s) in byThread) {
            val name = resolveContactName(context, s.address, contactCache)
            array.put(
                JSONObject()
                    .put("id", threadId.toString())
                    .put("contact_name", name)
                    .put("phone_number", s.address)
                    .put("last_message", s.lastBody)
                    .put("last_timestamp", s.lastTs)
                    .put("unread", s.unread)
            )
        }
        Log.i(
            TAG,
            "/v1/conversations: ${array.length()} conversations in " +
                "${SystemClock.elapsedRealtime() - started}ms " +
                "sms=${smsMessages.size} mms=${mmsMessages.messages.size} " +
                "mmsParts=${mmsMessages.partsRead}",
        )
        return JSONObject().put("conversations", array)
    }

    /** Nombre de messages renvoyés par défaut (les plus récents). */
    const val DEFAULT_MESSAGE_LIMIT = 200

    /**
     * Messages d'une conversation, anciens → récents (pour l'affichage).
     *
     * On récupère les **[limit] messages les plus récents** (tri `DATE DESC` +
     * `LIMIT`), puis on **inverse** pour les renvoyer du plus ancien au plus
     * récent. C'est volontaire : sur un long fil, on veut les derniers messages,
     * pas les premiers.
     *
     * Renvoie `{ "conversation_id": id, "messages": [ {body, timestamp,
     * outgoing}, … ] }`.
     */
    fun messages(
        context: Context,
        conversationId: String,
        limit: Int = DEFAULT_MESSAGE_LIMIT,
    ): JSONObject {
        val started = SystemClock.elapsedRealtime()
        val safeLimit = limit.coerceIn(1, 2000)
        val threadId = conversationId.toLongOrNull()
        val smsMessages: List<ProviderMessage>
        val mmsMessages: MmsReadResult
        val recent: List<ProviderMessage>
        if (threadId == null) {
            smsMessages = emptyList()
            mmsMessages = MmsReadResult(emptyList(), 0)
            recent = emptyList()
        } else {
            smsMessages = readRecentSmsMessages(context, threadId, safeLimit)
            mmsMessages = readRecentMmsMessages(
                context,
                threadId = threadId,
                limit = safeLimit,
                readTextParts = true,
            )
            recent = (smsMessages + mmsMessages.messages)
                .sortedByDescending { it.timestamp }
                .take(safeLimit)
        }

        val array = JSONArray()
        for (message in recent.asReversed()) {
            array.put(
                JSONObject()
                    .put("body", message.body)
                    .put("timestamp", message.timestamp)
                    .put("outgoing", message.outgoing)
            )
        }
        Log.i(
            TAG,
            "/v1/messages: thread=$conversationId returned=${array.length()} " +
                "in ${SystemClock.elapsedRealtime() - started}ms " +
                "sms=${smsMessages.size} mms=${mmsMessages.messages.size} " +
                "mmsParts=${mmsMessages.partsRead}",
        )
        return JSONObject()
            .put("conversation_id", conversationId)
            .put("messages", array)
    }

    private fun readRecentSmsMessages(
        context: Context,
        threadId: Long?,
        limit: Int,
    ): List<ProviderMessage> {
        val resolver = context.contentResolver
        val projection = arrayOf(
            Telephony.Sms.THREAD_ID,
            Telephony.Sms.ADDRESS,
            Telephony.Sms.BODY,
            Telephony.Sms.DATE,
            Telephony.Sms.READ,
            Telephony.Sms.TYPE,
        )
        val selection = threadId?.let { "${Telephony.Sms.THREAD_ID} = ?" }
        val selectionArgs = threadId?.let { arrayOf(it.toString()) }
        val messages = ArrayList<ProviderMessage>(limit)
        try {
            resolver.query(
                Telephony.Sms.CONTENT_URI,
                projection,
                selection,
                selectionArgs,
                "${Telephony.Sms.DATE} DESC LIMIT $limit",
            )?.use { c ->
                val idxThread = c.getColumnIndexOrThrow(Telephony.Sms.THREAD_ID)
                val idxAddr = c.getColumnIndexOrThrow(Telephony.Sms.ADDRESS)
                val idxBody = c.getColumnIndexOrThrow(Telephony.Sms.BODY)
                val idxDate = c.getColumnIndexOrThrow(Telephony.Sms.DATE)
                val idxRead = c.getColumnIndexOrThrow(Telephony.Sms.READ)
                val idxType = c.getColumnIndexOrThrow(Telephony.Sms.TYPE)
                while (c.moveToNext() && messages.size < limit) {
                    val type = c.getInt(idxType)
                    val read = c.getInt(idxRead)
                    messages.add(
                        ProviderMessage(
                            threadId = c.getLong(idxThread),
                            address = c.getString(idxAddr).orEmpty(),
                            body = c.getString(idxBody).orEmpty(),
                            timestamp = c.getLong(idxDate),
                            outgoing = isOutgoing(type),
                            unreadIncoming = read == 0 && type == Telephony.Sms.MESSAGE_TYPE_INBOX,
                        )
                    )
                }
            }
        } catch (e: Exception) {
            // Une erreur de lecture SMS ne doit pas faire échouer le serveur.
        }
        return messages
    }

    private fun readRecentMmsMessages(
        context: Context,
        threadId: Long?,
        limit: Int,
        readTextParts: Boolean,
    ): MmsReadResult {
        val projection = arrayOf(
            Telephony.Mms._ID,
            Telephony.Mms.THREAD_ID,
            Telephony.Mms.DATE,
            Telephony.Mms.READ,
            Telephony.Mms.MESSAGE_BOX,
        )
        val selection = threadId?.let { "${Telephony.Mms.THREAD_ID} = ?" }
        val selectionArgs = threadId?.let { arrayOf(it.toString()) }
        val messages = ArrayList<ProviderMessage>(limit)
        var partsRead = 0
        try {
            queryWithSortFallback(
                context,
                Telephony.Mms.CONTENT_URI,
                projection,
                selection,
                selectionArgs,
                Telephony.Mms.DATE,
                limit,
            )?.use { c ->
                val idxId = c.getColumnIndexOrThrow(Telephony.Mms._ID)
                val idxThread = c.getColumnIndexOrThrow(Telephony.Mms.THREAD_ID)
                val idxDate = c.getColumnIndexOrThrow(Telephony.Mms.DATE)
                val idxRead = c.getColumnIndexOrThrow(Telephony.Mms.READ)
                val idxBox = c.getColumnIndexOrThrow(Telephony.Mms.MESSAGE_BOX)
                while (c.moveToNext() && messages.size < limit) {
                    val id = c.getLong(idxId)
                    val messageBox = c.getInt(idxBox)
                    val body = if (readTextParts) {
                        val text = readMmsText(context, id)
                        partsRead += text.partsRead
                        text.text
                    } else {
                        "MMS"
                    }
                    val address = if (readTextParts) {
                        readMmsAddress(context, id, messageBox)
                    } else {
                        ""
                    }
                    messages.add(
                        ProviderMessage(
                            threadId = c.getLong(idxThread),
                            address = address,
                            body = body,
                            timestamp = normalizeProviderTimestamp(c.getLong(idxDate)),
                            outgoing = isMmsOutgoing(messageBox),
                            unreadIncoming = c.getInt(idxRead) == 0 &&
                                messageBox == Telephony.Mms.MESSAGE_BOX_INBOX,
                        )
                    )
                }
            }
        } catch (e: Exception) {
            // Certains ROMs exposent partiellement content://mms ; on garde les SMS.
        }
        return MmsReadResult(messages, partsRead)
    }

    private fun queryWithSortFallback(
        context: Context,
        uri: Uri,
        projection: Array<String>,
        selection: String?,
        selectionArgs: Array<String>?,
        dateColumn: String,
        limit: Int,
    ): android.database.Cursor? {
        return try {
            context.contentResolver.query(
                uri,
                projection,
                selection,
                selectionArgs,
                "$dateColumn DESC LIMIT $limit",
            )
        } catch (e: Exception) {
            context.contentResolver.query(
                uri,
                projection,
                selection,
                selectionArgs,
                "$dateColumn DESC",
            )
        }
    }

    private fun readMmsText(context: Context, mid: Long): MmsTextResult {
        val projection = arrayOf(
            Telephony.Mms.Part._ID,
            Telephony.Mms.Part._DATA,
            Telephony.Mms.Part.CONTENT_TYPE,
            Telephony.Mms.Part.TEXT,
        )
        val parts = ArrayList<String>()
        var partsRead = 0
        try {
            context.contentResolver.query(
                MMS_PART_URI,
                projection,
                "${Telephony.Mms.Part.MSG_ID} = ?",
                arrayOf(mid.toString()),
                null,
            )?.use { c ->
                val idxId = c.getColumnIndexOrThrow(Telephony.Mms.Part._ID)
                val idxData = c.getColumnIndexOrThrow(Telephony.Mms.Part._DATA)
                val idxType = c.getColumnIndexOrThrow(Telephony.Mms.Part.CONTENT_TYPE)
                val idxText = c.getColumnIndexOrThrow(Telephony.Mms.Part.TEXT)
                while (c.moveToNext()) {
                    val contentType = c.getString(idxType).orEmpty()
                    if (!isTextContentType(contentType)) continue
                    partsRead += 1
                    val text = if (!c.isNull(idxData)) {
                        readMmsPartData(context, c.getLong(idxId))
                    } else {
                        c.getString(idxText).orEmpty()
                    }
                    if (text.isNotBlank()) parts.add(text)
                }
            }
        } catch (e: Exception) {
            // Une part illisible ne doit pas bloquer le reste du fil.
        }
        return MmsTextResult(parts.joinToString("\n").trim(), partsRead)
    }

    private fun readMmsPartData(context: Context, partId: Long): String {
        val uri = ContentUris.withAppendedId(MMS_PART_URI, partId)
        return try {
            context.contentResolver.openInputStream(uri)?.use { stream ->
                stream.readBytes().toString(Charsets.UTF_8)
            }.orEmpty()
        } catch (e: Exception) {
            ""
        }
    }

    private fun readMmsAddress(context: Context, mid: Long, messageBox: Int): String {
        val uri = Uri.parse("content://mms/$mid/addr")
        var fallback = ""
        var preferred = ""
        try {
            context.contentResolver.query(
                uri,
                arrayOf("address", "type"),
                null,
                null,
                null,
            )?.use { c ->
                val idxAddress = c.getColumnIndex("address")
                val idxType = c.getColumnIndex("type")
                while (c.moveToNext()) {
                    val address = if (idxAddress >= 0) c.getString(idxAddress).orEmpty() else ""
                    if (address.isBlank() || address == "insert-address-token") continue
                    val type = if (idxType >= 0) c.getInt(idxType) else 0
                    if (isIncomingMms(messageBox) && type == 137) return address // FROM
                    if (isMmsOutgoing(messageBox) && (type == 151 || type == 130)) {
                        preferred = address // TO / CC
                    }
                    if (fallback.isBlank()) fallback = address
                }
            }
        } catch (e: Exception) {
            return fallback
        }
        return preferred.ifBlank { fallback }
    }

    fun debugMmsParts(context: Context, mid: Long): JSONObject {
        val parts = JSONArray()
        val root = JSONObject()
            .put("status", "ok")
            .put("mid", mid)
            .put("uri", MMS_PART_URI.toString())
            .put("parts", parts)
        try {
            context.contentResolver.query(
                MMS_PART_URI,
                null,
                "${Telephony.Mms.Part.MSG_ID} = ?",
                arrayOf(mid.toString()),
                null,
            )?.use { c ->
                root.put("columns", JSONArray(c.columnNames.toList()))
                while (c.moveToNext()) {
                    parts.put(debugMmsPartRow(context, c))
                }
            } ?: root.put("status", "null_cursor")
        } catch (e: Exception) {
            root
                .put("status", "error")
                .put("error", e.javaClass.simpleName)
                .put("message", e.message ?: "")
        }
        return root.put("part_count", parts.length())
    }

    private fun debugMmsPartRow(context: Context, c: android.database.Cursor): JSONObject {
        val row = JSONObject()
        for (i in 0 until c.columnCount) {
            row.put(c.getColumnName(i), cursorValue(c, i))
        }
        val id = c.getColumnIndex(Telephony.Mms.Part._ID)
            .takeIf { it >= 0 && !c.isNull(it) }
            ?.let { c.getLong(it) }
        val contentType = c.getColumnIndex(Telephony.Mms.Part.CONTENT_TYPE)
            .takeIf { it >= 0 && !c.isNull(it) }
            ?.let { c.getString(it) }
            .orEmpty()
        row.put("is_text_part", isTextContentType(contentType))
        if (id != null && isTextContentType(contentType)) {
            row.put("resolved_text", readMmsPartResolvedText(context, c, id))
        }
        return row
    }

    /** True pour les types « sortants » (envoyé / outbox / échec / file). */
    private fun isOutgoing(type: Int): Boolean = when (type) {
        Telephony.Sms.MESSAGE_TYPE_SENT,
        Telephony.Sms.MESSAGE_TYPE_OUTBOX,
        Telephony.Sms.MESSAGE_TYPE_FAILED,
        Telephony.Sms.MESSAGE_TYPE_QUEUED -> true
        else -> false
    }

    private fun isMmsOutgoing(messageBox: Int): Boolean = when (messageBox) {
        Telephony.Mms.MESSAGE_BOX_SENT,
        Telephony.Mms.MESSAGE_BOX_OUTBOX,
        Telephony.Mms.MESSAGE_BOX_FAILED -> true
        else -> false
    }

    private fun isIncomingMms(messageBox: Int): Boolean =
        messageBox == Telephony.Mms.MESSAGE_BOX_INBOX

    private fun normalizeProviderTimestamp(raw: Long): Long =
        if (raw in 1L..9_999_999_999L) raw * 1000L else raw

    private fun isTextContentType(contentType: String): Boolean =
        contentType.lowercase().startsWith("text/")

    private fun readMmsPartResolvedText(
        context: Context,
        c: android.database.Cursor,
        partId: Long,
    ): String {
        val idxData = c.getColumnIndex(Telephony.Mms.Part._DATA)
        val idxText = c.getColumnIndex(Telephony.Mms.Part.TEXT)
        return if (idxData >= 0 && !c.isNull(idxData)) {
            readMmsPartData(context, partId)
        } else if (idxText >= 0 && !c.isNull(idxText)) {
            c.getString(idxText).orEmpty()
        } else {
            ""
        }
    }

    private fun cursorValue(c: android.database.Cursor, index: Int): Any {
        if (c.isNull(index)) return JSONObject.NULL
        return when (c.getType(index)) {
            android.database.Cursor.FIELD_TYPE_INTEGER -> c.getLong(index)
            android.database.Cursor.FIELD_TYPE_FLOAT -> c.getDouble(index)
            android.database.Cursor.FIELD_TYPE_BLOB -> "<blob ${c.getBlob(index)?.size ?: 0} bytes>"
            else -> c.getString(index) ?: JSONObject.NULL
        }
    }

    // ---- envoi -----------------------------------------------------------

    /**
     * Résultat d'un envoi. [echo] est le message tel qu'il doit apparaître côté
     * Ubuntu (outgoing=true), avec un horodatage local.
     */
    data class SendOutcome(val sent: Boolean, val error: String?, val echo: JSONObject?)

    /**
     * Envoie un SMS texte via [SmsManager]. Le découpage multipart est géré par
     * `divideMessage()` (gère >160 GSM-7 / >70 UCS-2). Aucune persistance dans
     * `Telephony.Sms` n'est tentée (exigerait d'être l'app SMS par défaut) — le
     * message renvoyé est un écho local.
     */
    fun send(context: Context, phoneNumber: String?, body: String): SendOutcome {
        val number = phoneNumber?.trim().orEmpty()
        if (number.isEmpty()) {
            return SendOutcome(false, "phone_number requis pour l'envoi", null)
        }
        if (body.isBlank()) {
            return SendOutcome(false, "body vide", null)
        }
        return try {
            val manager = smsManager(context)
            val parts = manager.divideMessage(body)
            if (parts.size <= 1) {
                manager.sendTextMessage(number, null, body, null, null)
            } else {
                manager.sendMultipartTextMessage(number, null, parts, null, null)
            }
            val echo = JSONObject()
                .put("body", body)
                .put("timestamp", System.currentTimeMillis())
                .put("outgoing", true)
            SendOutcome(true, null, echo)
        } catch (e: Exception) {
            SendOutcome(false, "échec d'envoi: ${e.message ?: "inconnu"}", null)
        }
    }

    @Suppress("DEPRECATION")
    private fun smsManager(context: Context): SmsManager =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            context.getSystemService(SmsManager::class.java)
        } else {
            SmsManager.getDefault()
        }

    // ---- contacts --------------------------------------------------------

    /**
     * Résout un numéro en nom de contact via [ContactsContract] si READ_CONTACTS
     * est accordée. Retombe sur le numéro lui-même sinon, ou si non trouvé.
     */
    private fun resolveContactName(
        context: Context,
        phoneNumber: String,
        cache: MutableMap<String, String>,
    ): String {
        if (phoneNumber.isBlank()) return phoneNumber
        cache[phoneNumber]?.let { return it }
        if (!hasReadContacts(context)) {
            cache[phoneNumber] = phoneNumber
            return phoneNumber
        }
        var name = phoneNumber
        try {
            val uri: Uri = Uri.withAppendedPath(
                ContactsContract.PhoneLookup.CONTENT_FILTER_URI,
                Uri.encode(phoneNumber),
            )
            context.contentResolver.query(
                uri,
                arrayOf(ContactsContract.PhoneLookup.DISPLAY_NAME),
                null,
                null,
                null,
            )?.use { c ->
                if (c.moveToFirst()) {
                    val display = c.getString(0)
                    if (!display.isNullOrBlank()) name = display
                }
            }
        } catch (e: Exception) {
            // En cas d'échec, on garde le numéro comme nom.
        }
        cache[phoneNumber] = name
        return name
    }
}
