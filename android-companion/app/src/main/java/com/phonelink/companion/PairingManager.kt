package com.phonelink.companion

import android.util.Base64
import java.security.SecureRandom

/**
 * Appairage par PIN → token (cf. docs/android-backend-v0.4.md §5).
 *
 * - Un PIN à 6 chiffres est affiché dans l'app ; le client Ubuntu le poste sur
 *   `/v1/pair` pour obtenir un token Bearer opaque.
 * - Le PIN est à **usage unique** : il est régénéré après un appairage réussi.
 * - L'état tient en mémoire (démo) : tout est perdu au redémarrage de l'app.
 */
class PairingManager {

    private val random = SecureRandom()

    @Volatile
    var pin: String = generatePin()
        private set

    @Volatile
    var token: String? = null
        private set

    val isPaired: Boolean
        get() = token != null

    /** Régénère et renvoie un nouveau PIN (bouton « Nouveau PIN »). */
    @Synchronized
    fun regeneratePin(): String {
        pin = generatePin()
        return pin
    }

    /**
     * Vérifie le PIN reçu ; si correct, émet et mémorise un token, puis
     * régénère le PIN (usage unique). Renvoie le token, ou `null` si le PIN
     * est invalide.
     */
    @Synchronized
    fun verifyPinAndIssueToken(candidate: String?): String? {
        if (candidate.isNullOrEmpty() || candidate != pin) return null
        val issued = generateToken()
        token = issued
        pin = generatePin()
        return issued
    }

    /** True si le token fourni correspond au token émis. */
    fun isValidToken(candidate: String?): Boolean {
        val current = token ?: return false
        return !candidate.isNullOrEmpty() && candidate == current
    }

    private fun generatePin(): String = "%06d".format(random.nextInt(1_000_000))

    private fun generateToken(): String {
        val bytes = ByteArray(32)
        random.nextBytes(bytes)
        return Base64.encodeToString(
            bytes,
            Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING,
        )
    }
}
