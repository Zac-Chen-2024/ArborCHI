/**
 * Interaction log SDK (FS-04, 日志手册 §1).
 *
 * A singleton. Every call site does `log('chip_click', {...})` and nothing
 * else: seq, both clocks, phase, practice, condition, track and build are
 * filled in here, so no component can forget one or disagree about it.
 *
 * Extended from the product frontend's `services/interactionLogger.ts` rather
 * than written fresh (§7.5): the batching, the sendBeacon fallback, the
 * localStorage mirror and the failure backoff were already correct there. What
 * is new is the study envelope (seq / ts_mono / phase / practice / track), the
 * heartbeat, and the acked_seq-driven drain.
 *
 * ## What survives what
 *
 * | failure                | what saves the data                         |
 * |------------------------|---------------------------------------------|
 * | network drops for 30s  | queue holds; exponential backoff; resend    |
 * | participant closes tab | `pagehide` -> sendBeacon (fires after unload)|
 * | browser/tab crashes    | localStorage mirror, replayed on next boot  |
 * | server rejects a batch | queue is NOT dropped until acked_seq covers it|
 *
 * The mirror is written on every enqueue, not on a timer: a crash between the
 * timer ticks would lose exactly the events leading up to the crash, which are
 * the interesting ones.
 *
 * ## Why payloads carry names, not just ids
 *
 * The post-task interview is planned as half fixed questions and half
 * questions drawn from what this participant actually did. That only works if
 * a log line reads as a sentence -- "moved 'Decision and resource authority'
 * under 'The petitioner performs a leading role'" -- rather than as a pair of
 * opaque ids that would need every earlier event replayed to decode. So call
 * sites pass titles and labels alongside ids, and this file does not strip
 * them. Verbosity is the point; the analysis is the customer.
 */

import { getToken } from './api'

const ENDPOINT = '/api/study/log/batch'
const MIRROR_KEY = 'arbor.study.logqueue'
const FLUSH_INTERVAL_MS = 5_000
const FLUSH_AT_COUNT = 20
const HEARTBEAT_MS = 30_000
const MAX_BACKOFF_MS = 60_000
/** Hard cap so a long offline stretch cannot exhaust localStorage. */
const MAX_QUEUE = 2_000

export interface LoggedEvent {
  seq: number
  ts_mono: number
  ts_wall: string
  phase: string
  practice: boolean
  cond: string
  track: string
  build: string
  event: string
  payload: Record<string, unknown>
}

/** Read from session.ts; call sites never pass these. */
interface Context {
  phase: string
  practice: boolean
  cond: string
  track: string
}

class Logger {
  private queue: LoggedEvent[] = []
  private seq = 0
  private ctx: Context = { phase: 'setup', practice: false, cond: '', track: '' }
  private build = ''
  private timer: number | null = null
  private heartbeat: number | null = null
  private backoff = 0
  private sending = false
  private started = false

  /** Monotonic origin. performance.now() is immune to wall-clock jumps (NTP
   *  correction, the participant's laptop resuming from sleep), which is why
   *  ordering within a session uses it and never Date.now(). */
  private monoOrigin = performance.now()

  start(build: string): void {
    if (this.started) return
    this.started = true
    this.build = build
    this.restoreMirror()

    this.timer = window.setInterval(() => void this.flush(), FLUSH_INTERVAL_MS)
    this.heartbeat = window.setInterval(
      () => this.log('heartbeat', {}), HEARTBEAT_MS,
    )

    // pagehide covers tab close, navigation and bfcache entry; visibilitychange
    // covers the participant switching away without closing. Both, because
    // neither alone fires in every browser for every exit.
    window.addEventListener('pagehide', this.beaconFlush)
    document.addEventListener('visibilitychange', this.onVisibilityChange)
  }

  private onVisibilityChange = (): void => {
    if (document.visibilityState === 'hidden') this.beaconFlush()
  }

  /** Undo everything `start` did. Listeners as well as timers: leaving them
   *  attached means a second logger's flush fires the first one's too, which
   *  is invisible in an app with one logger and a page-long lifetime, and very
   *  visible the moment anything creates two. */
  stop(): void {
    if (this.timer !== null) window.clearInterval(this.timer)
    if (this.heartbeat !== null) window.clearInterval(this.heartbeat)
    this.timer = null
    this.heartbeat = null
    window.removeEventListener('pagehide', this.beaconFlush)
    document.removeEventListener('visibilitychange', this.onVisibilityChange)
    this.started = false
  }

  setContext(ctx: Partial<Context>): void {
    this.ctx = { ...this.ctx, ...ctx }
  }

