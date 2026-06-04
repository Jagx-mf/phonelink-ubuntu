package com.phonelink.companion

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.ContactsContract
import android.provider.Telephony
import android.telephony.SmsManager
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

    /**
     * Conversations, plus récente d'abord. On parcourt les SMS triés par date
     * décroissante (limités à [scanLimit]) et on retient la première occurrence
     * de chaque `thread_id` comme résumé de conversation, en comptant au passage
     * les messages non lus reçus.
     *
     * Renvoie `{ "conversations": [ {id, contact_name, phone_number,
     * last_message, last_timestamp, unread}, … ] }`.
     */
    fun conversations(context: Context, scanLimit: Int = 1000): JSONObject {
        val resolver = context.contentResolver
        val projection = arrayOf(
            Telephony.Sms.THREAD_ID,
            Telephony.Sms.ADDRESS,
            Telephony.Sms.BODY,
            Telephony.Sms.DATE,
            Telephony.Sms.READ,
            Telephony.Sms.TYPE,
        )

        // Résumé par thread (premier vu = le plus récent grâce au tri DESC).
        data class Summary(
            val address: String,
            val lastBody: String,
            val lastTs: Long,
            var unread: Int,
        )

        val byThread = LinkedHashMap<Long, Summary>()
        val contactCache = HashMap<String, String>()

        resolver.query(
            Telephony.Sms.CONTENT_URI,
            projection,
            null,
            null,
            "${Telephony.Sms.DATE} DESC",
        )?.use { c ->
            val idxThread = c.getColumnIndexOrThrow(Telephony.Sms.THREAD_ID)
            val idxAddr = c.getColumnIndexOrThrow(Telephony.Sms.ADDRESS)
            val idxBody = c.getColumnIndexOrThrow(Telephony.Sms.BODY)
            val idxDate = c.getColumnIndexOrThrow(Telephony.Sms.DATE)
            val idxRead = c.getColumnIndexOrThrow(Telephony.Sms.READ)
            val idxType = c.getColumnIndexOrThrow(Telephony.Sms.TYPE)

            var scanned = 0
            while (c.moveToNext() && scanned < scanLimit) {
                scanned++
                val threadId = c.getLong(idxThread)
                val address = c.getString(idxAddr).orEmpty()
                val body = c.getString(idxBody).orEmpty()
                val date = c.getLong(idxDate)
                val read = c.getInt(idxRead)
                val type = c.getInt(idxType)

                val existing = byThread[threadId]
                if (existing == null) {
                    byThread[threadId] = Summary(address, body, date, 0)
                }
                // Non lu = message reçu (INBOX) non marqué lu.
                if (read == 0 && type == Telephony.Sms.MESSAGE_TYPE_INBOX) {
                    byThread[threadId]?.let { it.unread += 1 }
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
        return JSONObject().put("conversations", array)
    }

    /**
     * Messages d'une conversation, anciens → récents.
     *
     * Renvoie `{ "conversation_id": id, "messages": [ {body, timestamp,
     * outgoing}, … ] }`.
     */
    fun messages(context: Context, conversationId: String): JSONObject {
        val resolver = context.contentResolver
        val projection = arrayOf(
            Telephony.Sms.BODY,
            Telephony.Sms.DATE,
            Telephony.Sms.TYPE,
        )

        val array = JSONArray()
        resolver.query(
            Telephony.Sms.CONTENT_URI,
            projection,
            "${Telephony.Sms.THREAD_ID} = ?",
            arrayOf(conversationId),
            "${Telephony.Sms.DATE} ASC",
        )?.use { c ->
            val idxBody = c.getColumnIndexOrThrow(Telephony.Sms.BODY)
            val idxDate = c.getColumnIndexOrThrow(Telephony.Sms.DATE)
            val idxType = c.getColumnIndexOrThrow(Telephony.Sms.TYPE)
            while (c.moveToNext()) {
                array.put(
                    JSONObject()
                        .put("body", c.getString(idxBody).orEmpty())
                        .put("timestamp", c.getLong(idxDate))
                        .put("outgoing", isOutgoing(c.getInt(idxType)))
                )
            }
        }
        return JSONObject()
            .put("conversation_id", conversationId)
            .put("messages", array)
    }

    /** True pour les types « sortants » (envoyé / outbox / échec / file). */
    private fun isOutgoing(type: Int): Boolean = when (type) {
        Telephony.Sms.MESSAGE_TYPE_SENT,
        Telephony.Sms.MESSAGE_TYPE_OUTBOX,
        Telephony.Sms.MESSAGE_TYPE_FAILED,
        Telephony.Sms.MESSAGE_TYPE_QUEUED -> true
        else -> false
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
