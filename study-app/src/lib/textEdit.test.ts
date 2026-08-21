/**
 * Sentence lineage across an edit (红线 #2, PR-3).
 *
 * What this file protects is the claim that `sent_id` survives editing: the
 * post-task probe asks about sentences by id, and the analysis asks which
 * planted sentence a participant changed. Both are answered by the lineage
 * this module produces, so a wrong claim here is not a display bug -- it
 * silently reattributes one sentence's history to another.
 */
import { describe, expect, it } from 'vitest'

import { alignSentences, EditReporter, similarity, type Sentence } from './textEdit'

const S = (id: string, text: string): Sentence => ({ id, text, kind: 'same' })

describe('claiming an old sentence', () => {
  it('keeps the id when a sentence is only reworded', () => {
    const before = [S('s1_0', 'The petitioner led the retrieval rebuild. [Exhibit C1, p.1]')]
    const { after, lineage } = alignSentences(
      before,
      'The petitioner led the retrieval re-build. [Exhibit C1, p.1]',
    )
    expect(after[0].id).toBe('s1_0')
    expect(after[0].kind).toBe('edited')
    expect(lineage['s1_0']).toEqual(['s1_0'])
  })

  it('forks the lineage when one sentence becomes two', () => {
    const before = [S(
      's2_0',
      'The petitioner led the retrieval rebuild that cut query latency by 40 percent across the platform. [Exhibit C1, p.1]',
    )]
    const { lineage } = alignSentences(
      before,
      'The petitioner led the retrieval rebuild. [Exhibit C1, p.1] ' +
        'That rebuild cut query latency by 40 percent across the platform. [Exhibit C1, p.1]',
    )
    // Both halves descend from the original, and the old id is never orphaned:
    // either half may still carry the planted error.
    expect(lineage['s2_0']).toHaveLength(2)
    expect(lineage['s2_0'][0]).toBe('s2_0')
  })

  it('refuses a loose claim on a sentence that is still there whole', () => {
    // The case from the walkthrough. A short sentence typed into the first
    // paragraph scored inside the `rewritten` band against a sentence two
    // paragraphs away -- short strings sharing a citation bracket and common
    // words score higher than they look -- while that sentence was still
    // present, untouched. Treating it as a split recorded a fork that never
    // happened; server-side, the same claim inherits `planted_id`.
    const kept = 'The arrangement is documented in the company’s organisational chart. [Exhibit B1, p.2]'
    const before = [
      S('s1_0', 'Northwind Data Systems is a data-infrastructure firm reporting $320M in revenue and 1,800 employees across eleven offices. [Exhibit B2, p.5]'),
      S('s3_1', kept),
    ]
    const typed = 'Separately, the record supports this. [Exhibit B2, p.5]'

    // Precondition: the score really is in the band this rule has to handle.
    expect(similarity(kept, typed)).toBeGreaterThan(0.35)
    expect(similarity(kept, typed)).toBeLessThan(0.92)

    const { after, lineage } = alignSentences(before, `${before[0].text} ${typed} ${kept}`)

    const typedRow = after.find((s) => s.text === typed)!
    expect(typedRow.kind).toBe('new')
    // s3_1 is claimed once, by the sentence that actually is s3_1.
    expect(lineage['s3_1']).toEqual(['s3_1'])
    expect(lineage['s3_1']).not.toContain(typedRow.id)
  })

  it('records a deleted sentence with an empty lineage rather than dropping it', () => {
    const before = [
      S('s1_0', 'The first sentence stays exactly as it was. [Exhibit B2, p.5]'),
      S('s1_1', 'The second sentence is about to be deleted entirely. [Exhibit D1, p.3]'),
    ]
    const { lineage } = alignSentences(before, before[0].text)
    expect(lineage['s1_1']).toEqual([])
  })
})

describe('the id space the log reports in', () => {
  it('reports lineage under the server sent_ids, not freshly minted ones', () => {
    // The join that makes the verification phase measurable: `text_edit` has to
    // name sentences the same way the draft snapshot and the probe do. Seeding
    // from plain text instead produced a lineage with zero overlap against
    // s1_0/s1_1/..., so "which planted sentence did they change" had no answer.
    const served = [
      { sent_id: 's1_0', text: 'Northwind reported $320M in revenue. [Exhibit B2, p.5]' },
      { sent_id: 's1_1', text: 'It was named vendor of the year. [Exhibit C1, p.1]' },
    ]
    const emitted: Record<string, unknown>[] = []
    const reporter = new EditReporter(
      'letter',
      (p) => emitted.push(p),
      served.map((s) => s.text).join(' '),
      served,
    )

    reporter.onChange(
      'Northwind reported $321M in revenue. [Exhibit B2, p.5] ' +
        'It was named vendor of the year. [Exhibit C1, p.1]',
    )
    reporter.flushNow()

    expect(emitted).toHaveLength(1)
    const lineage = emitted[0].lineage as Record<string, string[]>
    expect(Object.keys(lineage).sort()).toEqual(['s1_0', 's1_1'])
    expect(emitted[0].affected_sent_ids).toEqual(['s1_0'])
  })

  it('falls back to minted ids when no server sentences are supplied', () => {
    const emitted: Record<string, unknown>[] = []
    const reporter = new EditReporter('chat', (p) => emitted.push(p), 'One sentence here.')
    reporter.onChange('One sentence here. And a second one.')
    reporter.flushNow()
    expect(emitted).toHaveLength(1)
  })
})
