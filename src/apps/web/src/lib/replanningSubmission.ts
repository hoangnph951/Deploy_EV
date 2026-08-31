import type { SimulationState } from "./types";


export function canonicalEventKey(tripId: string, eventId: string): string {
  return `${tripId}:${eventId}`;
}

export function canonicalEventBatchKey(
  tripId: string,
  telemetrySnapshotId: string,
  eventIds: string[],
): string {
  return `${tripId}:${telemetrySnapshotId}:${[...eventIds].sort().join(",")}`;
}

export function activeSnapshotEvents(
  state: Pick<SimulationState, "telemetry" | "events">,
): SimulationState["events"] {
  const snapshotId = state.telemetry?.snapshot_id;
  return state.events.filter((event) => (
    event.status === "ACTIVE"
    && (!snapshotId || event.telemetry_snapshot_id === snapshotId)
  ));
}

export class ReplanningSubmissionGuard {
  private readonly active = new Set<string>();
  private readonly completed = new Set<string>();

  begin(key: string): boolean {
    if (this.active.has(key) || this.completed.has(key)) return false;
    this.active.add(key);
    return true;
  }

  complete(key: string): void {
    this.active.delete(key);
    this.completed.add(key);
  }

  fail(key: string): void {
    this.active.delete(key);
  }

  reset(): void {
    this.active.clear();
    this.completed.clear();
  }
}
