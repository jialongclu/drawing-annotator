import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { SheetCanvas } from '../features/annotations/SheetCanvas'
import { useAnnotationStore } from '../features/annotations/store'
import { api } from '../lib/api'
import { loadDocument } from '../lib/pdf'
import type { PDFDocumentProxy } from '../lib/pdf'

export function Viewer() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null)
  const [index, setIndex] = useState(0)
  const [loadError, setLoadError] = useState<string | null>(null)

  const project = useAnnotationStore((s) => s.project)
  const annotations = useAnnotationStore((s) => s.annotations)
  const tool = useAnnotationStore((s) => s.tool)
  const selectedId = useAnnotationStore((s) => s.selectedId)
  const dirty = useAnnotationStore((s) => s.dirty)
  const saving = useAnnotationStore((s) => s.saving)
  const saveError = useAnnotationStore((s) => s.saveError)
  const lastSavedAt = useAnnotationStore((s) => s.lastSavedAt)
  const load = useAnnotationStore((s) => s.load)
  const reset = useAnnotationStore((s) => s.reset)
  const setTool = useAnnotationStore((s) => s.setTool)
  const deleteAnnotation = useAnnotationStore((s) => s.deleteAnnotation)
  const select = useAnnotationStore((s) => s.select)
  const undo = useAnnotationStore((s) => s.undo)
  const save = useAnnotationStore((s) => s.save)

  const drawings = project?.drawings ?? []
  const current = drawings[index]
  const total = drawings.length

  // Load the folder and its PDF. One bootstrap request brings every sheet and
  // every rectangle; the document itself is fetched once and every page
  // renders from it, so page turns need no network at all.
  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    let loaded: PDFDocumentProxy | null = null

    ;(async () => {
      try {
        const [detail, source] = await Promise.all([
          api.getProject(projectId),
          api.getSourceUrl(projectId),
        ])
        if (cancelled) return
        load(detail)
        setIndex(0)

        loaded = await loadDocument(source.url)
        if (cancelled) {
          await loaded.destroy()
          return
        }
        setDoc(loaded)
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : 'Could not open this folder.')
        }
      }
    })()

    return () => {
      cancelled = true
      void loaded?.destroy()
      reset()
    }
  }, [projectId, load, reset])

  const goTo = useCallback(
    (next: number) => {
      // No wrap-around: the ends of a drawing set are real boundaries.
      setIndex((previous) => {
        const target = Math.min(Math.max(next, 0), Math.max(total - 1, 0))
        if (target !== previous) select(null)
        return target
      })
    },
    [total, select],
  )

  const onSave = useCallback(() => {
    if (dirty && !saving) void save()
  }, [dirty, saving, save])

  // Keyboard control. Suppressed while typing so shortcuts never eat input.
  useEffect(() => {
    const isTyping = (target: EventTarget | null) => {
      const element = target as HTMLElement | null
      if (!element) return false
      return (
        element.isContentEditable ||
        ['INPUT', 'TEXTAREA', 'SELECT'].includes(element.tagName)
      )
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (isTyping(event.target)) return

      const meta = event.metaKey || event.ctrlKey

      if (meta && event.key.toLowerCase() === 's') {
        event.preventDefault()
        onSave()
        return
      }
      if (meta && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        undo()
        return
      }
      if (meta) return

      switch (event.key) {
        case 'ArrowRight':
        case 'ArrowDown':
        case 'PageDown':
          event.preventDefault()
          setIndex((i) => Math.min(i + 1, Math.max(total - 1, 0)))
          select(null)
          break
        case 'ArrowLeft':
        case 'ArrowUp':
        case 'PageUp':
          event.preventDefault()
          setIndex((i) => Math.max(i - 1, 0))
          select(null)
          break
        case '1':
          setTool('block')
          break
        case '2':
          setTool('capture')
          break
        case 'Delete':
        case 'Backspace':
          if (selectedId && current) {
            event.preventDefault()
            void deleteAnnotation(current.id, selectedId)
          }
          break
        case 'Escape':
          select(null)
          break
        default:
          break
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [total, selectedId, current, onSave, undo, setTool, deleteAnnotation, select])

  // Warn before losing unsaved work on a reload or tab close.
  useEffect(() => {
    if (!dirty) return
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [dirty])

  const leave = () => {
    if (dirty && !window.confirm('You have unsaved annotations. Leave without saving?')) return
    navigate('/')
  }

  if (loadError) {
    return (
      <div className="page">
        <main className="dashboard">
          <div className="banner banner-error" role="alert">
            {loadError}
          </div>
          <button className="button" onClick={() => navigate('/')}>
            Back to drawings
          </button>
        </main>
      </div>
    )
  }

  if (!project) {
    return (
      <div className="page">
        <main className="dashboard">
          <p className="muted">Opening folder…</p>
        </main>
      </div>
    )
  }

  const sheetCount = annotations[current?.id ?? '']?.length ?? 0
  const totalMarks = Object.values(annotations).reduce((sum, list) => sum + list.length, 0)

  return (
    <div className="page viewer">
      <header className="toolbar">
        <div className="toolbar-left">
          <button className="button button-quiet" onClick={leave}>
            ← Back
          </button>
          <div className="toolbar-file">
            <span className="toolbar-filename">{project.name}</span>
            <span className="toolbar-filemeta">{project.filename}</span>
          </div>
        </div>

        <div className="toolbar-center" aria-live="polite">
          <span className="counter">
            Sheet {total === 0 ? 0 : index + 1} of {total}
          </span>
          <span className="counter-meta">
            {sheetCount} on this sheet · {totalMarks} in folder
          </span>
        </div>

        <div className="toolbar-right">
          <div className="segmented" role="radiogroup" aria-label="Annotation tool">
            <button
              role="radio"
              aria-checked={tool === 'block'}
              className={`segment segment-block ${tool === 'block' ? 'is-active' : ''}`}
              onClick={() => setTool('block')}
            >
              <span className="swatch swatch-block" aria-hidden="true" />
              Block
            </button>
            <button
              role="radio"
              aria-checked={tool === 'capture'}
              className={`segment segment-capture ${tool === 'capture' ? 'is-active' : ''}`}
              onClick={() => setTool('capture')}
            >
              <span className="swatch swatch-capture" aria-hidden="true" />
              Capture
            </button>
          </div>

          <button
            className="button button-quiet"
            onClick={() => selectedId && current && void deleteAnnotation(current.id, selectedId)}
            disabled={!selectedId}
          >
            Delete
          </button>
          <button className="button button-quiet" onClick={undo}>
            Undo
          </button>
          <button className="button button-primary" onClick={onSave} disabled={!dirty || saving}>
            {saving ? 'Saving…' : 'Save'}
            {dirty && !saving && <span className="dot" aria-hidden="true" />}
          </button>
        </div>
      </header>

      {(saveError || lastSavedAt) && (
        <div className={`strip ${saveError ? 'strip-error' : 'strip-ok'}`} role="status">
          {saveError ?? 'Saved'}
        </div>
      )}

      <main className="stage">
        <button
          className="nav nav-prev"
          onClick={() => goTo(index - 1)}
          disabled={index === 0}
          aria-label="Previous drawing"
        >
          ‹
        </button>

        {doc && current ? (
          <SheetCanvas doc={doc} pageNumber={current.page_number} drawingId={current.id} />
        ) : (
          <div className="sheet">
            <p className="muted">Loading the drawing…</p>
          </div>
        )}

        <button
          className="nav nav-next"
          onClick={() => goTo(index + 1)}
          disabled={index >= total - 1}
          aria-label="Next drawing"
        >
          ›
        </button>
      </main>

      <footer className="hints">
        <span><kbd>←</kbd> <kbd>→</kbd> change sheet</span>
        <span><kbd>1</kbd> block · <kbd>2</kbd> capture</span>
        <span><kbd>⌫</kbd> delete selected</span>
        <span><kbd>⌘Z</kbd> undo</span>
        <span><kbd>⌘S</kbd> save</span>
      </footer>
    </div>
  )
}
