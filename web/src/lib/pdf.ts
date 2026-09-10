import * as pdfjs from 'pdfjs-dist'
import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

// Bundled with the app rather than pulled from a CDN, so the viewer keeps
// working offline and no third party sees which drawings are being opened.
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

export type { PDFDocumentProxy, PDFPageProxy }

export async function loadDocument(source: string | ArrayBuffer): Promise<PDFDocumentProxy> {
  const task =
    typeof source === 'string' ? pdfjs.getDocument(source) : pdfjs.getDocument({ data: source })
  return task.promise
}

/** Read a page count locally, so the server never has to parse the PDF. */
export async function readPageCount(file: File): Promise<number> {
  const buffer = await file.arrayBuffer()
  const doc = await pdfjs.getDocument({ data: buffer }).promise
  const pages = doc.numPages
  await doc.destroy()
  return pages
}

export interface RenderedPage {
  canvas: HTMLCanvasElement
  cssWidth: number
  cssHeight: number
}

/**
 * Render one page to an offscreen canvas, fitted inside `maxWidth`/`maxHeight`.
 *
 * The canvas is drawn at device-pixel resolution but reported at CSS size, so
 * the annotation overlay can share one coordinate space with it and stay sharp
 * on retina displays.
 */
export async function renderPage(
  doc: PDFDocumentProxy,
  pageNumber: number,
  maxWidth: number,
  maxHeight: number,
): Promise<RenderedPage> {
  const page = await doc.getPage(pageNumber)
  const base = page.getViewport({ scale: 1 })
  const scale = Math.min(maxWidth / base.width, maxHeight / base.height)
  const viewport = page.getViewport({ scale })

  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const canvas = document.createElement('canvas')
  canvas.width = Math.floor(viewport.width * dpr)
  canvas.height = Math.floor(viewport.height * dpr)

  const context = canvas.getContext('2d')
  if (!context) throw new Error('Could not get a 2D canvas context.')

  context.scale(dpr, dpr)
  await page.render({ canvasContext: context, viewport }).promise
  page.cleanup()

  return { canvas, cssWidth: viewport.width, cssHeight: viewport.height }
}
