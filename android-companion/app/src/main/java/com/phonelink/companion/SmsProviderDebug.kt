package com.phonelink.companion

import android.content.Context
import android.database.Cursor
import android.net.Uri
import android.provider.Telephony
import org.json.JSONArray
import org.json.JSONObject

/**
 * Diagnostic brut des providers SMS/MMS Android, pour comparer PhoneLink avec
 * les chemins utilisés par KDE Connect sans changer le repository SMS normal.
 */
object SmsProviderDebug {

    private const val MAX_SCAN_ROWS = 5000
    private const val MAX_LATEST_ROWS = 25

    private val interestingColumns = listOf(
        "_id",
        "thread_id",
        "address",
        "recipient_ids",
        "body",
        "snippet",
        "text",
        "sub",
        "subject",
        "date",
        "date_sent",
        "type",
        "transport_type",
        "msg_box",
        "m_type",
        "read",
        "status",
        "ct_t",
        "m_id",
        "tr_id",
    )

    private val timestampColumns = listOf(
        "date",
        "date_sent",
        "timestamp",
        "normalized_date",
    )

    fun dump(context: Context, address: String?): JSONObject {
        val targetAddress = address?.trim().orEmpty()
        val sources = JSONArray()
        val threadIds = LinkedHashSet<Long>()
        val hasReadSms = SmsRepository.hasReadSms(context)

        val root = JSONObject()
            .put("status", if (hasReadSms) "ok" else "missing_read_sms_permission")
            .put("address", targetAddress)
            .put("read_sms_permission", hasReadSms)
            .put("kde_connect_sms_path", "Telephony + content://mms-sms")
            .put("kde_connect_notification_path", "getActiveNotifications() + MessagingStyle")
            .put("sources", sources)

        if (!hasReadSms) {
            return root.put("error", "permission READ_SMS manquante")
        }

        sources.put(
            querySource(
                context = context,
                name = "Telephony.Sms",
                uri = Telephony.Sms.CONTENT_URI,
                address = targetAddress,
                threadIds = emptySet(),
                mode = FilterMode.ADDRESS,
                fallbackIdIsThreadId = false,
                collectThreadIdsInto = threadIds,
            )
        )

        sources.put(
            querySource(
                context = context,
                name = "Telephony.Threads.CONTENT_URI",
                uri = Telephony.Threads.CONTENT_URI,
                address = targetAddress,
                threadIds = threadIds,
                mode = FilterMode.THREAD_ID,
                fallbackIdIsThreadId = true,
                collectThreadIdsInto = threadIds,
            )
        )

        sources.put(
            querySource(
                context = context,
                name = "content://mms-sms/conversations",
                uri = Uri.parse("content://mms-sms/conversations"),
                address = targetAddress,
                threadIds = threadIds,
                mode = FilterMode.THREAD_ID,
                fallbackIdIsThreadId = true,
                collectThreadIdsInto = threadIds,
            )
        )

        threadIds.toList().forEach { threadId ->
            sources.put(
                querySource(
                    context = context,
                    name = "content://mms-sms/conversations/<thread_id>",
                    uri = Uri.parse("content://mms-sms/conversations/$threadId"),
                    address = targetAddress,
                    threadIds = setOf(threadId),
                    mode = FilterMode.NONE,
                    fallbackIdIsThreadId = false,
                    collectThreadIdsInto = threadIds,
                )
            )
        }

        sources.put(
            querySource(
                context = context,
                name = "content://mms-sms/complete-conversations",
                uri = Uri.parse("content://mms-sms/complete-conversations"),
                address = targetAddress,
                threadIds = threadIds,
                mode = FilterMode.THREAD_ID,
                fallbackIdIsThreadId = false,
                collectThreadIdsInto = threadIds,
            )
        )

        return root
            .put("thread_ids", JSONArray(threadIds.toList()))
            .put("source_count", sources.length())
    }

    private enum class FilterMode {
        NONE,
        ADDRESS,
        THREAD_ID,
    }

