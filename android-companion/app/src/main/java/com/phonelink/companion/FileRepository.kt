package com.phonelink.companion

import android.content.Context
import android.media.MediaScannerConnection
import android.os.Build
import android.os.Environment
import android.util.Log
import android.webkit.MimeTypeMap
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.io.InputStream

/**
 * Explorateur de fichiers Android (V1.0 — Phase 1), exposé via les endpoints
 * `/v1/files` (roots, list, download, upload, mkdir, delete, rename).
 *
 * Périmètre volontairement restreint aux **dossiers publics** du stockage
 * partagé (Download, DCIM, Pictures, Movies, Music, Documents) :
 *  - pas de root, pas d'accès à `/data` ni au reste de `/storage` ;
 *  - chaque chemin reçu du client est canonicalisé puis vérifié comme étant
 *    **sous une racine autorisée** ([resolve]) — `..`, liens symboliques et
 *    chemins absolus hors racine sont refusés ;
 *  - toutes les méthodes attrapent leurs exceptions : une erreur de fichier ne
 *    doit jamais faire tomber le Foreground Service.
 *
 * Permissions :
 *  - Android ≤ 9 : READ/WRITE_EXTERNAL_STORAGE (runtime) ;
 *  - Android 10 : `requestLegacyExternalStorage` (manifest) + READ/WRITE ;
 *  - Android 11+ : « Accès à tous les fichiers » (MANAGE_EXTERNAL_STORAGE),
 *    accordé par l'utilisateur via les réglages (bouton dans [MainActivity]).
 *    Sans cet accès, [hasFullAccess] est faux et les endpoints renvoient
 *    `files_permission_missing` (l'UI Ubuntu affiche un message clair).
 */
object FileRepository {

    private const val TAG = "FileRepository"

    /** Racines publiques exposées (nom affiché → dossier standard Android). */
    private val ROOT_TYPES = linkedMapOf(
        "Download" to Environment.DIRECTORY_DOWNLOADS,
        "DCIM" to Environment.DIRECTORY_DCIM,
        "Pictures" to Environment.DIRECTORY_PICTURES,
        "Movies" to Environment.DIRECTORY_MOVIES,
        "Music" to Environment.DIRECTORY_MUSIC,
        "Documents" to Environment.DIRECTORY_DOCUMENTS,
    )

    // ---- permissions -------------------------------------------------------

