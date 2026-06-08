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
 *
 * V0.7 : l'activité et le [CompanionForegroundService] vivent dans le même
 * processus mais sont deux composants distincts. Ils partagent donc une unique
 * instance via [PairingManager.shared] pour que le PIN affiché par l'UI et le
 * token vérifié par le serveur soient bien les mêmes. Limite assumée pour V0.7 :
 * PIN/token restent **en mémoire** ; ils sont perdus si le processus est tué
 * (kill système ou réinstallation). La persistance est repoussée à plus tard.
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

    companion object {
        /**
         * Instance unique partagée par l'activité (affichage du PIN) et le
         * service de premier plan (vérification du token côté serveur HTTP).
         * Les deux composants tournent dans le même processus : une seule
         * instance suffit et garantit la cohérence PIN/token. État en mémoire.
         */
        val shared: PairingManager by lazy { PairingManager() }
    }
}
