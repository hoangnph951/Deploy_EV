export function canonicalEventKey(tripId: string, eventId: string): string {
  return `${tripId}:${eventId}`;
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
