import assert from "node:assert/strict";
import test from "node:test";

import { withPlanningStreamTimeout } from "./planningStreamWatchdog.ts";


test("planning stream watchdog rejects a request that stays silent", async () => {
  const never = new Promise<never>(() => undefined);

  await assert.rejects(
    withPlanningStreamTimeout(never, 5),
    /Backend không phản hồi tiến trình lập kế hoạch/,
  );
});


test("planning stream watchdog returns a response received before deadline", async () => {
  const result = await withPlanningStreamTimeout(Promise.resolve("ok"), 50);
  assert.equal(result, "ok");
});
