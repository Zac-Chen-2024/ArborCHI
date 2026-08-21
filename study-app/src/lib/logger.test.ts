/**
 * Logger reliability (FS-04) -- the dry run's B11/B12/B13 as tests.
 *
 * These three were on the manual list: pull the network cable for 30 seconds,
 * close the tab, crash the browser. Walking them by hand before every change
 * is not sustainable, and they guard the one thing in this system that cannot
 * be recovered afterwards: a session's log. So the failures are injected here
 * instead -- fetch made to reject, `pagehide` dispatched, a fresh logger booted
 * onto a mirror left behind by a dead one.
 *
 * What is deliberately NOT asserted: exact timer behaviour. The intervals are
 * real time and testing them would mean either sleeping for seconds or mocking
 * the clock so thoroughly that the test stops describing the real thing. The
 * properties that matter -- nothing dropped, the queue drains only on
 * acknowledgement, the mirror survives a crash -- hold regardless of when the
 * flush happens to fire.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setToken } from './api'
import { mirrorKeyFor } from './logger'

const ENDPOINT = '/api/study/log/batch'
/** Every test authenticates as 'test-token', so the mirror lands here. */
const MIRROR = mirrorKeyFor('test-token')

/** A fresh logger module per test: it is a singleton holding a queue.
 *
 * The instance is remembered so `afterEach` can stop it even when the test
 * fails partway. A logger left running keeps its `pagehide` listener attached,
 * and the next test's dispatch then fires two -- which showed up as a
 * confusing "expected 1 call, got 2" in a test that was itself fine.
 */
let current: { stop: () => void } | null = null

async function freshLogger() {
  vi.resetModules()
  const { logger } = await import('./logger')
  current = logger
  return logger
}

function okResponse(ackedSeq: number) {
  return {
    ok: true,
    json: async () => ({ acked_seq: ackedSeq, accepted: 0, rejected: 0 }),
  } as unknown as Response
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  setToken('test-token')
  vi.stubGlobal('navigator', { ...navigator, sendBeacon: vi.fn(() => true) })
})

afterEach(async () => {
  current?.stop()
  // stop() cancels the timers, not a flush already awaiting its response. That
  // flush still calls writeMirror() when it lands -- and if it lands after the
  // next test's beforeEach has cleared localStorage, it restores the previous
  // test's events into the next test's mirror. Which is exactly how it
  // presented: a test asserting that a foreign mirror is never replayed saw two
  // events belonging to a test three cases earlier.
  await new Promise((r) => setTimeout(r, 20))
  current = null
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// B11 -- the network goes away
// ---------------------------------------------------------------------------

describe('losing the network', () => {
  it('keeps every event when the request fails', async () => {
    const logger = await freshLogger()
    const fetchMock = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })
    vi.stubGlobal('fetch', fetchMock)

    logger.start('test-build')
    for (let i = 0; i < 25; i++) logger.log('heartbeat', { i })

    await logger.flush()

    // Nothing is dropped because a request failed -- that is the whole point.
    expect(logger.pending()).toBe(25)
    expect(fetchMock).toHaveBeenCalled()
  })

  it('retries by itself once the network comes back', async () => {
    const logger = await freshLogger()
    let online = false
    const sent: number[][] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string) as { events: { seq: number }[] }
      if (!online) throw new TypeError('Failed to fetch')
      sent.push(body.events.map((e) => e.seq))
      return okResponse(Math.max(...body.events.map((e) => e.seq)))
    }))

    logger.start('test-build')
    for (let i = 0; i < 5; i++) logger.log('heartbeat', { i })
    await logger.flush()
    expect(logger.pending()).toBe(5)

    // Nothing calls flush again: the backoff timer does. Waiting for it rather
    // than re-flushing by hand is the stronger check -- a participant whose
    // network returns does not press anything, and this is what has to happen
    // on its own. (First backoff step is 1s.)
    online = true
    await new Promise((r) => setTimeout(r, 1300))

    expect(logger.pending()).toBe(0)
    expect(sent.at(-1)).toEqual([0, 1, 2, 3, 4])
  })

  it('drains only up to acked_seq, so a partial commit is retried', async () => {
    const logger = await freshLogger()
    // The server committed the first three and stopped.
    vi.stubGlobal('fetch', vi.fn(async () => okResponse(2)))

    logger.start('test-build')
    for (let i = 0; i < 6; i++) logger.log('heartbeat', { i })
    await logger.flush()

    // Events 3..5 were sent but not acknowledged, so they stay queued.
    expect(logger.pending()).toBe(3)
  })
})

// ---------------------------------------------------------------------------
// B12 -- the tab closes
// ---------------------------------------------------------------------------

