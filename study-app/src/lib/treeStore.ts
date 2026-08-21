/**
 * The working argument tree and every operation on it (C-03, C-04).
 *
 * ## Why the logging lives here
 *
 * The requirement is that EVERY node operation in the organisation phase
 * records its before and after state. The reliable way to meet that is not to
 * remember to call `log()` next to each button, but to make the mutation layer
 * the only way to change the tree and have it log on the way through. A new
 * operation added later gets logging by construction; a button that forgets is
 * not a button that can change anything.
 *
 * So: components call `useTree.getState().rename(...)`, never `setState` on the
 * tree directly. `apply()` is the single choke point.
 *
 * ## What before/after contain
 *
 * The full node -- title, parent, evidence, state -- not a delta. A delta is
 * only interpretable against a reconstruction of everything that came before
 * it, and reconstruction is exactly what breaks when one event is missing. The
 * cost is a few hundred bytes per operation; the benefit is that any single
 * event in the log is independently readable, which is what the post-task
 * interview needs ("at 12:04 you moved X out from under Y -- why?").
 */

import { create } from 'zustand'

import { api } from './api'
import { logger } from './logger'
import type { Argument, NodeState, SubArgument, Tree } from './material'

export type NodeStateKind = 'proposed' | 'accepted' | 'edited' | 'removed'

export interface WorkingSub extends SubArgument {
  state: NodeStateKind
  /** True once the participant has changed the title. Shown as a small tag. */
  renamed?: boolean
}

export interface WorkingArg extends Omit<Argument, 'subs'> {
  subs: WorkingSub[]
}

/** A node as the log records it: everything, not a delta. */
interface NodeSnapshot {
  node_id: string
  title: string
  parent_id: string
  parent_title: string
  snippet_ids: string[]
  state: NodeStateKind
  index_in_parent: number
}

export type TreeOp =
  | 'rename' | 'split' | 'merge_up' | 'move' | 'promote' | 'remove' | 'create'
  | 'assign' | 'unassign' | 'reorder'

interface TreeStore {
  args: WorkingArg[]
  loaded: boolean

  load: (tree: Tree) => void
  /** Replace the working tree with one restored from the server. */
  hydrate: (args: WorkingArg[]) => void

  rename: (nodeId: string, title: string) => void
  splitNode: (nodeId: string) => void
  mergeUp: (nodeId: string) => void
  moveTo: (nodeId: string, parentId: string) => void
  promote: (nodeId: string) => void
  remove: (nodeId: string) => void
  addSub: (parentId: string) => void
  setState: (nodeId: string, state: NodeStateKind, via: string) => void
  acceptAll: () => void
  assign: (nodeId: string, snippetId: string) => void
  unassign: (nodeId: string, snippetId: string) => void

  /** What `/generate` is called with. */
  nodeStates: () => Record<string, NodeState>
}

// ---------------------------------------------------------------------------

let created = 0
const newNodeId = () => `n_${Date.now().toString(36)}_${(created++).toString(36)}`

function findNode(args: WorkingArg[], nodeId: string): NodeSnapshot | null {
  for (const arg of args) {
    const i = arg.subs.findIndex((s) => s.id === nodeId)
    if (i !== -1) {
      const sub = arg.subs[i]
      return {
        node_id: sub.id,
        title: sub.title,
        parent_id: arg.id,
        parent_title: arg.title,
        snippet_ids: [...sub.snippet_ids],
        state: sub.state,
        index_in_parent: i,
      }
    }
  }
  return null
}