    /** Vrai si la lecture/écriture réelle des dossiers publics est possible. */
    fun hasFullAccess(context: Context): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else {
            androidx.core.content.ContextCompat.checkSelfPermission(
                context, android.Manifest.permission.READ_EXTERNAL_STORAGE
            ) == android.content.pm.PackageManager.PERMISSION_GRANTED
        }
    }

    // ---- racines & résolution sécurisée -----------------------------------

    /** Dossiers racines autorisés et existants. */
    fun rootDirs(): List<Pair<String, File>> =
        ROOT_TYPES.mapNotNull { (name, type) ->
            try {
                val dir = Environment.getExternalStoragePublicDirectory(type)
                if (dir != null && dir.isDirectory) name to dir else null
            } catch (e: Exception) {
                null
            }
        }

    /**
     * Canonicalise [rawPath] et vérifie qu'il est **sous une racine autorisée**.
     * Renvoie `null` pour tout chemin vide, contenant `..`, ou sortant des
     * racines (y compris via lien symbolique, grâce à la canonicalisation).
     */
    fun resolve(rawPath: String?): File? {
        val path = rawPath?.trim().orEmpty()
        if (path.isEmpty() || path.contains("..")) return null
        return try {
            val canonical = File(path).canonicalFile
            val inRoot = rootDirs().any { (_, root) ->
                val rootPath = root.canonicalPath
                canonical.path == rootPath || canonical.path.startsWith(rootPath + File.separator)
            }
            if (inRoot) canonical else null
        } catch (e: IOException) {
            null
        }
    }

    // ---- endpoints (JSON) --------------------------------------------------

    /** `GET /v1/files/roots` → `{ "roots": [ {name, path, is_dir:true}, … ] }`. */
    fun roots(): JSONObject {
        val array = JSONArray()
        for ((name, dir) in rootDirs()) {
            array.put(
                JSONObject()
                    .put("name", name)
                    .put("path", dir.absolutePath)
                    .put("is_dir", true)
                    .put("size", 0L)
                    .put("modified", dir.lastModified())
            )
        }
        return JSONObject().put("roots", array)
    }

    /**
     * `GET /v1/files/list?path=…` →
     * `{ "path", "parent", "items": [ {name, path, is_dir, size, modified, mime} ] }`.
     * `parent` est vide quand on est à la racine d'un dossier autorisé (le
     * client revient alors à la liste des racines).
     */
    fun list(dir: File): JSONObject {
        val items = JSONArray()
        val children = dir.listFiles()?.sortedWith(
            compareByDescending<File> { it.isDirectory }.thenBy { it.name.lowercase() }
        ) ?: emptyList()
        for (child in children) {
            items.put(entry(child))
        }
        val parent = dir.parentFile?.let { p -> if (resolve(p.path) != null) p.absolutePath else "" }
        return JSONObject()
            .put("path", dir.absolutePath)
            .put("parent", parent ?: "")
            .put("items", items)
    }

    fun entry(file: File): JSONObject =
        JSONObject()
            .put("name", file.name)
            .put("path", file.absolutePath)
            .put("is_dir", file.isDirectory)
            .put("size", if (file.isFile) file.length() else 0L)
            .put("modified", file.lastModified())
            .put("mime", if (file.isDirectory) "" else mimeOf(file.name))

    fun mimeOf(name: String): String {
        val ext = name.substringAfterLast('.', "").lowercase()
        if (ext.isEmpty()) return "application/octet-stream"
        return MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext)
            ?: "application/octet-stream"
    }

    /** `POST /v1/files/mkdir {path, name}` — crée `path/name`. */
    fun mkdir(parent: File, name: String?): JSONObject {
        val safeName = sanitizeName(name)
            ?: return error("invalid_name")
        if (!parent.isDirectory) return error("not_a_directory")
        val target = File(parent, safeName)
        return try {
            when {
                target.exists() -> error("already_exists")
                target.mkdirs() -> JSONObject().put("ok", true).put("item", entry(target))
                else -> error("mkdir_failed")
            }
        } catch (e: Exception) {
            Log.w(TAG, "mkdir échoué: ${e.message}")
            error("mkdir_failed")
        }
    }

    /**
     * `POST /v1/files/delete {path}` — supprime un fichier ou un dossier
     * (récursivement). Le chemin a déjà été validé sous une racine ; une racine
     * elle-même n'est jamais supprimable.
     */
    fun delete(context: Context, target: File): JSONObject {
        if (isRoot(target)) return error("cannot_delete_root")
        return try {
            val ok = target.deleteRecursively()
            if (ok) {
                scan(context, target)
                JSONObject().put("ok", true)
            } else {
                error("delete_failed")
            }
        } catch (e: Exception) {
            Log.w(TAG, "delete échoué: ${e.message}")
            error("delete_failed")
        }
    }

    /**
     * `POST /v1/files/rename {path, new_name}` — renomme dans le **même
     * dossier** (pas de déplacement inter-racines).
     */
    fun rename(context: Context, source: File, newName: String?): JSONObject {
        if (isRoot(source)) return error("cannot_rename_root")
        val safeName = sanitizeName(newName) ?: return error("invalid_name")
        val target = File(source.parentFile, safeName)
        if (resolve(target.path) == null) return error("forbidden_path")
        return try {
            when {
                !source.exists() -> error("not_found")
                target.exists() -> error("already_exists")
                source.renameTo(target) -> {
                    scan(context, source)
                    scan(context, target)
                    JSONObject().put("ok", true).put("item", entry(target))
                }
                else -> error("rename_failed")
            }
        } catch (e: Exception) {
            Log.w(TAG, "rename échoué: ${e.message}")
            error("rename_failed")
        }
    }

    /**
     * `POST /v1/files/upload?path=<dossier>&name=<fichier>` — corps brut
     * (octet-stream) copié en streaming vers `path/name`. Refuse d'écraser un
     * fichier existant (le client renomme d'abord s'il le veut vraiment).
     */
    fun upload(
        context: Context,
        dir: File,
        name: String?,
        input: InputStream,
        contentLength: Long,
    ): JSONObject {
        val safeName = sanitizeName(name) ?: return error("invalid_name")
        if (!dir.isDirectory) return error("not_a_directory")
        val target = File(dir, safeName)
        if (target.exists()) return error("already_exists")
        return try {
            target.outputStream().use { out ->
                val buffer = ByteArray(64 * 1024)
                var remaining = contentLength
                while (remaining > 0) {
                    val read = input.read(buffer, 0, minOf(buffer.size.toLong(), remaining).toInt())
                    if (read < 0) break
                    out.write(buffer, 0, read)
                    remaining -= read
                }
            }
            scan(context, target)
            JSONObject().put("ok", true).put("item", entry(target))
        } catch (e: Exception) {
            Log.w(TAG, "upload échoué: ${e.message}")
            try {
                target.delete() // ne pas laisser un fichier partiel
            } catch (ignored: Exception) {
            }
            error("upload_failed")
        }
    }

    // ---- helpers -----------------------------------------------------------

    private fun isRoot(file: File): Boolean =
        rootDirs().any { (_, root) ->
            try {
                root.canonicalPath == file.canonicalPath
            } catch (e: IOException) {
                false
            }
        }

    /** Nom de fichier simple : non vide, sans séparateur ni `..`. */
    private fun sanitizeName(name: String?): String? {
        val trimmed = name?.trim().orEmpty()
        if (trimmed.isEmpty() || trimmed == "." || trimmed == "..") return null
        if (trimmed.contains('/') || trimmed.contains('\\') || trimmed.contains('\u0000')) return null
        return trimmed
    }

    /** Signale le fichier au MediaStore (galerie/téléchargements). Best-effort. */
    private fun scan(context: Context, file: File) {
        try {
            MediaScannerConnection.scanFile(
                context, arrayOf(file.absolutePath), null, null
            )
        } catch (e: Exception) {
            // best-effort : l'indexation média n'est jamais bloquante
        }
    }

    private fun error(code: String): JSONObject =
        JSONObject().put("ok", false).put("error", code)
}