describe('closing the tab', () => {
  it('flushes through sendBeacon on pagehide', async () => {
    const logger = await freshLogger()
    const beacon = vi.fn(() => true)
    vi.stubGlobal('navigator', { ...navigator, sendBeacon: beacon })
    vi.stubGlobal('fetch', vi.fn(async () => okResponse(-1)))

    logger.start('test-build')
    logger.log('declare_done', { condition: 'c' })

    window.dispatchEvent(new Event('pagehide'))

    expect(beacon).toHaveBeenCalledTimes(1)
    const [url, blob] = beacon.mock.calls[0] as unknown as [string, Blob]
    expect(url).toContain(ENDPOINT)
    // text/plain, because a beacon cannot perform the CORS preflight an
    // application/json blob would require.
    expect(blob.type).toBe('text/plain')
    const body = JSON.parse(await blob.text()) as { events: { event: string }[] }
    expect(body.events.map((e) => e.event)).toContain('declare_done')
  })

  it('keeps the mirror after a beacon, trading a possible duplicate for no loss', async () => {
    const logger = await freshLogger()
    vi.stubGlobal('navigator', { ...navigator, sendBeacon: vi.fn(() => true) })
    vi.stubGlobal('fetch', vi.fn(async () => okResponse(-1)))

    logger.start('test-build')
    logger.log('heartbeat', {})
    window.dispatchEvent(new Event('pagehide'))

    // A beacon can be dropped silently by the browser. The mirror stays so the
    // next boot replays it: duplicates are removable in analysis, losses are not.
    const mirror = JSON.parse(localStorage.getItem(MIRROR) ?? '[]')
    expect(mirror.length).toBeGreaterThan(0)
    logger.stop()
  })
})

// ---------------------------------------------------------------------------
// B13 -- the browser dies
// ---------------------------------------------------------------------------

describe('surviving a crash', () => {
  it('replays what the dead session left in the mirror', async () => {
    const first = await freshLogger()
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))

    first.start('test-build')
    first.log('chip_click', { snippet_id: 'c4' })
    first.log('hover_start', { snippet_id: 'c8' })
    await first.flush()
    first.stop()
    expect(JSON.parse(localStorage.getItem(MIRROR)!)).toHaveLength(2)

    // The tab dies here. A new one boots onto the same localStorage.
    const sent: { seq: number; event: string }[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string) as { events: typeof sent }
      sent.push(...body.events)
      return okResponse(Math.max(...body.events.map((e) => e.seq)))
    }))

    const second = await freshLogger()
    second.start('test-build')
    await new Promise((r) => setTimeout(r, 50))     // restore triggers a flush

    expect(sent.map((e) => e.event)).toEqual(['chip_click', 'hover_start'])
    second.stop()
  })

  it('continues the seq series past the dead session so the gap is visible', async () => {
    const first = await freshLogger()
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))
    first.start('test-build')
    for (let i = 0; i < 4; i++) first.log('heartbeat', {})
    await first.flush()
    first.stop()

    const second = await freshLogger()
    const seen: number[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string) as { events: { seq: number }[] }
      seen.push(...body.events.map((e) => e.seq))
      return okResponse(Math.max(...body.events.map((e) => e.seq)))
    }))
    second.start('test-build')
    // Let the restore's own flush finish first: flush() is a no-op while one
    // is in flight, so logging immediately would leave the new event queued
    // until the next 5s tick.
    await new Promise((r) => setTimeout(r, 50))
    second.log('heartbeat', {})
    await second.flush()

    // The new events continue from 4 rather than restarting at 0. A restart
    // would make the recovered batch and the new one collide, and the server
    // would see a duplicate rather than a resumption.
    expect(Math.max(...seen)).toBeGreaterThanOrEqual(4)
    second.stop()
  })

  it('boots cleanly when the mirror is corrupt', async () => {
    localStorage.setItem(MIRROR, '{not json')
    const logger = await freshLogger()
    vi.stubGlobal('fetch', vi.fn(async () => okResponse(0)))

    expect(() => logger.start('test-build')).not.toThrow()
    logger.log('heartbeat', {})
    expect(logger.pending()).toBe(1)
    logger.stop()
  })
})

// ---------------------------------------------------------------------------
// Envelope
// ---------------------------------------------------------------------------

describe('the envelope', () => {
  it('fills in seq, both clocks and the session context on every event', async () => {
    const logger = await freshLogger()
    const sent: Record<string, unknown>[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string) as { events: typeof sent }
      sent.push(...body.events)
      return okResponse(99)
    }))

    logger.start('abc123')
    logger.setContext({ phase: 'verification', practice: false, cond: 'c', track: 'test' })
    logger.log('chip_click', { snippet_id: 'c4' })
    logger.log('heartbeat', {})
    await logger.flush()

    expect(sent).toHaveLength(2)
    expect(sent.map((e) => e.seq)).toEqual([0, 1])
    for (const e of sent) {
      expect(e.phase).toBe('verification')
      expect(e.cond).toBe('c')
      expect(e.track).toBe('test')
      expect(e.build).toBe('abc123')
      expect(typeof e.ts_mono).toBe('number')
      expect(typeof e.ts_wall).toBe('string')
    }
    logger.stop()
  })

  it('caps the queue by dropping the OLDEST, leaving a visible gap', async () => {
    const logger = await freshLogger()
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))

    logger.start('test-build')
    for (let i = 0; i < 2100; i++) logger.log('heartbeat', {})

    // Bounded so a long offline stretch cannot exhaust localStorage. Dropping
    // from the front leaves a seq gap the server registers, rather than a
    // silent hole.
    expect(logger.pending()).toBe(2000)
    logger.stop()
  })
})

