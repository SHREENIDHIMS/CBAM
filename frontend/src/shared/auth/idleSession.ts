const MINUTE_MS = 60_000
const DEFAULT_IDLE_MINUTES = 30
const MAX_IDLE_MINUTES = 24 * 60

const ACTIVITY_EVENTS = ['keydown', 'pointerdown', 'scroll', 'touchstart', 'focus'] as const

/**
 * Resolve the browser inactivity limit. Invalid values fail closed to the documented
 * thirty-minute default rather than disabling sign-out.
 */
export function idleTimeoutMs(raw: string | undefined): number {
  if (raw === undefined || raw.trim() === '') return DEFAULT_IDLE_MINUTES * MINUTE_MS
  const minutes = Number(raw)
  if (!Number.isInteger(minutes) || minutes < 1 || minutes > MAX_IDLE_MINUTES) {
    return DEFAULT_IDLE_MINUTES * MINUTE_MS
  }
  return minutes * MINUTE_MS
}

export function startIdleSession({
  timeoutMs,
  onIdle,
  target = window,
}: {
  timeoutMs: number
  onIdle: () => void | Promise<void>
  target?: Window
}): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined
  let expired = false
  let lastActivity = Date.now()

  const expire = () => {
    if (expired) return
    expired = true
    void Promise.resolve(onIdle()).catch(() => undefined)
  }

  const restart = () => {
    if (expired) return
    const now = Date.now()
    // Background tabs may delay timers. An event after the wall-clock deadline must
    // expire the session, not revive it by resetting a throttled timer.
    if (now - lastActivity >= timeoutMs) {
      expire()
      return
    }
    lastActivity = now
    if (timer !== undefined) clearTimeout(timer)
    timer = setTimeout(expire, timeoutMs)
  }

  for (const event of ACTIVITY_EVENTS) target.addEventListener(event, restart)
  restart()

  return () => {
    if (timer !== undefined) clearTimeout(timer)
    for (const event of ACTIVITY_EVENTS) target.removeEventListener(event, restart)
  }
}
