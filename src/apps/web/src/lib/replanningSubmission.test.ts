import assert from "node:assert/strict";
import test from "node:test";

import {
  ReplanningSubmissionGuard,
  activeSnapshotEvents,
  canonicalEventBatchKey,
  canonicalEventKey,
} from "./replanningSubmission.ts";


test("canonical event key is stable and trip-scoped", () => {
  assert.equal(canonicalEventKey("trip-1", "event-1"), "trip-1:event-1");
  assert.notEqual(
    canonicalEventKey("trip-1", "event-1"),
    canonicalEventKey("trip-2", "event-1"),
  );
});


test("submission guard allows one in-flight or completed request per event", () => {
  const guard = new ReplanningSubmissionGuard();
  assert.equal(guard.begin("trip-1:event-1"), true);
  assert.equal(guard.begin("trip-1:event-1"), false);
  guard.complete("trip-1:event-1");
  assert.equal(guard.begin("trip-1:event-1"), false);
});


test("failed submission can be retried", () => {
  const guard = new ReplanningSubmissionGuard();
  assert.equal(guard.begin("trip-1:event-1"), true);
  guard.fail("trip-1:event-1");
  assert.equal(guard.begin("trip-1:event-1"), true);
});


test("canonical batch key is stable for simultaneous events regardless of order", () => {
  const first = canonicalEventBatchKey(
    "trip-1",
    "snapshot-7",
    ["event-route", "event-soc", "event-station"],
  );
  const reordered = canonicalEventBatchKey(
    "trip-1",
    "snapshot-7",
    ["event-station", "event-route", "event-soc"],
  );

  assert.equal(first, reordered);
  assert.notEqual(first, canonicalEventBatchKey("trip-1", "snapshot-8", ["event-route"]));
});


test("selects all active events from the current telemetry snapshot", () => {
  const events = activeSnapshotEvents({
    telemetry: { snapshot_id: "snapshot-7" },
    events: [
      { event_id: "event-route", telemetry_snapshot_id: "snapshot-7", status: "ACTIVE" },
      { event_id: "event-soc", telemetry_snapshot_id: "snapshot-7", status: "ACTIVE" },
      { event_id: "event-old", telemetry_snapshot_id: "snapshot-6", status: "ACTIVE" },
      { event_id: "event-done", telemetry_snapshot_id: "snapshot-7", status: "RESOLVED" },
    ],
  } as never);

  assert.deepEqual(events.map((event) => event.event_id), ["event-route", "event-soc"]);
});
