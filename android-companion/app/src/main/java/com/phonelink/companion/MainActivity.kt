package com.phonelink.companion

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.phonelink.companion.databinding.ActivityMainBinding
import java.net.Inet4Address
import java.net.NetworkInterface

/**
 * Écran unique : démarrer/arrêter le serveur, afficher IP/port/PIN, gérer les
 * permissions SMS.
 *
 * V0.7 : le serveur n'est plus lié au cycle de vie de l'activité. Il est
 * hébergé par [CompanionForegroundService] et **survit** donc à la fermeture ou
 * à la mise en arrière-plan de l'activité. Les boutons « Démarrer/Arrêter »
 * pilotent le service ; l'activité ne fait plus qu'afficher l'état (PIN partagé
 * via [PairingManager.shared]).
 *
 * V0.5 : les permissions SMS (dangereuses) sont demandées à l'exécution. Sans
 * elles, le serveur fonctionne toujours mais sert les données de démo
 * ([DemoData]) et `/v1/health` renvoie `sms_permission=false`.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val pairing = PairingManager.shared

    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
            render()
            val granted = SmsRepository.hasReadSms(this) && SmsRepository.hasSendSms(this)
            toast(
                getString(
                    if (granted) R.string.sms_granted else R.string.sms_denied
                )
            )
        }

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) {
            // Que la permission soit accordée ou non, le serveur tourne ; seule
            // la notification persistante peut ne pas s'afficher si refusée.
            render()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.btnStart.setOnClickListener { startServer() }
        binding.btnStop.setOnClickListener { stopServer() }
        binding.btnRegeneratePin.setOnClickListener {
            pairing.regeneratePin()
            render()
            toast(getString(R.string.pin_regenerated))
        }
        binding.btnRequestSms.setOnClickListener { requestSmsPermissions() }
        binding.btnNotifAccess.setOnClickListener { openNotificationAccessSettings() }

        render()
    }

    private fun startServer() {
        ensureNotificationPermission()
        try {
            ContextCompat.startForegroundService(this, serviceIntent())
        } catch (e: Exception) {
            toast(getString(R.string.start_error, e.message ?: ""))
        }
        scheduleRender()
    }

    private fun stopServer() {
        // Arrête le serveur ET le service ; onDestroy du service ferme NanoHTTPD.
        stopService(serviceIntent())
        scheduleRender()
    }

    private fun serviceIntent(): Intent =
        Intent(this, CompanionForegroundService::class.java)

    /**
     * Le service démarre/s'arrête de façon asynchrone : on rafraîchit tout de
     * suite puis à nouveau peu après pour refléter l'état réel du service.
     */
    private fun scheduleRender() {
        render()
        binding.root.postDelayed({ render() }, 250)
    }

    private fun ensureNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    override fun onResume() {
        super.onResume()
        render() // refléter l'état du service et une éventuelle révocation de permission
    }

    private fun requestSmsPermissions() {
        val permissions = mutableListOf(
            Manifest.permission.READ_SMS,
            Manifest.permission.SEND_SMS,
            Manifest.permission.RECEIVE_SMS,
            Manifest.permission.READ_CONTACTS,
        )
        permissionLauncher.launch(permissions.toTypedArray())
    }

    private fun render() {
        val running = CompanionForegroundService.isRunning
        binding.txtStatus.text = getString(
            if (running) R.string.status_running else R.string.status_stopped
        )
        binding.txtIp.text = localIpAddress() ?: getString(R.string.ip_unavailable)
        binding.txtPort.text = PORT.toString()
        binding.txtPin.text = pairing.pin
        binding.txtPaired.text = getString(
            if (pairing.isPaired) R.string.paired_yes else R.string.paired_no
        )

        val smsOk = SmsRepository.hasReadSms(this) && SmsRepository.hasSendSms(this)
        binding.txtSms.text = getString(
            if (smsOk) R.string.sms_mode_real else R.string.sms_mode_demo
        )
        binding.btnRequestSms.isEnabled = !smsOk

        val rcsOk = RcsNotificationListener.hasAccess(this)
        binding.txtRcs.text = getString(
            if (rcsOk) R.string.rcs_access_on else R.string.rcs_access_off
        )
        binding.btnNotifAccess.isEnabled = !rcsOk

        binding.btnStart.isEnabled = !running
        binding.btnStop.isEnabled = running
    }

    private fun openNotificationAccessSettings() {
        // Pas de permission runtime : on ouvre le réglage système dédié.
        try {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        } catch (e: Exception) {
            toast(getString(R.string.start_error, e.message ?: ""))
        }
    }

    /** Première adresse IPv4 non-loopback (Wi-Fi/LAN), ou null. */
    private fun localIpAddress(): String? {
        return try {
            NetworkInterface.getNetworkInterfaces().asSequence()
                .filter { it.isUp && !it.isLoopback }
                .flatMap { it.inetAddresses.asSequence() }
                .filterIsInstance<Inet4Address>()
                .firstOrNull { !it.isLoopbackAddress }
                ?.hostAddress
        } catch (e: Exception) {
            null
        }
    }

    private fun toast(message: String) =
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()

    companion object {
        private const val PORT = 8765
    }
}
