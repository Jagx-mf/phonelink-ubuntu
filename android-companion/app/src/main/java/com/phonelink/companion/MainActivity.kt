package com.phonelink.companion

import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.phonelink.companion.databinding.ActivityMainBinding
import java.net.Inet4Address
import java.net.NetworkInterface

/**
 * Écran unique : démarrer/arrêter le serveur, afficher IP/port/PIN.
 *
 * Le serveur est lié au cycle de vie de l'activité (démo) : il s'arrête quand
 * l'activité est détruite. Un service de premier plan viendra plus tard.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val pairing = PairingManager()
    private var server: CompanionServer? = null

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

        render()
    }

    private fun startServer() {
        if (server != null) return
        val instance = CompanionServer(PORT, pairing, deviceName())
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

    override fun onDestroy() {
        stopServer()
        super.onDestroy()
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
        binding.btnStart.isEnabled = !running
        binding.btnStop.isEnabled = running
    }

    private fun deviceName(): String =
        listOf(Build.MANUFACTURER, Build.MODEL)
            .filter { it.isNotBlank() }
            .joinToString(" ")
            .ifBlank { "Android" }

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
