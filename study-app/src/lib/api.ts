/**
 * Thin fetch wrapper. Every call carries the bearer token the participant
 * arrived with; nothing else in the app knows how auth works.
 *
 * The token lives in sessionStorage, not localStorage: closing the tab ends
 * the credential's life, so a shared lab machine cannot leak one participant's
 * session into the next participant's browser.
 */

const TOKEN_KEY = 'arbor.study.token'

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token)
}

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()
  const res = await fetch(`/api/study${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  })
  if (!res.ok) {
    // The backend never echoes exception text (BE-17), so there is nothing
    // useful to surface beyond the status.
    let detail = res.statusText
    try {
      const body = (await res.json()) as { detail?: string; error?: string }
      detail = body.detail ?? body.error ?? detail
    } catch {
      /* non-JSON error body: keep the status text */
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
}

// ---------------------------------------------------------------------------
// Response shapes
// ---------------------------------------------------------------------------

export type Condition = 'c' | 'b'
export type Track = 'formal' | 'test'
export type Role = 'participant' | 'moderator'

export interface WhoAmI {
  role: Role
  track: Track
  session_id: string | null
  workspace_id: string
}

/**
 * GET /state.
 *
 * 红线 #4: `remaining_ms` is present ONLY during the organisation phase. The
 * server omits the key entirely elsewhere -- it is optional here for the same
 * reason, and no component may substitute a default for it.
 */
export interface StudyState {
  session_id: string
  condition: Condition
  lang: string
  track: Track
  phase: string
  softlock: boolean
  submitted: boolean
  started: boolean
  /** The protocol says this phase may be ended by the participant. A boolean,
   *  deliberately: the verification phase has no clock and this flag must not
   *  become one (红线 #4). */
  can_submit: boolean
  remaining_ms?: number
}

export interface CreatedSession {
  success: boolean
  session_id: string
  condition: Condition
  lang: string
  track: Track
  join_token: string
  join_url: string
}

export interface IntegrityCheck {
  check: string
  /** pass = satisfied, flag = a human should look, fail = not analysable.
   *  The flag/fail split is PR-4: an unusual event count is a finding, losing
   *  the log is a defect. */
  status: 'pass' | 'flag' | 'fail'
  detail: string
}

export interface IntegrityReport {
  session_id: string
  verdict: 'valid' | 'review' | 'invalid'
  failed: string[]
  flagged: string[]
  event_count: number
  checks: IntegrityCheck[]
}

export interface MonitorRow {
  session_id: string
  condition: Condition
  participant_code: string
  lang: string
  track: Track
  phase: string
  next_phase: string | null
  softlock: boolean
  submitted: boolean
  started: boolean
  seq_acked: number
  heartbeat_age_ms: number | null
  /** Moderator-only. The participant build never renders this (MOD-03). */
  phase_remaining_ms: number | null
}