    private data class RowDebug(
        val timestamp: Long?,
        val json: JSONObject,
    )

    private fun querySource(
        context: Context,
        name: String,
        uri: Uri,
        address: String,
        threadIds: Set<Long>,
        mode: FilterMode,
        fallbackIdIsThreadId: Boolean,
        collectThreadIdsInto: MutableSet<Long>,
    ): JSONObject {
        val out = JSONObject()
            .put("name", name)
            .put("uri", uri.toString())
            .put("filter_mode", mode.name.lowercase())
            .put("filter_address", address)
            .put("filter_thread_ids", JSONArray(threadIds.toList()))

        return try {
            val query = queryCursor(context, uri, out)
            val cursor = query.cursor
                ?: return out.put("status", "null_cursor")
            cursor.use { c ->
                readCursor(
                    cursor = c,
                    out = out,
                    address = address,
                    threadIds = threadIds,
                    mode = mode,
                    fallbackIdIsThreadId = fallbackIdIsThreadId,
                    collectThreadIdsInto = collectThreadIdsInto,
                )
            }
        } catch (e: Exception) {
            out
                .put("status", "error")
                .put("error", e.javaClass.simpleName)
                .put("message", e.message ?: "")
        }
    }

    private data class QueryResult(
        val cursor: Cursor?,
    )

    private fun queryCursor(context: Context, uri: Uri, out: JSONObject): QueryResult {
        return try {
            out.put("sort_order", "date DESC")
            QueryResult(context.contentResolver.query(uri, null, null, null, "date DESC"))
        } catch (e: Exception) {
            out
                .put("sort_order", JSONObject.NULL)
                .put("sort_fallback_error_type", e.javaClass.simpleName)
                .put("sort_fallback_error", e.message ?: "")
            QueryResult(context.contentResolver.query(uri, null, null, null, null))
        }
    }

    private fun readCursor(
        cursor: Cursor,
        out: JSONObject,
        address: String,
        threadIds: Set<Long>,
        mode: FilterMode,
        fallbackIdIsThreadId: Boolean,
        collectThreadIdsInto: MutableSet<Long>,
    ): JSONObject {
        val columns = cursor.columnNames.toList()
        val latest = ArrayList<RowDebug>()
        val sourceThreadIds = LinkedHashSet<Long>()
        var scannedRows = 0
        var matchedRows = 0
        var minTimestamp: Long? = null
        var maxTimestamp: Long? = null

        while (cursor.moveToNext() && scannedRows < MAX_SCAN_ROWS) {
            scannedRows++
            val rowThreadId = rowThreadId(cursor, fallbackIdIsThreadId)
            if (!matches(cursor, address, threadIds, mode, rowThreadId)) continue
            matchedRows++
            rowThreadId?.let {
                sourceThreadIds.add(it)
                collectThreadIdsInto.add(it)
            }

            val timestamp = rowTimestamp(cursor)
            if (timestamp != null) {
                minTimestamp = minOf(minTimestamp ?: timestamp, timestamp)
                maxTimestamp = maxOf(maxTimestamp ?: timestamp, timestamp)
            }
            latest.add(RowDebug(timestamp, rowJson(cursor, timestamp)))
        }

        val latestRows = JSONArray()
        latest
            .sortedWith(compareByDescending<RowDebug> { it.timestamp ?: Long.MIN_VALUE })
            .take(MAX_LATEST_ROWS)
            .forEach { latestRows.put(it.json) }

        return out
            .put("status", "ok")
            .put("columns", JSONArray(columns))
            .put("provider_row_count", safeCount(cursor))
            .put("scanned_rows", scannedRows)
            .put("scan_limit", MAX_SCAN_ROWS)
            .put("scan_truncated", scannedRows >= MAX_SCAN_ROWS)
            .put("row_count", matchedRows)
            .put("min_timestamp", minTimestamp ?: JSONObject.NULL)
            .put("max_timestamp", maxTimestamp ?: JSONObject.NULL)
            .put("thread_ids", JSONArray(sourceThreadIds.toList()))
            .put("latest_messages", latestRows)
    }

