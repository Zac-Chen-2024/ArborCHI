/**
 * Non-linguistic glyphs used as icons.
 *
 * They live here rather than inline in JSX for one reason: the
 * i18next/no-literal-string rule (FS-03) cannot tell a drag handle from a
 * forgotten English label, and it should not have to. Anything in this file is
 * a symbol with no language; everything a participant can *read* goes through
 * i18n. The accessible name always comes from an aria-label, never from the
 * glyph.
 */
export const GRAB_HANDLE = '⠿'
export const MENU_DOTS = '⋯'
export const CRUMB_SEP = '›'
export const ZOOM_OUT = '−'
export const ZOOM_IN = '＋'
