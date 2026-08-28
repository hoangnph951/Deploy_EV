import assert from "node:assert/strict";
import test from "node:test";

import { ReplanningSubmissionGuard, canonicalEventKey } from "./replanningSubmission.ts";


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