export const useTree = create<TreeStore>((set, get) => {
  /**
   * The choke point. Runs `mutate`, then logs the operation with the node's
   * state on both sides of it. Nothing else in this module writes `args`.
   */
  const apply = (
    op: TreeOp,
    nodeId: string,
    mutate: (args: WorkingArg[]) => WorkingArg[],
    extra: Record<string, unknown> = {},
  ) => {
    const before = findNode(get().args, nodeId)
    const next = mutate(structuredClone(get().args))
    const after = findNode(next, nodeId)
    set({ args: next })

    logger.log('tree_op', {
      op,
      node_id: nodeId,
      // The title on whichever side exists: for a create there is no before,
      // for a remove there is no after, and the event should still say which
      // node it was about in words.
      node_title: after?.title ?? before?.title,
      before,
      after,
      ...extra,
    })
  }

  return {
    args: [],
    loaded: false,

    hydrate(args) {
      // No log entry: this is the same tree the participant already built,
      // arriving back from storage. The operations that produced it were
      // logged when they happened.
      set({ loaded: true, args })
    },

    load(tree) {
      set({
        loaded: true,
        args: tree.arguments.map((a) => ({
          ...a,
          // Everything the machine proposed starts unreviewed. Accepting is
          // an act the log records; arriving pre-accepted would erase it.
          subs: a.subs.map((s) => ({ ...s, state: 'proposed' as const })),
        })),
      })
    },

    rename(nodeId, title) {
      const before = findNode(get().args, nodeId)
      if (!before || before.title === title) return
      apply('rename', nodeId, (args) => {
        for (const arg of args) {
          const sub = arg.subs.find((s) => s.id === nodeId)
          if (sub) {
            sub.title = title
            sub.renamed = true
            sub.state = 'edited'
          }
        }
        return args
      }, { from_title: before.title, to_title: title })
    },

    splitNode(nodeId) {
      const newId = newNodeId()
      apply('split', nodeId, (args) => {
        for (const arg of args) {
          const i = arg.subs.findIndex((s) => s.id === nodeId)
          if (i === -1) continue
          const original = arg.subs[i]
          // The evidence is divided rather than duplicated: two nodes citing
          // the same snippet would make "which node is this evidence for"
          // unanswerable in the analysis.
          const half = Math.ceil(original.snippet_ids.length / 2)
          const second: WorkingSub = {
            id: newId,
            title: `${original.title} (2)`,
            snippet_ids: original.snippet_ids.slice(half),
            state: 'edited',
          }
          original.snippet_ids = original.snippet_ids.slice(0, half)
          original.state = 'edited'
          arg.subs.splice(i + 1, 0, second)
        }
        return args
      }, { new_node_id: newId })
    },

    mergeUp(nodeId) {
      const before = findNode(get().args, nodeId)
      if (!before || before.index_in_parent === 0) return
      // The previous sibling WITHIN THE SAME PARENT -- not the previous node
      // in a flattened walk of the whole tree, which would name a node from a
      // different argument as the merge target.
      const parent = get().args.find((a) => a.id === before.parent_id)
      const target = parent?.subs[before.index_in_parent - 1]
      apply('merge_up', nodeId, (args) => {
        for (const arg of args) {
          const i = arg.subs.findIndex((s) => s.id === nodeId)
          if (i <= 0) continue
          const previous = arg.subs[i - 1]
          previous.snippet_ids = [
            ...previous.snippet_ids,
            ...arg.subs[i].snippet_ids.filter((s) => !previous.snippet_ids.includes(s)),
          ]
          previous.state = 'edited'
          arg.subs.splice(i, 1)
        }
        return args
      }, { merged_into: target?.id, merged_into_title: target?.title })
    },

    moveTo(nodeId, parentId) {
      const before = findNode(get().args, nodeId)
      if (!before || before.parent_id === parentId) return
      apply('move', nodeId, (args) => {
        let moved: WorkingSub | null = null
        for (const arg of args) {
          const i = arg.subs.findIndex((s) => s.id === nodeId)
          if (i !== -1) {
            moved = arg.subs.splice(i, 1)[0]
          }
        }
        if (moved) {
          moved.state = 'edited'
          args.find((a) => a.id === parentId)?.subs.push(moved)
        }
        return args
      }, {
        from_parent: before.parent_id,
        from_parent_title: before.parent_title,
        to_parent: parentId,
        to_parent_title: get().args.find((a) => a.id === parentId)?.title,
      })
    },

    promote(nodeId) {
      const before = findNode(get().args, nodeId)
      if (!before) return
      apply('promote', nodeId, (args) => {
        for (const arg of args) {
          const i = arg.subs.findIndex((s) => s.id === nodeId)
          if (i === -1) continue
          const [sub] = arg.subs.splice(i, 1)
          args.push({
            id: `a_${sub.id}`,
            index: `${args.length + 1}`,
            title: sub.title,
            rationale: '',
            subs: [{ ...sub, state: 'edited' }],
          })
        }
        return args
      }, { from_parent: before.parent_id, from_parent_title: before.parent_title })
    },

    remove(nodeId) {
      apply('remove', nodeId, (args) => {
        for (const arg of args) {
          const sub = arg.subs.find((s) => s.id === nodeId)
          // Marked, not deleted: the node has to stay in `nodeStates` so the
          // server is told it was removed, and the log keeps a coherent
          // before/after for anything that touches it afterwards.
          if (sub) sub.state = 'removed'
        }
        return args
      })
    },

    addSub(parentId) {
      const newId = newNodeId()
      apply('create', newId, (args) => {
        args.find((a) => a.id === parentId)?.subs.push({
          id: newId,
          title: '',
          snippet_ids: [],
          state: 'edited',
        })
        return args
      }, { parent_id: parentId,
           parent_title: get().args.find((a) => a.id === parentId)?.title })
    },

    setState(nodeId, state, via) {
      const before = findNode(get().args, nodeId)
      if (!before || before.state === state) return
      set({
        args: structuredClone(get().args).map((arg) => ({
          ...arg,
          subs: arg.subs.map((s) => (s.id === nodeId ? { ...s, state } : s)),
        })),
      })
      // node_state, not tree_op: accepting a proposal is not a structural
      // edit, and the analysis counts the two separately.
      logger.log('node_state', {
        node_id: nodeId,
        node_title: before.title,
        from: before.state,
        to: state,
        via,
      })
    },

    acceptAll() {
      // Logged per node rather than once: the question "how many nodes did
      // they accept without ever looking at them" needs a per-node record,
      // and a single aggregate event would erase it.
      for (const arg of get().args) {
        for (const sub of arg.subs) {
          if (sub.state === 'proposed') get().setState(sub.id, 'accepted', 'accept_all')
        }
      }
    },

    assign(nodeId, snippetId) {
      apply('assign', nodeId, (args) => {
        for (const arg of args) {
          const sub = arg.subs.find((s) => s.id === nodeId)
          if (sub && !sub.snippet_ids.includes(snippetId)) {
            sub.snippet_ids.push(snippetId)
            sub.state = 'edited'
          }
        }
        return args
      }, { snippet_id: snippetId })
    },

    unassign(nodeId, snippetId) {
      apply('unassign', nodeId, (args) => {
        for (const arg of args) {
          const sub = arg.subs.find((s) => s.id === nodeId)
          if (sub) {
            sub.snippet_ids = sub.snippet_ids.filter((s) => s !== snippetId)
            sub.state = 'edited'
          }
        }
        return args
      }, { snippet_id: snippetId })
    },

    nodeStates() {
      const out: Record<string, NodeState> = {}
      for (const arg of get().args) {
        for (const sub of arg.subs) {
          out[sub.id] = {
            title: sub.title,
            parent_id: arg.id,
            snippet_ids: [...sub.snippet_ids],
            state: sub.state,
          }
        }
      }
      return out
    },
  }
})


