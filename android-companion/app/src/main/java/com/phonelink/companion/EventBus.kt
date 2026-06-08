package com.phonelink.companion

import android.util.Log
import org.json.JSONArray
import org.json.JSONObject

/**
 * File d'événements en mémoire pour le temps réel côté Ubuntu (V0.9).
 *
 * Objectif : éviter que l'utilisateur doive cliquer sur « Rafraîchir » pour voir
 * un nouveau SMS/MMS/RCS ou une nouvelle notification Android. Le serveur expose
 * un endpoint de **long polling** `GET /v1/events` (cf. [CompanionServer]) qui
 * s'appuie sur cet objet.
 *
 * Modèle :
 *  - chaque événement porte un `id` incrémental, un `type`, un `timestamp` (ms)
 *    et un payload JSON minimal optionnel ;
 *  - les producteurs ([RcsNotificationListener], le ContentObserver SMS/MMS et le
 *    receiver batterie de [CompanionForegroundService]) appellent [emit] ;
 *  - le consommateur (client Ubuntu) appelle [poll] qui **attend** jusqu'à
 *    `timeoutMs` qu'un nouvel événement arrive, puis renvoie ce qui est dispo.
 *
 * Contraintes respectées :
 *  - aucune dépendance lourde (uniquement `wait/notify` de la JVM) ;
 *  - file **bornée** ([MAX_EVENTS]) : pas de fuite mémoire ;
 *  - un thread serveur bloqué l'est au plus `timeoutMs` (jamais indéfiniment) ;
 *  - thread-safe (toutes les sections critiques sont `synchronized(lock)`).
 *
 * Les événements sont volatiles (perdus au redémarrage du service) : c'est
 * voulu. Le client se resynchronise alors via les endpoints classiques
 * (`/v1/conversations`, `/v1/notifications`, `/v1/device/status`) puis repart de
 * `last_event_id`.
 */
object EventBus {

    private const val TAG = "EventBus"

    /** Nombre maximal d'événements conservés (les plus anciens sont purgés). */
    private const val MAX_EVENTS = 256

    /** Timeout de long polling par défaut si le client n'en fournit pas. */
    const val DEFAULT_TIMEOUT_MS = 25_000L

    /** Bornes raisonnables du timeout demandé par le client (20–30 s). */
    private const val MIN_TIMEOUT_MS = 1_000L
    private const val MAX_TIMEOUT_MS = 30_000L

    // Types d'événements (contrat partagé avec app/core/android_bridge.py).
    const val TYPE_NOTIFICATION_CHANGED = "notification_changed"
    const val TYPE_SMS_CHANGED = "sms_changed"
    const val TYPE_DEVICE_STATUS_CHANGED = "device_status_changed"

    private data class Event(
        val id: Long,
        val type: String,
        val timestamp: Long,
        val payload: JSONObject?,
    )

    private val lock = Object()
    private val events = ArrayDeque<Event>()
    private var lastId = 0L

    /**
     * Publie un nouvel événement et réveille les clients en attente.
     *
     * Ne lève jamais : un échec de publication ne doit pas casser un producteur
     * (notification listener, observer, receiver). Le `payload` reste minimal
     * (le client recharge ensuite les endpoints concernés).
     */
    fun emit(type: String, payload: JSONObject? = null) {
        try {
            synchronized(lock) {
                lastId += 1
                events.addLast(Event(lastId, type, System.currentTimeMillis(), payload))
                while (events.size > MAX_EVENTS) {
                    events.removeFirst()
                }
                lock.notifyAll()
            }
        } catch (e: Exception) {
            Log.w(TAG, "emit($type) échoué: ${e.message}")
        }
    }

    /**
     * Long polling : renvoie les événements d'`id` strictement supérieur à
     * [since]. S'il n'y en a aucun, **attend** jusqu'à `timeoutMs` (borné) qu'un
     * nouvel événement arrive, puis renvoie ce qui est disponible (possiblement
     * vide).
     *
     * Renvoie toujours un objet de la forme :
     * `{ "events": [ {id, type, timestamp, payload?} ], "last_event_id": N }`.
     *
     * @param since  dernier id connu du client ; `< 0` ⇒ resynchro initiale
     *               (renvoie une liste vide + l'`last_event_id` courant).
     * @param timeoutMs durée maximale d'attente (bornée à [MIN_TIMEOUT_MS]..[MAX_TIMEOUT_MS]).
     */
    fun poll(since: Long, timeoutMs: Long): JSONObject {
        val bounded = timeoutMs.coerceIn(MIN_TIMEOUT_MS, MAX_TIMEOUT_MS)
        synchronized(lock) {
            // Resynchro initiale : le client ne connaît pas encore d'id → on lui
            // donne un point de départ propre sans rejouer tout l'historique.
            if (since < 0) {
                return response(emptyList(), lastId)
            }

            var pending = collectSince(since)
            if (pending.isNotEmpty()) {
                return response(pending, lastId)
            }

            val deadline = System.currentTimeMillis() + bounded
            while (pending.isEmpty()) {
                val remaining = deadline - System.currentTimeMillis()
                if (remaining <= 0) break
                try {
                    lock.wait(remaining)
                } catch (e: InterruptedException) {
                    java.lang.Thread.currentThread().interrupt()
                    break
                }
                pending = collectSince(since)
            }
            return response(pending, lastId)
        }
    }

    /** Doit être appelé sous `synchronized(lock)`. */
    private fun collectSince(since: Long): List<Event> {
        if (events.isEmpty()) return emptyList()
        return events.filter { it.id > since }
    }

    private fun response(pending: List<Event>, lastEventId: Long): JSONObject {
        val arr = JSONArray()
        for (e in pending) {
            val obj = JSONObject()
                .put("id", e.id)
                .put("type", e.type)
                .put("timestamp", e.timestamp)
            e.payload?.let { obj.put("payload", it) }
            arr.put(obj)
        }
        return JSONObject()
            .put("events", arr)
            .put("last_event_id", lastEventId)
    }
}
