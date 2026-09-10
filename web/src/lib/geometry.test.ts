import { describe, expect, it } from 'vitest'

import { hitTest, normalizeDrag, toPixels } from './geometry'
import type { Annotation } from '../types'

const box = (over: Partial<Annotation> = {}): Annotation => ({
  id: 'a',
  kind: 'block',
  x: 0.25,
  y: 0.5,
  w: 0.25,
  h: 0.25,
  ...over,
})

describe('normalizeDrag', () => {
  it('converts pixels to fractions of the page', () => {
    const result = normalizeDrag({ x: 100, y: 200 }, { x: 300, y: 400 }, 1000, 800)

    expect(result).not.toBeNull()
    expect(result!.x).toBeCloseTo(0.1)
    expect(result!.y).toBeCloseTo(0.25)
    expect(result!.w).toBeCloseTo(0.2)
    expect(result!.h).toBeCloseTo(0.25)
  })

  it('normalizes a drag made in any direction', () => {
    const downRight = normalizeDrag({ x: 100, y: 100 }, { x: 300, y: 300 }, 1000, 1000)
    const upLeft = normalizeDrag({ x: 300, y: 300 }, { x: 100, y: 100 }, 1000, 1000)

    expect(upLeft).toEqual({ ...downRight!, id: upLeft!.id })
  })

  it('discards a drag too small to be intentional', () => {
    expect(normalizeDrag({ x: 100, y: 100 }, { x: 103, y: 130 }, 1000, 1000)).toBeNull()
    expect(normalizeDrag({ x: 100, y: 100 }, { x: 100, y: 100 }, 1000, 1000)).toBeNull()
  })

  it('clamps a drag that runs off the page', () => {
    const result = normalizeDrag({ x: -500, y: -500 }, { x: 5000, y: 5000 }, 1000, 800)

    expect(result).toEqual(expect.objectContaining({ x: 0, y: 0, w: 1, h: 1 }))
  })

  it('never produces a rectangle the server would reject', () => {
    const result = normalizeDrag({ x: 900, y: 700 }, { x: 2000, y: 2000 }, 1000, 800)!

    expect(result.x + result.w).toBeLessThanOrEqual(1)
    expect(result.y + result.h).toBeLessThanOrEqual(1)
  })

  it('refuses to divide by a zero-sized page', () => {
    expect(normalizeDrag({ x: 0, y: 0 }, { x: 50, y: 50 }, 0, 0)).toBeNull()
  })
})

describe('round-tripping through pixels', () => {
  it('lands in the same place at a different window size', () => {
    // The whole point of storing fractions: draw at one size, reopen at
    // another, and the rectangle still covers the same part of the drawing.
    const drawn = normalizeDrag({ x: 250, y: 400 }, { x: 500, y: 600 }, 1000, 800)!

    const small = toPixels(drawn, 500, 400)
    const large = toPixels(drawn, 2000, 1600)

    expect(small.x / 500).toBeCloseTo(large.x / 2000)
    expect(small.w / 500).toBeCloseTo(large.w / 2000)
    expect(large.x).toBeCloseTo(500)
    expect(large.w).toBeCloseTo(500)
  })
})

describe('hitTest', () => {
  it('finds a rectangle under the cursor', () => {
    const found = hitTest([box()], { x: 300, y: 600 }, 1000, 1000)

    expect(found?.id).toBe('a')
  })

  it('returns nothing when the cursor is on bare paper', () => {
    expect(hitTest([box()], { x: 10, y: 10 }, 1000, 1000)).toBeNull()
  })

  it('prefers the rectangle drawn most recently where they overlap', () => {
    const under = box({ id: 'under' })
    const over = box({ id: 'over' })

    expect(hitTest([under, over], { x: 300, y: 600 }, 1000, 1000)?.id).toBe('over')
  })
})
