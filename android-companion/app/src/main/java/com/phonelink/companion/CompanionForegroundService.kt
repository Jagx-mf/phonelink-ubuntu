package com.phonelink.companion

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat

/**
 * Service de premier plan hébergeant [CompanionServer] (V0.7).
 *
 * Avant V0.7, le serveur NanoHTTPD était lié au cycle de vie de [MainActivity]
 * et s'arrêtait dès que l'activité était détruite. Ici, le serveur tourne dans
 * un Foreground Service : il **survit** à la fermeture ou à la mise en
 * arrière-plan de l'activité, et reste joignable par le client Ubuntu.
 *
 * Le service :
 *  - crée/gère l'unique instance [CompanionServer] (endpoints V0.6 inchangés) ;
 *  - affiche une notification persistante « PhoneLink Companion actif » ;
 *  - partage l'appairage via [PairingManager.shared] avec l'activité.
 *
 * Le contrat HTTP (health, pair, conversations, messages, send, rcs/messages,
 * et les endpoints debug) ainsi que le modèle provider-first SMS/MMS/RCS sont
 * **inchangés** : seul l'hébergement du serveur change.
 */
class CompanionForegroundService : Service() {

    private var server: CompanionServer? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopServerAndSelf()
            return START_NOT_STICKY
        }
        startInForeground()
        startServer()
        // START_STICKY : si le système tue le service, il le relance (intent
        // null) et le serveur redémarre. PIN/token sont alors régénérés
        // (état en mémoire — limite V0.7).
        return START_STICKY
    }

    private fun startInForeground() {
        val notification = buildNotification()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIF_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
        } else {
            startForeground(NOTIF_ID, notification)
        }
    }

    private fun startServer() {
        if (server != null) return
        val instance = CompanionServer(
            PORT,
            PairingManager.shared,
            deviceName(),
            applicationContext,
            appVersion(),
        )
        try {
            instance.start(NANO_HTTPD_TIMEOUT, false)
            server = instance
            isRunning = true
            Log.i(TAG, "CompanionServer démarré sur le port $PORT")
        } catch (e: Exception) {
            Log.e(TAG, "Échec du démarrage du serveur: ${e.message}")
            stopServerAndSelf()
        }
    }

    private fun stopServerAndSelf() {
        stopServerInstance()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun stopServerInstance() {
        server?.stop()
        server = null
        isRunning = false
        Log.i(TAG, "CompanionServer arrêté")
    }

    override fun onDestroy() {
        stopServerInstance()
        super.onDestroy()
    }

    // ---- notification ----------------------------------------------------

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.notif_channel_name),
            NotificationManager.IMPORTANCE_LOW, // discret : pas de son ni vibration
        ).apply {
            description = getString(R.string.notif_channel_desc)
        }
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(channel)
    }

    private fun buildNotification(): android.app.Notification {
        val piFlags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        } else {
            PendingIntent.FLAG_UPDATE_CURRENT
        }

        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
            },
            piFlags,
        )

        val stopIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, CompanionForegroundService::class.java).apply {
                action = ACTION_STOP
            },
            piFlags,
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.notif_title))
            .setContentText(getString(R.string.notif_text, PORT))
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
            .setOngoing(true)
            .setContentIntent(openIntent)
            .addAction(0, getString(R.string.notif_stop), stopIntent)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    // ---- helpers ---------------------------------------------------------

    private fun deviceName(): String =
        listOf(Build.MANUFACTURER, Build.MODEL)
            .filter { it.isNotBlank() }
            .joinToString(" ")
            .ifBlank { "Android" }

    private fun appVersion(): String =
        try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: ""
        } catch (e: Exception) {
            ""
        }

    companion object {
        private const val TAG = "CompanionFgService"
        private const val PORT = 8765

        // Délai de lecture socket par défaut de NanoHTTPD (5 s).
        private const val NANO_HTTPD_TIMEOUT = 5_000

        private const val NOTIF_ID = 1
        private const val CHANNEL_ID = "phonelink_companion_server"

        /** Action d'arrêt (bouton de la notification ou demande explicite). */
        const val ACTION_STOP = "com.phonelink.companion.action.STOP"

        /**
         * Vrai tant que le serveur est démarré. Lu par [MainActivity] pour
         * afficher le statut. Volatile : écrit par le service, lu par l'UI.
         */
        @Volatile
        var isRunning: Boolean = false
            private set
    }
}
