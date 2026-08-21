/**
 * The splitter agrees with the backend's (PR-3).
 *
 * sentences.ts and backend/app/core/sentences.py are two implementations of
 * one rule, and the rule is what `sent_id` means. If they disagree, the client
 * reports lineage over one segmentation while the server computes the probe's
 * candidate pool over another, and the two id spaces stop describing the same
 * sentences -- silently, because each half is internally consistent.
 *
 * backend/tests/fixtures/sentences.json is the shared contract. The Python
 * suite reads it; until now nothing on this side did, so "both must produce
 * exactly these splits" was enforced against one of the two.
 */
import { describe, expect, it } from 'vitest'

import fixtures from '../../../backend/tests/fixtures/sentences.json'
import { splitSentences } from './sentences'

interface Case {
  why?: string
  text: string
  expect: string[]
}

describe('the shared segmentation contract', () => {
  const cases = (fixtures as { cases: Case[] }).cases

  it('has cases to check', () => {
    expect(cases.length).toBeGreaterThan(0)
  })

  it.each(cases.map((c, i) => [i, c.why ?? `case ${i}`, c] as const))(
    'case %i: %s',
    (_i, _why, testCase) => {
      expect(splitSentences(testCase.text)).toEqual(testCase.expect)
    },
  )
})
