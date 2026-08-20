/**
 * M0 static data -- lifted verbatim from the mockups so the two condition
 * screens can be checked against them pixel for pixel before any real material
 * bundle exists.
 *
 * This file dies at M5, when `backend/study_materials/case_v1/` becomes the
 * only source of exhibits, snippets, relations and pre-generated text. Nothing
 * outside `data/` may import it after that; keep the shapes here identical to
 * the bundle's so the swap is a one-line change in the loader.
 *
 * Note what is NOT here, and must never be: distractor flags, probe ground
 * truth, or any strength/quality score (红线 #5, C-14). A snippet the tree
 * points at looks exactly like every other snippet.
 */

export interface Snippet {
  id: string
  sub: string
  ex: string
  page: number
  pages: number
  label: string
  docTitle: string
  docSubtitle: string
  text: string
  /** Plain factual triples for the relations panel. No evaluative field. */
  rel: [string, string, string][]
}

export interface Exhibit {
  id: string
  pages: number
  title: string
}

// NOTE: the mockup's exhibit strip lists six exhibits (A3 B1 B2 C1 C2 E2) but
// its evidence chips cite a seventh, D1 -- snippets c2 and c3 both point at it.
// That is a data slip in the mockup, not a design decision: without D1 in this
// list, clicking either chip navigates to an exhibit that does not exist. D1 is
// included here so the fixture is self-consistent, which makes the header read
// "7 exhibits" rather than the mockup's 6.
export const EXHIBITS: Exhibit[] = [
  { id: 'A3', pages: 2, title: 'ACM SIGMOD · Best Paper Award' },
  { id: 'B1', pages: 6, title: 'Organisational chart and delegation of authority' },
  { id: 'B2', pages: 8, title: 'Annual Report 2023' },
  { id: 'C1', pages: 3, title: 'Letter of recommendation · Marcus Reed' },
  { id: 'C2', pages: 5, title: 'Internal memorandum · Project Atlas' },
  { id: 'D1', pages: 4, title: 'Data Infrastructure Review · Vendor of the Year' },
  { id: 'E2', pages: 4, title: 'VLDB 2023 · Programme committee invitation' },
]