    private fun matches(
        cursor: Cursor,
        address: String,
        threadIds: Set<Long>,
        mode: FilterMode,
        rowThreadId: Long?,
    ): Boolean {
        return when (mode) {
            FilterMode.NONE -> true
            FilterMode.ADDRESS -> {
                if (address.isBlank()) true else matchesAddress(columnString(cursor, "address"), address)
            }
            FilterMode.THREAD_ID -> {
                if (threadIds.isEmpty()) true else rowThreadId != null && threadIds.contains(rowThreadId)
            }
        }
    }

    private fun rowJson(cursor: Cursor, timestamp: Long?): JSONObject {
        val row = JSONObject()
            .put("timestamp", timestamp ?: JSONObject.NULL)
        interestingColumns.forEach { column ->
            val idx = cursor.getColumnIndex(column)
            if (idx >= 0) row.put(column, cursorValue(cursor, idx))
        }
        return row
    }

    private fun rowTimestamp(cursor: Cursor): Long? {
        timestampColumns.forEach { column ->
            val idx = cursor.getColumnIndex(column)
            if (idx >= 0 && !cursor.isNull(idx)) {
                val raw = runCatching { cursor.getLong(idx) }.getOrNull()
                if (raw != null && raw > 0L) return normalizeTimestamp(raw)
            }
        }
        return null
    }

    private fun rowThreadId(cursor: Cursor, fallbackIdIsThreadId: Boolean): Long? {
        val threadIndex = cursor.getColumnIndex("thread_id")
        if (threadIndex >= 0 && !cursor.isNull(threadIndex)) {
            return runCatching { cursor.getLong(threadIndex) }.getOrNull()
        }
        if (fallbackIdIsThreadId) {
            val idIndex = cursor.getColumnIndex("_id")
            if (idIndex >= 0 && !cursor.isNull(idIndex)) {
                return runCatching { cursor.getLong(idIndex) }.getOrNull()
            }
        }
        return null
    }

    private fun columnString(cursor: Cursor, column: String): String {
        val idx = cursor.getColumnIndex(column)
        if (idx < 0 || cursor.isNull(idx)) return ""
        return runCatching { cursor.getString(idx) }.getOrNull().orEmpty()
    }

    private fun cursorValue(cursor: Cursor, index: Int): Any {
        if (cursor.isNull(index)) return JSONObject.NULL
        return when (cursor.getType(index)) {
            Cursor.FIELD_TYPE_INTEGER -> cursor.getLong(index)
            Cursor.FIELD_TYPE_FLOAT -> cursor.getDouble(index)
            Cursor.FIELD_TYPE_BLOB -> "<blob ${cursor.getBlob(index)?.size ?: 0} bytes>"
            else -> cursor.getString(index)?.let { trimValue(it) } ?: JSONObject.NULL
        }
    }

    private fun safeCount(cursor: Cursor): Any =
        runCatching { cursor.count }.getOrNull() ?: JSONObject.NULL

    private fun normalizeTimestamp(raw: Long): Long =
        if (raw in 1L..9_999_999_999L) raw * 1000L else raw

    private fun matchesAddress(actual: String, expected: String): Boolean {
        if (actual == expected) return true
        val a = normalizePhone(actual)
        val b = normalizePhone(expected)
        if (a.isBlank() || b.isBlank()) return false
        if (a == b) return true
        if (a.length >= 9 && b.length >= 9 && a.takeLast(9) == b.takeLast(9)) {
            return true
        }
        val minComparable = 7
        return (a.length >= minComparable && b.endsWith(a)) ||
            (b.length >= minComparable && a.endsWith(b))
    }

    private fun normalizePhone(value: String): String =
        value.filter { it.isDigit() }

    private fun trimValue(value: String): String =
        if (value.length <= 1000) value else value.take(1000) + "..."
}
