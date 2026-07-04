/*
 * Copyright: Ankitects Pty Ltd and contributors
 * License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
 */

package com.ichi2.anki.speedrun

import android.content.Context
import anki.speedrun.concept
import anki.speedrun.transferReviewProto
import net.ankiweb.rsdroid.Backend
import org.json.JSONArray
import org.json.JSONObject
import timber.log.Timber
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL

/**
 * Syncs the Speedrun transfer-review log (the T/G data) with the transfer-sync
 * server.
 *
 * Anki's own sync moves cards/notes/revlog, so recall **R** already syncs
 * phone<->desktop for free. The `transfer_review` table is NOT part of Anki's
 * synced schema, so this class carries it on a separate channel: export this
 * device's log, push it, pull the merged log back, and import it.
 *
 * The log is append-only and merged **union-by-guid**; the concept's ability is
 * re-derived by replaying it, so this is idempotent and offline-then-sync safe -
 * running it repeatedly (or after offline review) can never lose or
 * double-count a review.
 *
 * Uses `HttpURLConnection` + `org.json` only (both always present on Android),
 * so no new dependency and no `ssl` (the transport is localhost/emulator
 * cleartext HTTP).
 */
object TransferLogSync {
    /**
     * Default endpoint. `10.0.2.2` is the Android emulator's alias for the host
     * machine's loopback, so this reaches a `transfer_sync_server` running on the
     * desktop at `localhost:8090`. Override for a physical device / different port.
     */
    const val DEFAULT_SERVER = "http://10.0.2.2:8090"

    data class Stats(
        val pushedNew: Int,
        val serverTotal: Int,
        val importedNew: Int,
        val localTotal: Int,
    )

    /** Export -> push -> pull -> import. Returns what moved in each direction. */
    fun sync(
        backend: Backend,
        server: String = DEFAULT_SERVER,
    ): Stats {
        val base = server.trimEnd('/')

        // 1. Export the local log and serialise it to JSON. The generated binding
        // for ExportTransferLog (empty request, single repeated-field response)
        // takes no argument and returns the reviews list directly.
        val local = backend.exportTransferLog()
        val outReviews = JSONArray()
        for (r in local) {
            outReviews.put(
                JSONObject().apply {
                    put("guid", r.guid)
                    put("item_id", r.itemId)
                    put("concept_id", r.conceptId)
                    put("correct", r.correct)
                    put("latency_ms", r.latencyMs)
                    put("ts", r.ts)
                    put("difficulty", r.difficulty)
                },
            )
        }
        val pushResp = postJson("$base/transfer/push", JSONObject().put("reviews", outReviews))

        // 2. Pull the merged log and import it (union-by-guid, idempotent).
        val pullResp = getJson("$base/transfer/pull")
        val mergedJson = pullResp.getJSONArray("reviews")
        // ImportTransferLog takes the reviews list directly (the TransferLog
        // wrapper is unwrapped by the generated binding); union-by-guid is done
        // engine-side, so re-importing the same review is a no-op (idempotent).
        val merged =
            (0 until mergedJson.length()).map { i ->
                val o = mergedJson.getJSONObject(i)
                transferReviewProto {
                    guid = o.getString("guid")
                    itemId = o.getLong("item_id")
                    conceptId = o.getLong("concept_id")
                    correct = o.getBoolean("correct")
                    latencyMs = o.getLong("latency_ms")
                    ts = o.getLong("ts")
                    difficulty = o.getDouble("difficulty")
                }
            }
        val imported = backend.importTransferLog(merged)

        return Stats(
            pushedNew = pushResp.optInt("added"),
            serverTotal = pushResp.optInt("total"),
            importedNew = imported.added,
            localTotal = imported.total,
        )
    }