export const SNIPPETS: Record<string, Snippet> = {
  c1: {
    id: 'c1', sub: 's1', ex: 'B2', page: 5, pages: 8,
    label: 'Revenue $320M · 1,800 employees',
    docTitle: 'NORTHWIND DATA SYSTEMS', docSubtitle: 'Annual Report 2023',
    text: 'Global revenue reached $320M in FY2023, with 1,800 employees across eleven offices.',
    rel: [
      ['Northwind Data Systems', 'annual revenue', '$320M'],
      ['Northwind Data Systems', 'employees', '1,800'],
      ['Northwind Data Systems', 'offices', '11'],
    ],
  },
  c2: {
    id: 'c2', sub: 's1', ex: 'D1', page: 1, pages: 4,
    label: 'Data Infrastructure Vendor of the Year',
    docTitle: 'DATA INFRASTRUCTURE REVIEW', docSubtitle: 'Vendor of the Year · 2023',
    text: 'Northwind Data Systems was named Data Infrastructure Vendor of the Year for 2023.',
    rel: [
      ['Northwind Data Systems', 'named', 'Data Infrastructure Vendor of the Year'],
      ['Awarded by', 'is', 'Data Infrastructure Review'],
    ],
  },
  c3: {
    id: 'c3', sub: 's2', ex: 'D1', page: 3, pages: 4,
    label: '13 of the 20 largest retailers in North America',
    docTitle: 'DATA INFRASTRUCTURE REVIEW', docSubtitle: 'Market Coverage',
    text: 'Its platform serves 13 of the 20 largest retailers in North America.',
    rel: [['Northwind Data Systems', 'serves', '13 of the 20 largest North American retailers']],
  },
  c4: {
    id: 'c4', sub: 's3', ex: 'B1', page: 2, pages: 6,
    label: 'Reports to the CTO · 4 teams, 47 people',
    docTitle: 'NORTHWIND DATA SYSTEMS',
    docSubtitle: 'Organizational Chart · Research & Development',
    text: 'The Director of AI Research reports directly to the Chief Technology Officer and oversees four research teams comprising 47 researchers.',
    rel: [
      ['Dr. Wei Li', 'holds title', 'Director of AI Research'],
      ['AI Research division', 'reports to', 'Marcus Reed · CTO'],
      ['Dr. Wei Li', 'manages', '4 teams · 47 researchers'],
    ],
  },
  c5: {
    id: 'c5', sub: 's4', ex: 'B1', page: 4, pages: 6,
    label: 'Final approval over a $12M budget',
    docTitle: 'NORTHWIND DATA SYSTEMS', docSubtitle: 'Delegation of Authority',
    text: 'Final approval authority over the division’s $12M annual R&D budget rests with the Director of AI Research.',
    rel: [['Dr. Wei Li', 'approval authority over', '$12M annual division budget']],
  },
  c6: {
    id: 'c6', sub: 's5', ex: 'C1', page: 1, pages: 3,
    label: 'Retrieval rebuild cut query latency 60%',
    docTitle: 'LETTER OF RECOMMENDATION',
    docSubtitle: 'Marcus Reed · Chief Technology Officer',
    text: 'The retrieval infrastructure rebuild that Dr. Li led reduced median query latency by 60% across our platform.',
    rel: [
      ['Dr. Wei Li', 'led', 'retrieval infrastructure rebuild'],
      ['That project', 'resulted in', '60% lower median query latency'],
      ['Recommender', 'is', 'Marcus Reed · CTO'],
    ],
  },
  c7: {
    id: 'c7', sub: 's5', ex: 'C2', page: 3, pages: 5,
    label: 'Led Project Atlas · delivered 2022 Q3',
    docTitle: 'INTERNAL MEMORANDUM', docSubtitle: 'Project Atlas · Delivery Review',
    text: 'Project Atlas was initiated and led by Dr. Li, and was delivered in Q3 2022.',
    rel: [
      ['Dr. Wei Li', 'initiated and led', 'Project Atlas'],
      ['Project Atlas', 'delivered', '2022 Q3'],
    ],
  },
  c8: {
    id: 'c8', sub: 's6', ex: 'A3', page: 1, pages: 2,
    label: 'SIGMOD 2022 Best Paper Award',
    docTitle: 'ACM SIGMOD', docSubtitle: 'Best Paper Award · 2022',
    text: 'Best Paper Award presented to Dr. Wei Li et al. for “Efficient Query Processing in Large-Scale Distributed Databases.”',
    rel: [
      ['Dr. Wei Li', 'received', 'SIGMOD 2022 Best Paper Award'],
      ['Awarded by', 'is', 'ACM SIGMOD'],
    ],
  },
  c9: {
    id: 'c9', sub: 's6', ex: 'E2', page: 2, pages: 3,
    label: 'VLDB 2023 programme committee invitation',
    docTitle: 'VLDB 2023', docSubtitle: 'Program Committee Invitation',
    text: 'We invite Dr. Wei Li to serve on the Program Committee for VLDB 2023.',
    rel: [['Dr. Wei Li', 'invited to serve on', 'VLDB 2023 Program Committee']],
  },
}

/**
 * Body text of the page the viewer shows by default. It is material content
 * (English exhibit OCR), not interface chrome, so it lives in the data layer
 * and never goes through i18n -- a zh session reads the same exhibit.
 */
export const PAGE_BODY_FIXTURE =
  'The Director of AI Research reports directly to the Chief Technology Officer and oversees four research teams comprising 47 researchers.'

export type NodeState = 'proposed' | 'accepted' | 'edited' | 'removed'

export interface SubArgument {
  id: string
  title: string
  state: NodeState
  renamed?: boolean
  snippetIds: string[]
}

export interface Argument {
  id: string
  index: string
  title: string
  rationale: string
  subs: SubArgument[]
}

