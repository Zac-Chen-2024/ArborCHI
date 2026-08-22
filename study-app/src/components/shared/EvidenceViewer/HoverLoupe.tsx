/**
 * Hovering the located passage brings it to the middle of the screen.
 *
 * Carried over from the product frontend's BBoxLightbox (§7.5): a portal, fixed
 * position, and a 300ms flight from the box's own rectangle to the centre of
 * the viewport. In a 300px-wide panel the cited passage is a few millimetres
 * tall, and reading it is the task -- so the reading aid has to use the whole
 * screen, not the corner of the panel it started in.
 *
 * Three things it deliberately is not:
 *
 * - It is not the magnifier. It opens on hover, so it cannot be a measured act:
 *   `lightbox_open` and its dwell would then record the pointer passing over
 *   something rather than a decision to check. This reports nothing at all.
 * - It shows the cited passage with a little page context and NO neighbouring
 *   candidate boxes. The product version drew the alternatives around a
 *   snippet; here that would be the interface pointing at what else might fit,
 *   which is the judgement being measured (红线, C-11).
 * - It never takes the pointer. `pointer-events: none` throughout: moving onto
 *   it would mean leaving the box, which would dismiss it.
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

import type { PageImage } from '../../../lib/pageImage'

interface Props {
  page: PageImage
  /** 0-1000 normalised, the same space the box uses (红线 #8). */
  bbox: [number, number, number, number] | number[]
  /** Where it starts from, so it can fly out of the box the pointer is on. */
  origin: DOMRect
}

/** Page-units of context kept around the passage, as in the product version. */
const CONTEXT_PAD = 40
/** Share of the viewport the enlarged passage may occupy. */
const MAX_W = 0.62
const MAX_H = 0.62
const MIN_W = 320

export function HoverLoupe({ page, bbox, origin }: Props) {
  // Two frames: mount at the origin rect, then move to centre, so the browser
  // has something to transition from.
  const [flown, setFlown] = useState(false)
  useEffect(() => {
    const id = requestAnimationFrame(() => requestAnimationFrame(() => setFlown(true)))
    return () => cancelAnimationFrame(id)
  }, [])

  const [x1, y1, x2, y2] = bbox
  const cx1 = Math.max(0, x1 - CONTEXT_PAD)
  const cy1 = Math.max(0, y1 - CONTEXT_PAD)
  const cx2 = Math.min(1000, x2 + CONTEXT_PAD)
  const cy2 = Math.min(1000, y2 + CONTEXT_PAD)
  const cw = (cx2 - cx1) / 10
  const ch = (cy2 - cy1) / 10
  if (cw <= 0 || ch <= 0) return null

  // Crop shape in real pixels, so the enlargement keeps the page's proportions.
  const cropW = (cw / 100) * page.w
  const cropH = (ch / 100) * page.h
  const aspect = cropW / cropH

  let w = Math.min(window.innerWidth * MAX_W, cropW * 2.2)
  let h = w / aspect
  if (h > window.innerHeight * MAX_H) {
    h = window.innerHeight * MAX_H
    w = h * aspect
  }
  if (w < MIN_W) {
    w = Math.min(MIN_W, window.innerWidth * MAX_W)
    h = w / aspect
  }

  const style: React.CSSProperties = flown
    ? {
        left: (window.innerWidth - w) / 2,
        top: (window.innerHeight - h) / 2,
        width: w,
        height: h,
        opacity: 1,
      }
    : {
        left: origin.left,
        top: origin.top,
        width: origin.width,
        height: origin.height,
        opacity: 0,
      }

  return createPortal(
    <div className="hover-loupe" style={style} aria-hidden="true">
      <div className="hover-loupe-crop">
        <img
          src={page.url}
          alt=""
          draggable={false}
          style={{
            width: `${(100 / cw) * 100}%`,
            height: `${(100 / ch) * 100}%`,
            left: `${-(cx1 / 10 / cw) * 100}%`,
            top: `${-(cy1 / 10 / ch) * 100}%`,
          }}
        />
        {/* The passage itself, marked inside its context so the enlargement
            still says which part was cited. */}
        <div
          className="hover-loupe-box"
          style={{
            left: `${((x1 - cx1) / (cx2 - cx1)) * 100}%`,
            top: `${((y1 - cy1) / (cy2 - cy1)) * 100}%`,
            width: `${((x2 - x1) / (cx2 - cx1)) * 100}%`,
            height: `${((y2 - y1) / (cy2 - cy1)) * 100}%`,
          }}
        />
      </div>
    </div>,
    document.body,
  )
}
