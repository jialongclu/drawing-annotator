import { useCallback, useEffect, useRef, useState } from 'react'

import { hitTest, normalizeDrag, toPixels } from '../../lib/geometry'
import { renderPage } from '../../lib/pdf'
import type { PDFDocumentProxy, RenderedPage } from '../../lib/pdf'
import type { Annotation, AnnotationKind } from '../../types'
import { useAnnotationStore } from './store'

const COLORS: Record<AnnotationKind, string> = {
  block: '#EF4444',
  capture: '#22C55E',
}

interface Props {
  doc: PDFDocumentProxy
  pageNumber: number
  drawingId: string
}

/**
 * The PDF page and its markup, drawn on two stacked canvases.
 *
 * Keeping the overlay separate means a drag repaints only the rectangles —
 * the PDF itself is rendered once per page and left alone.
 */
export function SheetCanvas({ doc, pageNumber, drawingId }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const pageCanvasRef = useRef<HTMLCanvasElement>(null)
  const overlayRef = useRef<HTMLCanvasElement>(null)

  // Rendered pages, keyed by page and viewport size so a resize invalidates
  // them. Bounded, because a 200-sheet set would otherwise pin a lot of memory.
  const cacheRef = useRef(new Map<string, RenderedPage>())

  const [box, setBox] = useState({ width: 0, height: 0 })
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [drag, setDrag] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null)
  const [rendering, setRendering] = useState(true)

  const annotations = useAnnotationStore((s) => s.annotations[drawingId] ?? [])
  const tool = useAnnotationStore((s) => s.tool)
  const selectedId = useAnnotationStore((s) => s.selectedId)
  const deletingId = useAnnotationStore((s) => s.deletingId)
  const add = useAnnotationStore((s) => s.add)
  const select = useAnnotationStore((s) => s.select)
  const deleteAnnotation = useAnnotationStore((s) => s.deleteAnnotation)

  const selected = annotations.find((a) => a.id === selectedId) ?? null

  // Track the space available for the page.
  useEffect(() => {
    const element = containerRef.current
    if (!element) return

    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setBox({ width: Math.floor(width), height: Math.floor(height) })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  // Render the current page, and warm the neighbours so arrow keys feel instant.
  useEffect(() => {
    if (box.width < 40 || box.height < 40) return
    let cancelled = false

    const key = (page: number) => `${page}@${box.width}x${box.height}`

    const get = async (page: number): Promise<RenderedPage> => {
      const cached = cacheRef.current.get(key(page))
      if (cached) return cached
      const rendered = await renderPage(doc, page, box.width, box.height)
      cacheRef.current.set(key(page), rendered)
      if (cacheRef.current.size > 5) {
        const oldest = cacheRef.current.keys().next().value
        if (oldest) cacheRef.current.delete(oldest)
      }
      return rendered
    }

    setRendering(true)
    get(pageNumber)
      .then((rendered) => {
        if (cancelled) return
        const canvas = pageCanvasRef.current
        if (!canvas) return

        canvas.width = rendered.canvas.width
        canvas.height = rendered.canvas.height
        canvas.style.width = `${rendered.cssWidth}px`
        canvas.style.height = `${rendered.cssHeight}px`
        canvas.getContext('2d')?.drawImage(rendered.canvas, 0, 0)

        setSize({ width: rendered.cssWidth, height: rendered.cssHeight })
        setRendering(false)

        for (const neighbour of [pageNumber + 1, pageNumber - 1]) {
          if (neighbour >= 1 && neighbour <= doc.numPages) void get(neighbour)
        }
      })
      .catch(() => {
        if (!cancelled) setRendering(false)
      })

    return () => {
      cancelled = true
    }
  }, [doc, pageNumber, box.width, box.height])

  // Repaint the markup.
  useEffect(() => {
    const canvas = overlayRef.current
    if (!canvas || size.width === 0) return

    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = Math.floor(size.width * dpr)
    canvas.height = Math.floor(size.height * dpr)
    canvas.style.width = `${size.width}px`
    canvas.style.height = `${size.height}px`

    const context = canvas.getContext('2d')
    if (!context) return
    context.setTransform(dpr, 0, 0, dpr, 0, 0)
    context.clearRect(0, 0, size.width, size.height)

    const paint = (rect: ReturnType<typeof toPixels>, color: string, selected: boolean) => {
      context.globalAlpha = 0.3
      context.fillStyle = color
      context.fillRect(rect.x, rect.y, rect.w, rect.h)

      context.globalAlpha = 1
      context.strokeStyle = color
      context.lineWidth = 2
      context.setLineDash([])
      context.strokeRect(rect.x, rect.y, rect.w, rect.h)

      if (selected) {
        context.strokeStyle = '#0F172A'
        context.lineWidth = 1
        context.setLineDash([4, 3])
        context.strokeRect(rect.x - 3, rect.y - 3, rect.w + 6, rect.h + 6)
        context.setLineDash([])
      }
    }

    for (const annotation of annotations) {
      paint(
        toPixels(annotation, size.width, size.height),
        COLORS[annotation.kind],
        annotation.id === selectedId,
      )
    }

    if (drag) {
      const x = Math.min(drag.x1, drag.x2)
      const y = Math.min(drag.y1, drag.y2)
      paint({ x, y, w: Math.abs(drag.x2 - drag.x1), h: Math.abs(drag.y2 - drag.y1) }, COLORS[tool], false)
    }
  }, [annotations, selectedId, drag, tool, size])

  const pointAt = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    return { x: event.clientX - rect.left, y: event.clientY - rect.top }
  }, [])

  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (event.button !== 0) return
    event.currentTarget.setPointerCapture(event.pointerId)
    const point = pointAt(event)
    setDrag({ x1: point.x, y1: point.y, x2: point.x, y2: point.y })
  }

  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drag) return
    const point = pointAt(event)
    setDrag({ ...drag, x2: point.x, y2: point.y })
  }

  const onPointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drag) return
    const point = pointAt(event)
    const drawn = normalizeDrag(
      { x: drag.x1, y: drag.y1 },
      { x: point.x, y: point.y },
      size.width,
      size.height,
    )
    setDrag(null)

    if (drawn) {
      add(drawingId, { ...drawn, kind: tool })
    } else {
      // Too small to be a rectangle, so treat it as a click: select whatever
      // is under the cursor, or clear the selection.
      select(hitTest(annotations, point, size.width, size.height)?.id ?? null)
    }
  }

  const onPointerCancel = () => setDrag(null)

  // Anchored above the selected rectangle, nudged back inside the page when
  // the rectangle sits against an edge.
  const popover = (() => {
    if (!selected || size.width === 0) return null
    const rect = toPixels(selected, size.width, size.height)
    const width = 108
    const left = Math.min(Math.max(rect.x + rect.w / 2 - width / 2, 4), size.width - width - 4)
    const above = rect.y > 44
    return { left, top: above ? rect.y - 40 : rect.y + rect.h + 8, width }
  })()

  return (
    <div className="sheet" ref={containerRef}>
      <div className="sheet-stack" style={{ width: size.width || undefined }}>
        <canvas ref={pageCanvasRef} className="sheet-page" />
        <canvas
          ref={overlayRef}
          className="sheet-overlay"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerCancel}
        />

        {selected && popover && (
          <div
            className="annotation-popover"
            style={{ left: popover.left, top: popover.top, width: popover.width }}
            role="dialog"
            aria-label={`${selected.kind === 'block' ? 'Block' : 'Capture'} annotation`}
          >
            <span className={`popover-kind popover-kind-${selected.kind}`}>
              {selected.kind === 'block' ? 'Block' : 'Capture'}
            </span>
            <button
              type="button"
              className="popover-delete"
              autoFocus
              disabled={deletingId === selected.id}
              onClick={() => void deleteAnnotation(drawingId, selected.id)}
            >
              {deletingId === selected.id ? 'Deleting…' : 'Delete'}
            </button>
          </div>
        )}

        {rendering && <div className="sheet-loading">Rendering…</div>}
      </div>
    </div>
  )
}

export type { Annotation }
