export async function withPlanningStreamTimeout<T>(
  operation: Promise<T>,
  timeoutMs: number,
  signal?: AbortSignal,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let removeAbortListener: (() => void) | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(
      "Backend không phản hồi tiến trình lập kế hoạch. Vui lòng thử lại.",
    )), timeoutMs);
  });
  const aborted = new Promise<never>((_, reject) => {
    if (!signal) return;
    const rejectCancelled = () => reject(new Error("Đã hủy yêu cầu lập kế hoạch."));
    if (signal.aborted) {
      rejectCancelled();
      return;
    }
    signal.addEventListener("abort", rejectCancelled, { once: true });
    removeAbortListener = () => signal.removeEventListener("abort", rejectCancelled);
  });
  try {
    return await Promise.race([operation, timeout, aborted]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    removeAbortListener?.();
  }
}
