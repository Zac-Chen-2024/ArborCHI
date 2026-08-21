/**
 * Exhibit page images, fetched with the participant's token.
 *
 * `<img src=...>` cannot carry an Authorization header, and the obvious
 * workaround -- putting the token in the URL -- writes a credential into every
 * image request, where it lands in referrers, history and any proxy log. So the
 * bytes are fetched like any other API call and handed to the `<img>` as an
 * object URL instead.
 *
 * Cached by (exhibit, page) for the life of the tab. A participant turns back
 * to the same exhibit repeatedly -- that is the task -- and re-downloading a
 * page each time would put load time inside the measurement.
 */
import { getToken } from './api'

export interface PageImage {
  url: string
  /** Natural pixel size, which the hover loupe needs to crop a region to shape. */
  w: number
  h: number
}

const cache = new Map<string, Promise<PageImage>>()

function key(exhibit: string, page: number): string {
  return `${exhibit}/${page}`
}

function measure(url: string): Promise<PageImage> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve({ url, w: img.naturalWidth, h: img.naturalHeight })
    img.onerror = () => reject(new Error('decode failed'))
    img.src = url
  })
}

/** One page, with its natural size. Rejects if the page is not available. */
export function pageImage(exhibit: string, page: number): Promise<PageImage> {
  const k = key(exhibit, page)
  const hit = cache.get(k)
  if (hit) return hit

  const token = getToken()
  const pending = fetch(`/api/study/page/${encodeURIComponent(exhibit)}/${page}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
    .then(async (res) => {
      if (!res.ok) throw new Error(String(res.status))
      return measure(URL.createObjectURL(await res.blob()))
    })
    .catch((e) => {
      // Not kept: a page that failed once (a dropped request, a server
      // restart) must be retriable, or the exhibit stays blank for the rest of
      // the session.
      cache.delete(k)
      throw e
    })

  cache.set(k, pending)
  return pending
}

/** Drop every cached page. Used when the bundle changes (practice -> real). */
export function clearPageImages(): void {
  for (const pending of cache.values()) {
    void pending.then((p) => URL.revokeObjectURL(p.url)).catch(() => {})
  }
  cache.clear()
}
