/**
 * Practice gate state (FS-06).
 *
 * Thin on purpose: the server owns the tally, this just mirrors it and offers
 * `clear(gate)` so a component can report "the participant just did this"
 * without knowing which gates its condition requires. Reporting a gate the
 * condition does not have is refused by the server rather than silently
 * ignored, so a wiring mistake shows up as a 400 instead of a gate that can
 * never be cleared.
 */
import { create } from 'zustand'

import { api } from './api'

interface CheckpointState {
  required: string[]
  cleared: string[]
  complete: boolean
}

interface PracticeStore extends CheckpointState {
  loaded: boolean
  refresh: () => Promise<void>
  clear: (gate: string) => Promise<void>
}

export const usePractice = create<PracticeStore>((set, get) => ({
  required: [],
  cleared: [],
  complete: false,
  loaded: false,

  async refresh() {
    const out = await api.get<CheckpointState>('/checkpoint')
    set({ ...out, loaded: true })
  },

  async clear(gate) {
    // Already done: no request, no duplicate event. The server would dedupe
    // anyway, but a gate cleared twice would still cost a round trip on every
    // magnifier open for the rest of practice.
    if (get().cleared.includes(gate)) return
    const out = await api.post<CheckpointState>('/checkpoint', { gate })
    set({ ...out, required: get().required, loaded: true })
  },
}))
