package com.phonelink.companion

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.ContactsContract
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject

/**
 * Contacts Android (V1.0 — Phase 2), exposés via `/v1/contacts`.
 *
 * Lecture seule du carnet d'adresses (READ_CONTACTS, déjà demandée par
 * [MainActivity] avec les permissions SMS). Aucune écriture, aucune photo
 * transférée (seul `photo_available` est renvoyé).
 *
 * `/v1/call/start` ouvre le **dialer** Android ([Intent.ACTION_DIAL]) avec le
 * numéro prérempli : l'utilisateur confirme l'appel sur le téléphone. On
 * n'utilise jamais ACTION_CALL (pas de permission CALL_PHONE, pas d'appel
 * déclenché à distance sans confirmation). Limite documentée : sur Android 10+,
 * une app en arrière-plan peut être empêchée d'ouvrir une activité ; le dialer
 * s'ouvre de façon fiable quand l'écran du téléphone est allumé/déverrouillé.
 * L'audio de l'appel côté Ubuntu dépendra du Bluetooth HFP (hors scope ici).
 */
object ContactsRepository {

    private const val TAG = "ContactsRepository"

    /** Nombre maximal de contacts renvoyés (garde-fou mémoire/JSON). */
    private const val MAX_CONTACTS = 2000

    fun hasReadContacts(context: Context): Boolean =
        SmsRepository.hasReadContacts(context)

    /**
     * `GET /v1/contacts[?q=…]` →
     * `{ "contacts": [ {id, display_name, phones[], emails[], photo_available} ] }`.
     *
     * Le filtre [query] est appliqué côté Kotlin (insensible à la casse) sur le
     * nom et les numéros — la base contacts locale reste de taille raisonnable.
     */
    fun contacts(context: Context, query: String? = null): JSONObject {
        data class Entry(
            val id: String,
            var name: String,
            val phones: LinkedHashSet<String> = LinkedHashSet(),
            val emails: LinkedHashSet<String> = LinkedHashSet(),
            var photo: Boolean = false,
        )

        val byId = LinkedHashMap<String, Entry>()
        val resolver = context.contentResolver

        // 1) Numéros de téléphone (la plupart des contacts utiles en ont un).
        try {
            resolver.query(
                ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                arrayOf(
                    ContactsContract.CommonDataKinds.Phone.CONTACT_ID,
                    ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                    ContactsContract.CommonDataKinds.Phone.NUMBER,
                    ContactsContract.CommonDataKinds.Phone.PHOTO_URI,
                ),
                null,
                null,
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME + " COLLATE NOCASE ASC",
            )?.use { c ->
                val idxId = c.getColumnIndexOrThrow(
                    ContactsContract.CommonDataKinds.Phone.CONTACT_ID
                )
                val idxName = c.getColumnIndexOrThrow(
                    ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME
                )
                val idxNumber = c.getColumnIndexOrThrow(
                    ContactsContract.CommonDataKinds.Phone.NUMBER
                )
                val idxPhoto = c.getColumnIndexOrThrow(
                    ContactsContract.CommonDataKinds.Phone.PHOTO_URI
                )
                while (c.moveToNext() && byId.size < MAX_CONTACTS) {
                    val id = c.getLong(idxId).toString()
                    val entry = byId.getOrPut(id) {
                        Entry(id = id, name = c.getString(idxName).orEmpty())
                    }
                    c.getString(idxNumber)?.trim()?.takeIf { it.isNotEmpty() }
                        ?.let { entry.phones.add(it) }
                    if (!c.getString(idxPhoto).isNullOrEmpty()) entry.photo = true
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "lecture des numéros échouée: ${e.message}")
        }

        // 2) Emails (complète les contacts déjà vus, n'ajoute pas de contact
        //    sans téléphone : l'usage PhoneLink est SMS/appel d'abord).
        try {
            resolver.query(
                ContactsContract.CommonDataKinds.Email.CONTENT_URI,
                arrayOf(
                    ContactsContract.CommonDataKinds.Email.CONTACT_ID,
                    ContactsContract.CommonDataKinds.Email.ADDRESS,
                ),
                null,
                null,
                null,
            )?.use { c ->
                val idxId = c.getColumnIndexOrThrow(
                    ContactsContract.CommonDataKinds.Email.CONTACT_ID
                )
                val idxAddr = c.getColumnIndexOrThrow(
                    ContactsContract.CommonDataKinds.Email.ADDRESS
                )
                while (c.moveToNext()) {
                    val entry = byId[c.getLong(idxId).toString()] ?: continue
                    c.getString(idxAddr)?.trim()?.takeIf { it.isNotEmpty() }
                        ?.let { entry.emails.add(it) }
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "lecture des emails échouée: ${e.message}")
        }

        val needle = query?.trim()?.lowercase().orEmpty()
        val array = JSONArray()
        for (entry in byId.values) {
            if (needle.isNotEmpty()) {
                val haystack = (entry.name + " " + entry.phones.joinToString(" ")).lowercase()
                if (!haystack.contains(needle)) continue
            }
            array.put(
                JSONObject()
                    .put("id", entry.id)
                    .put("display_name", entry.name)
                    .put("phones", JSONArray(entry.phones.toList()))
                    .put("emails", JSONArray(entry.emails.toList()))
                    .put("photo_available", entry.photo)
            )
        }
        return JSONObject().put("contacts", array)
    }

    /**
     * `POST /v1/call/start {phone_number}` — ouvre le dialer du téléphone avec
     * le numéro prérempli (ACTION_DIAL : aucune permission, aucun appel lancé
     * sans confirmation de l'utilisateur sur le téléphone).
     */
    fun startDial(context: Context, phoneNumber: String?): JSONObject {
        val number = phoneNumber?.trim().orEmpty()
        if (number.isEmpty()) {
            return JSONObject().put("ok", false).put("error", "invalid_number")
        }
        return try {
            val intent = Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + Uri.encode(number)))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
            Log.i(TAG, "Dialer ouvert pour $number")
            JSONObject().put("ok", true).put("detail", "dialer_opened")
        } catch (e: Exception) {
            Log.w(TAG, "ouverture du dialer échouée: ${e.message}")
            JSONObject().put("ok", false).put("error", "dial_failed")
        }
    }
}