    /**
     * Best-effort variant for the normal sync path: logs the result and never
     * throws, so a missing/unreachable transfer-sync server can never break
     * Anki's own sync.
     */
    fun syncQuietly(
        context: Context,
        backend: Backend,
        server: String = DEFAULT_SERVER,
    ) {
        try {
            val s = sync(backend, server)
            Timber.i(
                "Speedrun transfer-log sync: pushedNew=%d serverTotal=%d importedNew=%d localTotal=%d",
                s.pushedNew,
                s.serverTotal,
                s.importedNew,
                s.localTotal,
            )
        } catch (e: Exception) {
            Timber.w(e, "Speedrun transfer-log sync skipped (no server?)")
        }
        // The AAMC concept graph is not carried by Anki's sync nor the transfer
        // log, so seed it on-device (idempotent) before scoring; without it the
        // engine has transfer reviews but no exam weights and readiness is empty.
        seedConcepts(context, backend)
        // On-device proof that the shared Rust engine computes the three scores on
        // the phone (not just the desktop). Visible with: adb logcat | findstr Speedrun
        logReadiness(backend)
    }

    /**
     * Seeds the 31-concept AAMC map (bundled asset `speedrun/concepts.json`) via
     * idempotent `upsertConcept`. Numeric ids are assigned by file order so they
     * match the desktop's `import_content.py` — this is what lets the transfer
     * reviews (which carry `concept_id`) line up with the seeded concepts and give
     * the same weighted R/T/G + readiness the desktop computes.
     */
    fun seedConcepts(
        context: Context,
        backend: Backend,
    ) {
        try {
            val text =
                context.assets
                    .open("speedrun/concepts.json")
                    .bufferedReader()
                    .use(BufferedReader::readText)
            val root = JSONObject(text)
            val sectionShort = HashMap<String, String>()
            val sections = root.getJSONArray("sections")
            for (i in 0 until sections.length()) {
                val s = sections.getJSONObject(i)
                sectionShort[s.getString("id")] = s.optString("short", s.getString("id"))
            }
            val concepts = root.getJSONArray("concepts")
            for (i in 0 until concepts.length()) {
                val c = concepts.getJSONObject(i)
                val secId = c.getString("section")
                backend.upsertConcept(
                    concept {
                        id = (i + 1).toLong()
                        outlineId = c.getString("id")
                        section = sectionShort[secId] ?: secId
                        title = c.getString("title")
                        examWeight = c.getDouble("exam_weight")
                    },
                )
            }
            Timber.i("Speedrun: seeded %d concepts on device", concepts.length())
        } catch (e: Exception) {
            Timber.w(e, "Speedrun concept seeding skipped")
        }
    }

    /**
     * Logs the three Speedrun scores (Memory R, Performance T, Readiness) with
     * their range and the give-up count, computed on-device by the shared engine.
     * This is the phone-side proof for "three scores + give-up rule on the phone".
     */
    fun logReadiness(backend: Backend) {
        try {
            val r = backend.readinessReport()
            Timber.i(
                "Speedrun scores (on device): Memory(R)=%.2f Performance(T)=%.2f " +
                    "Readiness=%d [%d..%d] coverage=%.2f giveUpConcepts=%d",
                r.memory,
                r.performance,
                r.readiness,
                r.readinessLow,
                r.readinessHigh,
                r.coverage,
                r.giveUpConceptIdsCount,
            )
        } catch (e: Exception) {
            Timber.w(e, "Speedrun readiness log skipped")
        }
    }

    private fun postJson(
        url: String,
        body: JSONObject,
    ): JSONObject {
        val conn = URL(url).openConnection() as HttpURLConnection
        return conn.use {
            it.requestMethod = "POST"
            it.doOutput = true
            it.connectTimeout = 15_000
            it.readTimeout = 30_000
            it.setRequestProperty("Content-Type", "application/json")
            it.outputStream.use { os -> os.write(body.toString().toByteArray()) }
            it.readBody()
        }
    }

    private fun getJson(url: String): JSONObject {
        val conn = URL(url).openConnection() as HttpURLConnection
        return conn.use {
            it.requestMethod = "GET"
            it.connectTimeout = 15_000
            it.readTimeout = 30_000
            it.readBody()
        }
    }

    private fun HttpURLConnection.use(block: (HttpURLConnection) -> JSONObject): JSONObject =
        try {
            block(this)
        } finally {
            disconnect()
        }

    private fun HttpURLConnection.readBody(): JSONObject {
        if (responseCode >= 400) {
            throw RuntimeException("HTTP $responseCode from $url")
        }
        val text = inputStream.bufferedReader().use(BufferedReader::readText)
        return JSONObject(text)
    }
}
