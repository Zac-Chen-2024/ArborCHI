/**
 * The probe's citation parser (BE-13, FS-09).
 *
 * Small and load-bearing: its output decides whether the "View source" button
 * renders at all, and whether a participant could open the evidence is one of
 * the measures the probe collects. When it failed to parse, nothing errored --
 * the button was simply absent, and `source_opened` was false for every item in
 * every session.
 */
import { describe, expect, it } from 'vitest'

import { parseCitation } from './ProbeRunner'

describe('parsing a citation', () => {
  it('reads the exhibit numbering a real filing uses', () => {
    // The brief numbers its exhibits C-1, C-7, G-5. This is the case that broke:
    // the id class allowed no hyphen, so every citation in the real bundle
    // failed to parse and the source button disappeared from the whole phase.
    expect(parseCitation('[Exhibit C-1, p.2]')).toEqual({ exhibit: 'C-1', page: 2 })
    expect(parseCitation('[Exhibit G-5, p.3]')).toEqual({ exhibit: 'G-5', page: 3 })
  })

  it('still reads ids without a hyphen', () => {
    expect(parseCitation('[Exhibit B2, p.5]')).toEqual({ exhibit: 'B2', page: 5 })
  })

  it('finds the citation inside a sentence', () => {
    expect(
      parseCitation('The petitioner was appointed Deputy Director. [Exhibit C-1, p.2]'),
    ).toEqual({ exhibit: 'C-1', page: 2 })
  })

  it('tolerates a space after p.', () => {
    expect(parseCitation('[Exhibit C-3, p. 12]')).toEqual({ exhibit: 'C-3', page: 12 })
  })

  it('returns null when there is nothing to parse', () => {
    expect(parseCitation('No citation here.')).toBeNull()
    expect(parseCitation('[Exhibit , p.2]')).toBeNull()
  })
})
