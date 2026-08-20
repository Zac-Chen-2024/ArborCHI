/**
 * Debounced text-edit logging with sentence lineage (红线 #2, C-10, B-05).
 *
 * Two separate jobs, deliberately kept together because they share the same
 * before/after pair:
 *
 * 1. **Debounce.** Logging a keystroke each would drown the log and tell us
 *    nothing; logging only on blur would lose the shape of a long revision.
 *    2 seconds of quiet is the unit the study defines as "an edit".
 *
 * 2. **Lineage.** When a sentence is split in two, or two are merged, the new
 *    sentences must keep a link to the old ones. Without it a sentence's
 *    provenance (which snippet it cites, whether it was frozen or live) dies
 *    the first time the participant presses Enter mid-sentence, and every
 *    downstream question about "did they check the sentence they changed"
 *    becomes unanswerable.
 *
 * The alignment is the same algorithm and the same thresholds as the product's
 * `utils/sentenceDiff.ts` (Dice coefficient over character bigrams, 0.92 for a
 * confident match and 0.35 for a weak one). Reusing the numbers is not
 * laziness: the analysis pipeline runs the same alignment offline, and if the
 * two disagreed the offline reconstruction would not match what was logged
 * live. Both are pre-registered.
 */

import { splitSentences } from './sentences'

const DEBOUNCE_MS = 2000
const STRONG = 0.92
const WEAK = 0.35

/** Character bigrams of a normalised string. */
function bigrams(s: string): Map<string, number> {
  const norm = s.toLowerCase().replace(/\s+/g, ' ').trim()
  const out = new Map<string, number>()
  for (let i = 0; i < norm.length - 1; i++) {
    const g = norm.slice(i, i + 2)
    out.set(g, (out.get(g) ?? 0) + 1)
  }
  return out
}

/** Dice coefficient over character bigrams: 0 (nothing shared) .. 1 (identical). */
export function similarity(a: string, b: string): number {
  if (a === b) return 1
  const A = bigrams(a)
  const B = bigrams(b)
  if (A.size === 0 || B.size === 0) return 0
  let shared = 0
  let total = 0
  for (const [g, n] of A) {
    total += n
    shared += Math.min(n, B.get(g) ?? 0)
  }
  for (const n of B.values()) total += n
  return (2 * shared) / total
}


/**
 * How a sentence after the edit relates to the one it inherited its id from.
 * The two thresholds carry different meanings for the analysis: `edited` is a
 * wording tweak to a sentence the participant kept, `rewritten` is the same
 * slot filled with substantially different prose. Collapsing them would hide
 * the difference between proofreading and rethinking.
 */
export type MatchKind = 'same' | 'edited' | 'rewritten' | 'new'

export interface Sentence {
  id: string
  text: string
  kind?: MatchKind
}

export interface EditDiff {
  /** Sentences present after the edit, with the id they inherit. */
  after: Sentence[]
  /** Ids of sentences the edit touched -- what `text_edit` reports. */
  affected: string[]
  /** old id -> new ids. A split yields one entry with two ids. */
  lineage: Record<string, string[]>
  splits: number
  merges: number
}

let counter = 0
function newId(): string {
  return `s_${Date.now().toString(36)}_${(counter++).toString(36)}`
}

/**
 * Align the sentences after an edit to the ones before it.
 *
 * A new sentence that strongly resembles exactly one old sentence inherits its
 * id. Two new sentences that both resemble the same old one are a split: both
 * inherit, and the lineage records the fork so the old id is never orphaned.
 * A new sentence resembling nothing above the weak threshold is genuinely new.
 */
