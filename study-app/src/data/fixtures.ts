/**
 * What is left of the M0 fixtures.
 *
 * Everything the study actually runs on now comes from the server
 * (`lib/material.ts`): tree, snippets, relations, letter text. What remains
 * here belongs to condition B, whose chat backend is deliberately not built --
 * B is the optional arm and its server side is deferred until condition C has
 * run to 24 sessions (see docs/日志手册 §8).
 *
 * When B is picked up, these go the same way as the rest: to the material
 * bundle and the prompt registry, with hashes.
 */

/** Page body the viewer prints when nothing is being pointed at. */
export const PAGE_BODY_FIXTURE =
  'The Director of AI Research reports directly to the Chief Technology Officer and oversees four research teams comprising 47 researchers.'

/** The bootstrap exchange the server will inject once B is built (BE-09). */
export const CHAT_FIXTURE = [
  {
    role: 'user' as const,
    text: 'Using the attached evidence, write the Leading or Critical Role section for Dr. Wei Li.',
  },
  {
    role: 'assistant' as const,
    lead: 'Here is a Leading or Critical Role section based on the evidence provided:',
    body: [
      '**I. Northwind Data Systems has a distinguished reputation.** Northwind Data Systems is a data-infrastructure firm reporting $320M in revenue and 1,800 employees across eleven offices [Exhibit B2, p.5]. The company was named Data Infrastructure Vendor of the Year for 2023 [Exhibit D1, p.1] …',
      '**II. Dr. Li performs a leading role within it.** As Director of AI Research, Dr. Li reports directly to the Chief Technology Officer and oversees four research teams comprising 47 researchers [Exhibit B1, p.2]. Dr. Li\u2019s SIGMOD 2022 Best Paper Award [Exhibit A3, p.1] further underscores his professional standing …',
    ],
    footnote: '(26 sentences with 14 citations — remainder omitted)',
  },
  { role: 'user' as const, text: 'Could the second paragraph bring out his decision authority more?' },
  {
    role: 'assistant' as const,
    lead: 'Certainly. The revised paragraph: As Director of AI Research, Dr. Li holds final approval authority over the division\u2019s $12M annual R&D budget [Exhibit B1, p.4], reports directly to the Chief Technology Officer …',
    body: [],
  },
]

export const DRAFT_FIXTURE = `I. Northwind Data Systems has a distinguished reputation

Northwind Data Systems is a data-infrastructure firm reporting $320M in revenue and 1,800 employees across eleven offices [Exhibit B2, p.5]. The company was named Data Infrastructure Vendor of the Year for 2023 [Exhibit D1, p.1], and its platform serves 13 of the 20 largest retailers in North America [Exhibit D1, p.3].

II. Dr. Li performs a leading role within it

As Director of AI Research, Dr. Li holds final approval authority over the division's $12M annual R&D budget [Exhibit B1, p.4], reports directly to the Chief Technology Officer, and oversees four research teams comprising 47 researchers [Exhibit B1, p.2]. The retrieval infrastructure rebuild that Dr. Li led reduced median query latency by 60% [Exhibit C1, p.1]. Dr. Li's SIGMOD 2022 Best Paper Award [Exhibit A3, p.1] and his invitation to the VLDB 2023 Program Committee [Exhibit E2, p.2] further underscore his professional standing.
`