// ---------------------------------------------------------------------------
// Durability
// ---------------------------------------------------------------------------

/**
 * The working tree, kept on the server.
 *
 * It used to live only here, in memory. A reload -- a refresh, a crash, a stray
 * Back button -- put every sub-argument back to `proposed` and undid every
 * rename and every move, and the next generation ran against the machine's
 * original proposal. Nothing said so: the letter still rendered, the phase
 * still advanced, and the log still contained every `tree_op` the participant
 * had performed. The session looked complete. In the verification phase it was
 * worse than losing work, because the letter under review was silently rebuilt
 * from a tree the participant had not organised.
 *
 * Debounced rather than per-operation: a rename fires on every keystroke, and
 * the interesting artefact is the settled tree, not each intermediate one. The
 * log already holds the intermediate ones.
 */
const PERSIST_DEBOUNCE_MS = 800
let persistTimer: number | null = null
let persistMaterialId = ''

/** Told by the workspace which bundle the current tree belongs to. */
export function setTreeMaterial(materialId: string): void {
  persistMaterialId = materialId
}

function schedulePersist(args: WorkingArg[]): void {
  if (persistTimer !== null) window.clearTimeout(persistTimer)
  persistTimer = window.setTimeout(() => {
    persistTimer = null
    // Failure is survivable and must never interrupt the task: the next
    // mutation schedules another attempt, and the log of what was done is
    // already safe by its own route.
    void api.put('/tree', { tree: args, material_id: persistMaterialId }).catch(() => {})
  }, PERSIST_DEBOUNCE_MS)
}

useTree.subscribe((state, prev) => {
  if (!state.loaded || state.args === prev.args) return
  schedulePersist(state.args)
})

/** Flush a pending save immediately -- used before leaving a phase. */
export async function flushTree(): Promise<void> {
  if (persistTimer === null) return
  window.clearTimeout(persistTimer)
  persistTimer = null
  try {
    await api.put('/tree', { tree: useTree.getState().args, material_id: persistMaterialId })
  } catch {
    /* the next mutation retries */
  }
}

export interface StoredTree {
  tree: WorkingArg[] | null
  material_id: string | null
  saved_at: string | null
}

export async function fetchStoredTree(): Promise<WorkingArg[] | null> {
  try {
    const res = await api.get<StoredTree>('/tree')
    return res.tree?.length ? res.tree : null
  } catch {
    return null
  }
}