export function alignSentences(before: Sentence[], afterText: string): EditDiff {
  const afterRaw = splitSentences(afterText)
  const lineage: Record<string, string[]> = {}
  const claims = new Map<string, string[]>() // old id -> new ids claiming it
  const after: Sentence[] = []

  for (const text of afterRaw) {
    let bestId: string | null = null
    let best = 0
    for (const old of before) {
      const score = similarity(old.text, text)
      if (score > best) {
        best = score
        bestId = old.id
      }
    }

    if (bestId !== null && best >= WEAK) {
      const already = claims.get(bestId) ?? []
      // The first claimant keeps the id outright. A second claimant means the
      // sentence was split, and BOTH halves need traceable ancestry -- so the
      // second gets a fresh id whose lineage points back at the original.
      const id = already.length === 0 ? bestId : newId()
      claims.set(bestId, [...already, id])
      const kind: MatchKind = best === 1 ? 'same' : best >= STRONG ? 'edited' : 'rewritten'
      after.push({ id, text, kind })
    } else {
      after.push({ id: newId(), text, kind: 'new' })
    }
  }

  let splits = 0
  let merges = 0
  for (const [oldId, newIds] of claims) {
    lineage[oldId] = newIds
    if (newIds.length > 1) splits += newIds.length - 1
  }
  // An old sentence nothing claimed was deleted or merged away; record it with
  // an empty lineage so the id is accounted for rather than vanishing.
  for (const old of before) {
    if (!claims.has(old.id)) {
      lineage[old.id] = []
      merges += 1
    }
  }

  const affected: string[] = []
  const beforeById = new Map(before.map((s) => [s.id, s.text]))
  for (const s of after) {
    const prev = beforeById.get(s.id)
    if (prev === undefined || prev !== s.text) affected.push(s.id)
  }
  for (const [oldId, newIds] of Object.entries(lineage)) {
    if (newIds.length !== 1 && !affected.includes(oldId)) affected.push(oldId)
  }

  return { after, affected, lineage, splits, merges }
}

/**
 * Debounced edit reporter. Hold one per editable surface.
 *
 *   const reporter = new EditReporter('draft', (payload) => logger.log('text_edit', payload))
 *   reporter.onChange(newText)      // call on every keystroke; it debounces
 *   reporter.flushNow()             // on blur / submit
 */
export class EditReporter {
  private before: Sentence[]
  private timer: number | null = null
  private pending: string | null = null

  constructor(
    private readonly surface: string,
    private readonly emit: (payload: Record<string, unknown>) => void,
    initialText = '',
  ) {
    this.before = splitSentences(initialText).map((text) => ({ id: newId(), text }))
  }

  /** Current sentence list, for callers that need to render provenance. */
  sentences(): Sentence[] {
    return this.before
  }

  onChange(text: string): void {
    this.pending = text
    if (this.timer !== null) window.clearTimeout(this.timer)
    this.timer = window.setTimeout(() => this.flushNow(), DEBOUNCE_MS)
  }

  flushNow(): void {
    if (this.timer !== null) {
      window.clearTimeout(this.timer)
      this.timer = null
    }
    if (this.pending === null) return
    const text = this.pending
    this.pending = null

    const diff = alignSentences(this.before, text)
    if (diff.affected.length === 0 && diff.splits === 0 && diff.merges === 0) {
      this.before = diff.after
      return
    }

    this.emit({
      surface: this.surface,
      affected_sent_ids: diff.affected,
      lineage: diff.lineage,
      splits: diff.splits,
      merges: diff.merges,
      sentence_count: diff.after.length,
      char_count: text.length,
      // The changed sentences verbatim. This is the field that lets the
      // post-task interview quote what the participant wrote back at them.
      changed_text: diff.after
        .filter((s) => diff.affected.includes(s.id))
        .map((s) => ({ sent_id: s.id, kind: s.kind, text: s.text }))
        .slice(0, 20),
      // Counts by kind: proofreading and rethinking look very different here.
      kinds: diff.after.reduce<Record<string, number>>((acc, s) => {
        if (s.kind) acc[s.kind] = (acc[s.kind] ?? 0) + 1
        return acc
      }, {}),
    })
    this.before = diff.after
  }
}
