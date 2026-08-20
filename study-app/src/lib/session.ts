/**
 * Session state: one poll loop, one store, read by everything.
 *
 * The condition comes from here and ONLY from here (D2). No component reads
 * the URL to decide what to render, so a participant who types /c cannot land
 * in condition C -- the router redirects them back to whatever their token
 * says. `phase` drives the same way: the server is the authority, the client
 * only reflects it.
 */
import { create } from 'zustand'

import { api, type StudyState } from './api'
import { applySessionLang } from '../i18n'

const POLL_MS = 2000

interface SessionStore {
  state: StudyState | null
  error: string | null
  loading: boolean
  refresh: () => Promise<void>
  startPolling: () => () => void
}

export const useSession = create<SessionStore>((set, get) => ({
  state: null,
  error: null,
  loading: true,

  async refresh() {
    try {
      const next = await api.get<StudyState>('/state')
      applySessionLang(next.lang)
      set({ state: next, error: null, loading: false })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : 'error', loading: false })
    }
  },

  startPolling() {
    void get().refresh()
    const id = window.setInterval(() => void get().refresh(), POLL_MS)
    return () => window.clearInterval(id)
  },
}))

/**
 * Remaining time for the countdown, in ms, or null when the participant is
 * not allowed to see a clock.
 *
 * 红线 #4 / FS-07. This returns null unless the server actually sent
 * `remaining_ms`, which it does only in the organisation phase. There is
 * deliberately no fallback that derives a time from anything else -- if this
 * function ever starts returning a number in the verification phase, the leak
 * is upstream in the API, and the countdown component will make it visible.
 */
export function visibleRemainingMs(state: StudyState | null): number | null {
  if (!state) return null
  return typeof state.remaining_ms === 'number' ? state.remaining_ms : null
}

export const BUILD_HASH: string = __BUILD_HASH__
