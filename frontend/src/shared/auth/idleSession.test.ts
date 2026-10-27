import { afterEach, describe, expect, test, vi } from 'vitest'
import { idleTimeoutMs, startIdleSession } from './idleSession'

afterEach(() => {
  vi.useRealTimers()
})

describe('R1-042 idle session control', () => {
  test('defaults to thirty minutes and rejects unsafe configuration', () => {
    expect(idleTimeoutMs(undefined)).toBe(30 * 60 * 1000)
    expect(idleTimeoutMs('15')).toBe(15 * 60 * 1000)
    expect(idleTimeoutMs('0')).toBe(30 * 60 * 1000)
    expect(idleTimeoutMs('not-a-number')).toBe(30 * 60 * 1000)
  })

  test('signs out once after the configured period without activity', async () => {
    vi.useFakeTimers()
    const onIdle = vi.fn().mockResolvedValue(undefined)
    const stop = startIdleSession({ timeoutMs: 1_000, onIdle })

    await vi.advanceTimersByTimeAsync(999)
    expect(onIdle).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(onIdle).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(5_000)
    expect(onIdle).toHaveBeenCalledTimes(1)
    stop()
  })

  test('user activity restarts the idle period and cleanup removes the guard', async () => {
    vi.useFakeTimers()
    const onIdle = vi.fn().mockResolvedValue(undefined)
    const stop = startIdleSession({ timeoutMs: 1_000, onIdle })

    await vi.advanceTimersByTimeAsync(800)
    window.dispatchEvent(new Event('keydown'))
    await vi.advanceTimersByTimeAsync(800)
    expect(onIdle).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(200)
    expect(onIdle).toHaveBeenCalledTimes(1)

    stop()
    window.dispatchEvent(new Event('pointerdown'))
    await vi.advanceTimersByTimeAsync(2_000)
    expect(onIdle).toHaveBeenCalledTimes(1)
  })

  test('returning to a throttled background tab cannot revive an expired session', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2027-01-01T00:00:00Z'))
    const onIdle = vi.fn().mockResolvedValue(undefined)
    const stop = startIdleSession({ timeoutMs: 1_000, onIdle })

    // Moving wall time models a browser that suspended the timeout while the tab slept.
    vi.setSystemTime(new Date('2027-01-01T00:00:02Z'))
    window.dispatchEvent(new Event('focus'))

    expect(onIdle).toHaveBeenCalledTimes(1)
    stop()
  })
})
