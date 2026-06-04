package com.phonelink.companion

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.phonelink.companion.databinding.ActivityMainBinding
import java.net.Inet4Address
import java.net.NetworkInterface

/**
 * Écran unique : démarrer/arrêter le serveur, afficher IP/port/PIN, gérer les
 * permissions SMS.
 *
 * Le serveur est lié au cycle de vie de l'activité (démo) : il s'arrête quand
 * l'activité est détruite. Un service de premier plan viendra plus tard.
 *
 * V0.5 : les permissions SMS (dangereuses) sont demandées à l'exécution. Sans
 * elles, le serveur fonctionne toujours mais sert les données de démo
 * ([DemoData]) et `/v1/health` renvoie `sms_permission=false`.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val pairing = PairingManager()
    private var server: CompanionServer? = null

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
        if (server != null) return
        val instance = CompanionServer(
            PORT,
            pairing,
            deviceName(),
            applicationContext,
            appVersion(),
        )
        try {
            instance.start(NanoHttpdTimeout, false)
            server = instance
        } catch (e: Exception) {
            toast(getString(R.string.start_error, e.message ?: ""))
        }
        render()
    }

    private fun stopServer() {
        server?.stop()
        server = null
        render()
    }

    override fun onResume() {
        super.onResume()
        render() // refléter une éventuelle révocation de permission depuis les réglages
    }

    override fun onDestroy() {
        stopServer()
        super.onDestroy()
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
        val running = server != null
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

        // Délai de lecture socket par défaut de NanoHTTPD (5 s).
        private const val NanoHttpdTimeout = 5_000
    }
}
