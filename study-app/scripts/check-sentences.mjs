/**
 * Checks that lib/sentences.ts produces exactly the segmentation the shared
 * contract specifies -- the same JSON file backend/tests/test_sentences.py
 * checks the Python implementation against.
 *
 * This exists because a divergence between the two would be silent. The browser
 * computes the sent_ids that go into the event log; the offline analysis
 * recomputes them in Python. If they disagreed, nothing would raise -- the
 * reconstruction would just fail to line up with the log, and we would find out
 * during analysis, after the sessions are gone.
 *
 *     node scripts/check-sentences.mjs
 *
 * Run by `npm test` and in CI.
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const contractPath = resolve(here, '../../backend/tests/fixtures/sentences.json')

// lib/sentences.ts is dependency-free TypeScript whose only non-JS syntax is
// type annotations, so it is transpiled here with a minimal strip rather than
// pulling a bundler into a check that has to stay trivially runnable.
const tsSource = readFileSync(resolve(here, '../src/lib/sentences.ts'), 'utf8')
const js = tsSource
  .replace(/^export const CITE_RE/m, 'const CITE_RE')
  .replace(/^export function/gm, 'function')
  .replace(/: string\[\]/g, '')
  .replace(/: string\b/g, '')
  .replace(/: number\b/g, '')
  .replace(/: boolean\b/g, '')
  .replace(/: RegExpExecArray \| null/g, '')
  .replace(/^import .*$/gm, '')

const module = new Function(`${js}; return { splitSentences, countSentences, countCitations }`)()

const contract = JSON.parse(readFileSync(contractPath, 'utf8'))
let failures = 0

for (const testCase of contract.cases) {
  const got = module.splitSentences(testCase.text)
  const same =
    got.length === testCase.expect.length &&
    got.every((s, i) => s === testCase.expect[i])
  if (!same) {
    failures++
    console.error(`FAIL  ${testCase.why}`)
    console.error(`  input    ${JSON.stringify(testCase.text)}`)
    console.error(`  expected ${JSON.stringify(testCase.expect)}`)
    console.error(`  got      ${JSON.stringify(got)}`)
  }
}

const total = contract.cases.length
if (failures) {
  console.error(
    `\n${failures}/${total} case(s) differ from the shared contract.\n` +
      'The browser and the analysis pipeline must segment identically -- fix ' +
      'both src/lib/sentences.ts and backend/app/core/sentences.py.',
  )
  process.exit(1)
}
console.log(`sentences: ${total}/${total} cases match the shared contract`)
