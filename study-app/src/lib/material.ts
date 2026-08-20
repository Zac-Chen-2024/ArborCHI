/**
 * Material loaded from the server, replacing the M0 fixtures.
 *
 * Types here mirror what `/api/study/material` actually sends, which is what
 * `materials.public_*` chose to send -- notably WITHOUT `distractor` on nodes
 * and WITHOUT `planted_id` on sentences. Those fields are absent from these
 * interfaces on purpose: a `distractor?: boolean` here would be a place for a
 * future leak to land quietly and typecheck.
 *
 * `source: "frozen" | "live"` DOES come through, because the analysis needs it
 * on the wire. Nothing may render differently because of it (红线 #3) -- see
 * the note on LetterSentence.
 */

import { api } from './api'

export interface Exhibit {
  id: string
  pages: number
  title: string
}

export interface Snippet {
  snippet_id: string
  exhibit: string
  page: number
  /** [x1, y1, x2, y2] in a 1000x1000 normalised space (红线 #8), never pixels. */
  bbox: [number, number, number, number]
  label: string
  text: string
  doc_title: string
  doc_subtitle: string
}

export interface SubArgument {
  id: string
  title: string
  snippet_ids: string[]
}

export interface Argument {
  id: string
  index: string
  title: string
  rationale: string
  subs: SubArgument[]
}

export interface Tree {
  tree_variant_id: string
  criterion: string
  arguments: Argument[]
}

export interface Triple {
  subject: string
  predicate: string
  object: string
}

export interface Relations {
  focus_entity: string
  relations: Record<string, Triple[]>
  other_mentions: Record<string, { exhibit: string; page: number }[]>
}

export interface Material {
  tree: Tree
  relations: Relations
  bbox_space: number
  exhibits: Exhibit[]
  snippets: Record<string, Snippet>
}

export function fetchMaterial(): Promise<Material> {
  return api.get<Material>('/material')
}

// ---------------------------------------------------------------------------
// Generation
// ---------------------------------------------------------------------------

/** What the client tells the server about a node. Note what is NOT here: any
 *  claim about whether it changed. The server decides that by comparing with
 *  the frozen tree -- the client is the thing being measured. */
export interface NodeState {
  title: string
  parent_id: string
  snippet_ids: string[]
  state: 'proposed' | 'accepted' | 'edited' | 'removed'
}

export interface LetterSentence {
  sent_id: string
  text: string
  snippet_ids: string[]
  exhibit_refs: { exhibit: string; page: number }[]
  sentence_type: string
  /**
   * Where the sentence came from. Carried for the analysis and for nothing
   * else: no component may branch on it, style on it, or order by it. A
   * participant who could tell frozen from live would be verifying a different
   * artefact than one who could not (红线 #3).
   */
  source: 'frozen' | 'live'
  subargument_id: string
  argument_id: string
  position: number
  position_in_node: number
  change_reason?: string
}

export interface GeneratedLetter {
  text: string
  sentences: LetterSentence[]
  stats: { frozen: number; live: number; nodes_changed: number; nodes_total: number }
}

export function generateLetter(nodeStates: Record<string, NodeState>): Promise<GeneratedLetter> {
  return api.post<GeneratedLetter>('/generate', { node_states: nodeStates })
}

// ---------------------------------------------------------------------------
// Submission
// ---------------------------------------------------------------------------

/** sha256 of the text, hex, computed the same way the server will. */
export async function sha256Hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

export async function submitFinal(text: string): Promise<void> {
  await api.post('/submit', { text, final_text_hash: await sha256Hex(text) })
}