export const TREE: Argument[] = [
  {
    id: 'a1', index: '①', title: 'The organisation has a distinguished reputation',
    rationale: 'Establish the standing of the organisation before the individual role',
    subs: [
      { id: 's1', title: 'Scale and market position', state: 'accepted', snippetIds: ['c1', 'c2'] },
      { id: 's2', title: 'Industry recognition and client coverage', state: 'proposed', snippetIds: ['c3'] },
    ],
  },
  {
    id: 'a2', index: '②', title: 'The petitioner performs a leading role within it',
    rationale: 'Argue hierarchical position, decision authority and actual impact',
    subs: [
      { id: 's3', title: 'Position in the hierarchy and reporting line', state: 'accepted', snippetIds: ['c4'] },
      { id: 's4', title: 'Decision and resource authority', state: 'proposed', snippetIds: ['c5'] },
      { id: 's5', title: 'Quantified impact of the leadership', state: 'accepted', renamed: true, snippetIds: ['c6', 'c7'] },
      { id: 's6', title: 'Academic honours corroborating professional standing', state: 'proposed', snippetIds: ['c8', 'c9'] },
    ],
  },
]

/** Snippets not assigned to any node yet (C-06). */
export const UNUSED_SNIPPETS = [{ id: 'u1', ex: 'E2', page: 4, label: 'Conference registration figures' }]

/** The person the relations panel offers other mentions of. */
export const FOCUS_ENTITY = 'Dr. Wei Li'
export const OTHER_MENTIONS = ['A3 p.1', 'C1 p.1', 'C2 p.3', 'E2 p.2']

export interface LetterParagraph {
  sub: string
  /** Rendered text, or null for a paragraph that has not been generated. */
  text: string | null
  /** Skeleton bar widths for an ungenerated paragraph, as in the mockup. */
  bars?: number[]
  citeSnippetId?: string
}

export const LETTER: { argId: string; heading: string; paras: LetterParagraph[] }[] = [
  {
    argId: 'a1',
    heading: '① The organisation has a distinguished reputation',
    paras: [
      {
        sub: 's1',
        text: 'Northwind Data Systems is a data-infrastructure firm reporting $320M in revenue and 1,800 employees across eleven offices.',
        citeSnippetId: 'c1',
      },
      { sub: 's2', text: null, bars: [94, 88, 76] },
    ],
  },
  {
    argId: 'a2',
    heading: '② The petitioner performs a leading role within it',
    paras: [
      {
        sub: 's3',
        text: 'As Director of AI Research at Northwind Data Systems, Dr. Li reported directly to the Chief Technology Officer and oversaw four research teams comprising 47 researchers.',
        citeSnippetId: 'c4',
      },
      { sub: 's4', text: null, bars: [92, 84, 70] },
      { sub: 's5', text: null, bars: [95, 88, 91, 74] },
      { sub: 's6', text: null, bars: [90, 82, 68] },
    ],
  },
]

/** Condition B: the bootstrap exchange the server injects (BE-09). */
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
      '**II. Dr. Li performs a leading role within it.** As Director of AI Research, Dr. Li reports directly to the Chief Technology Officer and oversees four research teams comprising 47 researchers [Exhibit B1, p.2]. Dr. Li’s SIGMOD 2022 Best Paper Award [Exhibit A3, p.1] further underscores his professional standing …',
    ],
    footnote: '(26 sentences with 14 citations — remainder omitted)',
  },
  { role: 'user' as const, text: 'Could the second paragraph bring out his decision authority more?' },
  {
    role: 'assistant' as const,
    lead: 'Certainly. The revised paragraph: As Director of AI Research, Dr. Li holds final approval authority over the division’s $12M annual R&D budget [Exhibit B1, p.4], reports directly to the Chief Technology Officer …',
    body: [],
  },
]

export const DRAFT_FIXTURE = `I. Northwind Data Systems has a distinguished reputation

Northwind Data Systems is a data-infrastructure firm reporting $320M in revenue and 1,800 employees across eleven offices [Exhibit B2, p.5]. The company was named Data Infrastructure Vendor of the Year for 2023 [Exhibit D1, p.1], and its platform serves 13 of the 20 largest retailers in North America [Exhibit D1, p.3].

II. Dr. Li performs a leading role within it

As Director of AI Research, Dr. Li holds final approval authority over the division's $12M annual R&D budget [Exhibit B1, p.4], reports directly to the Chief Technology Officer, and oversees four research teams comprising 47 researchers [Exhibit B1, p.2]. The retrieval infrastructure rebuild that Dr. Li led reduced median query latency by 60% [Exhibit C1, p.1]. Dr. Li's SIGMOD 2022 Best Paper Award [Exhibit A3, p.1] and his invitation to the VLDB 2023 Program Committee [Exhibit E2, p.2] further underscore his professional standing.
`