  /**
   * Record one event. Never throws and never awaits: a logging failure must
   * not be able to break the task the participant is doing.
   */
  log(event: string, payload: Record<string, unknown> = {}): void {
    const record: LoggedEvent = {
      seq: this.seq++,
      ts_mono: Math.round(performance.now() - this.monoOrigin),
      ts_wall: new Date().toISOString(),
      phase: this.ctx.phase,
      practice: this.ctx.practice,
      cond: this.ctx.cond,
      track: this.ctx.track,
      build: this.build,
      event,
      payload,
    }
    this.queue.push(record)
    if (this.queue.length > MAX_QUEUE) {
      // Drop from the FRONT: the oldest events are the ones already least
      // likely to matter, and the seq gap makes the loss explicit on the
      // server rather than silent.
      this.queue.splice(0, this.queue.length - MAX_QUEUE)
    }
    this.writeMirror()
    if (this.queue.length >= FLUSH_AT_COUNT) void this.flush()
  }

  /** Send what is queued. Safe to call concurrently; overlapping calls no-op. */
  async flush(): Promise<void> {
    if (this.sending || this.queue.length === 0) return
    if (this.backoff > 0) return
    this.sending = true

    const batch = this.queue.slice()
    try {
      const res = await fetch(ENDPOINT, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(getToken() ? { Authorization: `Bearer ${getToken()!}` } : {}),
        },
        body: JSON.stringify({ events: batch }),
        keepalive: true,
      })
      if (!res.ok) throw new Error(String(res.status))

      const { acked_seq } = (await res.json()) as { acked_seq: number }
      // Drain by acked_seq rather than by "we sent these": if the server only
      // committed part of the batch, the rest stays queued and is retried.
      this.queue = this.queue.filter((e) => e.seq > acked_seq)
      this.writeMirror()
      this.backoff = 0
    } catch {
      // Exponential backoff, capped. The queue is untouched -- nothing is
      // dropped because a request failed.
      this.backoff = this.backoff === 0 ? 1_000 : Math.min(this.backoff * 2, MAX_BACKOFF_MS)
      window.setTimeout(() => {
        this.backoff = 0
        void this.flush()
      }, this.backoff)
    } finally {
      this.sending = false
    }
  }

  /**
   * Last-chance flush on tab close. fetch() is cancelled when the document
   * goes away; sendBeacon is queued by the browser and survives it.
   *
   * The blob is text/plain: an application/json blob would need a CORS
   * preflight, and a beacon cannot perform one. The server reads this endpoint's
   * body raw for exactly this reason.
   */
  private beaconFlush = (): void => {
    if (this.queue.length === 0) return
    const token = getToken()
    const url = token ? `${ENDPOINT}?token=${encodeURIComponent(token)}` : ENDPOINT
    const blob = new Blob([JSON.stringify({ events: this.queue })], { type: 'text/plain' })
    const sent = navigator.sendBeacon(url, blob)
    if (sent) {
      // Keep the mirror: if the beacon is silently dropped, the next session
      // boot replays it. Clearing here would trade a duplicate for a loss, and
      // duplicates are removable in analysis while losses are not.
      this.queue = []
    }
  }

  // -- crash mirror ---------------------------------------------------------

  private writeMirror(): void {
    try {
      localStorage.setItem(MIRROR_KEY, JSON.stringify(this.queue))
    } catch {
      /* quota or private mode: the in-memory queue still works */
    }
  }

  private restoreMirror(): void {
    try {
      const raw = localStorage.getItem(MIRROR_KEY)
      if (!raw) return
      const events = JSON.parse(raw) as LoggedEvent[]
      if (Array.isArray(events) && events.length) {
        this.queue = events.concat(this.queue)
        // Continue the seq series past whatever the dead session reached, so
        // the server sees one monotonic run with a visible gap rather than a
        // second run that appears to restart.
        this.seq = Math.max(this.seq, ...events.map((e) => e.seq + 1))
        void this.flush()
      }
    } catch {
      /* corrupt mirror: better to start clean than to fail boot */
    }
  }

  /** Test seam. */
  pending(): number {
    return this.queue.length
  }
}

export const logger = new Logger()

/**
 * Convenience for dwell timing (hover_end, lightbox_close). Returns a function
 * that logs the paired end event with the elapsed milliseconds filled in.
 *
 *   const done = startDwell('lightbox_close', { exhibit, page })
 *   ... later ...
 *   done()
 */
export function startDwell(
  endEvent: string,
  payload: Record<string, unknown> = {},
): () => void {
  const t0 = performance.now()
  let fired = false
  return () => {
    if (fired) return
    fired = true
    logger.log(endEvent, { ...payload, dwell_ms: Math.round(performance.now() - t0) })
  }
}
