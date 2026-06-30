/*
 * Copyright: Ankitects Pty Ltd and contributors
 * License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
 *
 * TEMPLATE host-JVM proof that the Speedrun engine + RPCs are compiled into the
 * Android backend .aar / .jar. Drop this into the Anki-Android-Backend JVM test
 * sources (e.g. rsdroid-testing or the robolectric test module) and run with
 * `./gradlew test`. No emulator or device required.
 *
 * The proto messages below (anki.speedrun.*) are generated automatically from
 * our proto/anki/speedrun.proto when the backend is built against the Speedrun
 * fork, so if this test compiles and passes, the Speedrun RPCs are live on the
 * Android backend.
 *
 * NOTE: backend construction differs slightly between backend repo versions.
 * Use the same helper the repo's own tests use to obtain an opened Backend
 * (search the test sources for `Backend(` / `openCollection` / a `*ForTesting`
 * helper) and replace `openTestBackend()` below accordingly.
 */

package com.ichi2.anki.speedrun

import anki.speedrun.concept
import anki.speedrun.item
import anki.speedrun.masteryQueryRequest
import anki.speedrun.readinessRequest
import anki.speedrun.recordTransferReviewRequest
import net.ankiweb.rsdroid.Backend
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SpeedrunBackendTest {
    /** TODO: replace with the backend repo's own test-backend helper. */
    private fun openTestBackend(): Backend = TODO("use the repo's test Backend factory / openCollection on a temp file")

    @Test
    fun speedrunEngineIsAvailableOnAndroidBackend() {
        val backend = openTestBackend()

        // Seed one concept + one item through the generated Speedrun RPCs.
        backend.upsertConcept(
            concept {
                id = 1
                outlineId = "1D"
                section = "bb"
                title = "Bioenergetics"
                examWeight = 1.0
            },
        )
        backend.upsertItem(
            item {
                id = 10
                conceptId = 1
                level = 3
                difficulty = 0.2
                sourceRef = "MileDown"
                aiGenerated = false
                stem = "stem"
                choices += listOf("a", "b")
                answer = 0
                explanation = "x"
            },
        )

        // Record a graded transfer review; ability/transfer should rise.
        val before = backend.masteryQuery(masteryQueryRequest { conceptIds += 1L })
        backend.recordTransferReview(
            recordTransferReviewRequest {
                itemId = 10
                conceptId = 1
                correct = true
                latencyMs = 1200
            },
        )
        val after = backend.masteryQuery(masteryQueryRequest { conceptIds += 1L })

        assertEquals(0, before.getEntries(0).nTransferObs)
        assertEquals(1, after.getEntries(0).nTransferObs)
        assertTrue("transfer should increase", after.getEntries(0).transfer > before.getEntries(0).transfer)

        // Dashboard: readiness must land in the MCAT band.
        val readiness = backend.readinessReport(readinessRequest {})
        assertTrue("readiness in 472..528", readiness.readiness in 472..528)

        // Sync log round-trips: export then re-import is idempotent.
        val log = backend.exportTransferLog(anki.speedrun.exportTransferLogRequest {})
        assertEquals(1, log.reviewsCount)
        val reimport = backend.importTransferLog(log)
        assertEquals("re-import adds nothing", 0, reimport.added)

        backend.close()
    }
}