// ---------------------------------------------------------------------------
// The next participant on the same machine
// ---------------------------------------------------------------------------

describe('a mirror left by a different session', () => {
  it('is neither replayed nor allowed to carry the seq forward', async () => {
    // Participant N ended with unsent events under their own token.
    localStorage.setItem(
      mirrorKeyFor('participant-N-token'),
      JSON.stringify([
        { seq: 106, event: 'chip_click', payload: { snippet_id: 'c4' } },
        { seq: 107, event: 'declare_done', payload: {} },
      ]),
    )

    // Participant N+1 boots in the same browser profile, with their own token.
    setToken('test-token')
    const logger = await freshLogger()
    const sent: { seq: number; event: string }[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string) as { events: typeof sent }
      sent.push(...body.events)
      return okResponse(Math.max(...body.events.map((e) => e.seq)))
    }))

    logger.start('test-build')
    await new Promise((r) => setTimeout(r, 50))
    logger.log('heartbeat', {})
    await logger.flush()

    // Not one of N's events may appear under N+1's token...
    expect(sent.map((e) => e.event)).not.toContain('chip_click')
    expect(sent.map((e) => e.event)).not.toContain('declare_done')
    // ...and the series starts at 0, so the server does not record a gap of
    // 108 events in a session that has lost nothing. That phantom gap was
    // enough to fail a complete session on the log-loss check.
    expect(sent[0].seq).toBe(0)
    // N's mirror is gone rather than lingering to be picked up later.
    expect(localStorage.getItem(mirrorKeyFor('participant-N-token'))).toBeNull()
  })

  it('still recovers this session own mirror across a reload', async () => {
    setToken('test-token')
    const first = await freshLogger()
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))
    first.start('test-build')
    first.log('cite_click', { snippet_id: 'c9' })
    await first.flush()
    first.stop()

    // Same token: a reload, not a new participant.
    const sent: { event: string }[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string) as { events: { seq: number; event: string }[] }
      sent.push(...body.events)
      return okResponse(Math.max(...body.events.map((e) => e.seq)))
    }))
    const second = await freshLogger()
    second.start('test-build')
    await new Promise((r) => setTimeout(r, 50))

    expect(sent.map((e) => e.event)).toContain('cite_click')
  })
})

describe('the sequence number across a reload', () => {
  it('continues rather than restarting once the queue has drained', async () => {
    setToken('test-token')
    const first = await freshLogger()
    vi.stubGlobal('fetch', vi.fn(async () => okResponse(2)))
    first.start('test-build')
    for (let i = 0; i < 3; i++) first.log('heartbeat', {})
    await first.flush()
    // Everything acknowledged: the mirror is empty, which is the ordinary case.
    expect(first.pending()).toBe(0)
    first.stop()

    // The page reloads. Nothing was lost, so nothing is in the mirror to carry
    // the counter -- and this used to restart the series at 0, which the server
    // reads as neither a gap nor new events. A whole session after the first
    // reload became invisible to the log-loss check that decides validity.
    const seen: number[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string) as { events: { seq: number }[] }
      seen.push(...body.events.map((e) => e.seq))
      return okResponse(Math.max(...body.events.map((e) => e.seq)))
    }))
    const second = await freshLogger()
    second.start('test-build')
    second.log('heartbeat', {})
    await second.flush()

    expect(seen).toEqual([3])
    second.stop()
  })

  it('does not inherit the counter from a different session', async () => {
    setToken('participant-N-token')
    const theirs = await freshLogger()
    vi.stubGlobal('fetch', vi.fn(async () => okResponse(99)))
    theirs.start('test-build')
    for (let i = 0; i < 100; i++) theirs.log('heartbeat', {})
    await theirs.flush()
    theirs.stop()

    setToken('test-token')
    const seen: number[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string) as { events: { seq: number }[] }
      seen.push(...body.events.map((e) => e.seq))
      return okResponse(Math.max(...body.events.map((e) => e.seq)))
    }))
    const mine = await freshLogger()
    mine.start('test-build')
    mine.log('heartbeat', {})
    await mine.flush()

    expect(seen).toEqual([0])
    mine.stop()
  })
})
