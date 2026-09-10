import type { Annotation } from '../types'

export interface PixelRect {
  x: number
  y: number
  w: number
  h: number
}

/** The smallest drag we treat as a rectangle rather than a stray click. */
export const MIN_DRAG_PX = 6

/**
 * Convert a drag in canvas pixels into normalized page coordinates.
 *
 * Points are clamped to the page first, so a drag that runs off the edge
 * produces a rectangle flush with the border rather than one the server has to
 * reject.
 */
export function normalizeDrag(
  start: { x: number; y: number },
  end: { x: number; y: number },
  width: number,
  height: number,
): Annotation | null {
  if (width <= 0 || height <= 0) return null

  const clamp = (value: number, max: number) => Math.min(Math.max(value, 0), max)
  const x1 = clamp(start.x, width)
  const y1 = clamp(start.y, height)
  const x2 = clamp(end.x, width)
  const y2 = clamp(end.y, height)

  const left = Math.min(x1, x2)
  const top = Math.min(y1, y2)
  const dragWidth = Math.abs(x2 - x1)
  const dragHeight = Math.abs(y2 - y1)

  if (dragWidth < MIN_DRAG_PX || dragHeight < MIN_DRAG_PX) return null

  return {
    id: crypto.randomUUID(),
    kind: 'block',
    x: left / width,
    y: top / height,
    w: dragWidth / width,
    h: dragHeight / height,
  }
}

/** Project a stored rectangle back onto the canvas at its current size. */
export function toPixels(annotation: Annotation, width: number, height: number): PixelRect {
  return {
    x: annotation.x * width,
    y: annotation.y * height,
    w: annotation.w * width,
    h: annotation.h * height,
  }
}

export function hitTest(
  annotations: Annotation[],
  point: { x: number; y: number },
  width: number,
  height: number,
): Annotation | null {
  // Walk backwards so the most recently drawn rectangle wins an overlap,
  // matching what the user sees on top.
  for (let i = annotations.length - 1; i >= 0; i -= 1) {
    const rect = toPixels(annotations[i], width, height)
    if (
      point.x >= rect.x &&
      point.x <= rect.x + rect.w &&
      point.y >= rect.y &&
      point.y <= rect.y + rect.h
    ) {
      return annotations[i]
    }
  }
  return null
}
