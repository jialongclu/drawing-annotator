import { create } from 'zustand'

import { api } from '../../lib/api'
import type { Annotation, AnnotationKind, Project } from '../../types'

type AnnotationsByDrawing = Record<string, Annotation[]>

interface UndoEntry {
  drawingId: string
  annotations: Annotation[]
}

interface AnnotationState {
  project: Project | null
  annotations: AnnotationsByDrawing
  /** Ids the server is known to hold, so a delete knows whether to call it. */
  persistedIds: Set<string>
  tool: AnnotationKind
  selectedId: string | null
  deletingId: string | null
  dirty: boolean
  saving: boolean
  saveError: string | null
  lastSavedAt: number | null
  undoStack: UndoEntry[]

  load: (project: Project) => void
  reset: () => void
  setTool: (tool: AnnotationKind) => void
  select: (id: string | null) => void
  add: (drawingId: string, annotation: Annotation) => void
  deleteAnnotation: (drawingId: string, annotationId: string) => Promise<void>
  undo: () => void
  save: () => Promise<void>
}

function indexByDrawing(project: Project): AnnotationsByDrawing {
  const result: AnnotationsByDrawing = {}
  for (const drawing of project.drawings) {
    result[drawing.id] = drawing.annotations.map((a) => ({ ...a }))
  }
  return result
}

function persistedFrom(project: Project): Set<string> {
  return new Set(project.drawings.flatMap((d) => d.annotations.map((a) => a.id)))
}

/**
 * The buffer that makes Save mean something.
 *
 * Every edit lands here and nowhere else; the API is touched only when `save`
 * runs. That is the whole point of the requirement that annotations persist
 * on an explicit save rather than as you draw.
 */
export const useAnnotationStore = create<AnnotationState>((set, get) => ({
  project: null,
  annotations: {},
  persistedIds: new Set<string>(),
  tool: 'block',
  selectedId: null,
  deletingId: null,
  dirty: false,
  saving: false,
  saveError: null,
  lastSavedAt: null,
  undoStack: [],

  load: (project) =>
    set({
      project,
      annotations: indexByDrawing(project),
      persistedIds: persistedFrom(project),
      dirty: false,
      selectedId: null,
      deletingId: null,
      saveError: null,
      undoStack: [],
    }),

  reset: () =>
    set({
      project: null,
      annotations: {},
      persistedIds: new Set<string>(),
      dirty: false,
      selectedId: null,
      deletingId: null,
      saveError: null,
      lastSavedAt: null,
      undoStack: [],
    }),

  setTool: (tool) => set({ tool }),

  select: (selectedId) => set({ selectedId }),

  add: (drawingId, annotation) =>
    set((state) => {
      const before = state.annotations[drawingId] ?? []
      return {
        annotations: { ...state.annotations, [drawingId]: [...before, annotation] },
        undoStack: [...state.undoStack, { drawingId, annotations: before }].slice(-50),
        dirty: true,
        selectedId: annotation.id,
        saveError: null,
      }
    }),

  /**
   * Delete one rectangle.
   *
   * A rectangle the server already holds is deleted through the API
   * immediately; one that has only ever lived in this buffer is simply
   * dropped, because there is nothing on the server to delete. Getting that
   * distinction wrong would mean a 404 every time someone drew a box and
   * changed their mind before saving.
   */
  deleteAnnotation: async (drawingId, annotationId) => {
    const { project, annotations, persistedIds, deletingId } = get()
    if (!project || deletingId) return

    const before = annotations[drawingId] ?? []
    if (!before.some((a) => a.id === annotationId)) return

    if (persistedIds.has(annotationId)) {
      set({ deletingId: annotationId, saveError: null })
      try {
        await api.deleteAnnotation(project.id, annotationId)
      } catch (error) {
        set({
          deletingId: null,
          saveError:
            error instanceof Error ? error.message : 'Could not delete that annotation.',
        })
        return
      }
    }

    set((state) => {
      const current = state.annotations[drawingId] ?? []
      const remaining = new Set(state.persistedIds)
      const wasPersisted = remaining.delete(annotationId)

      return {
        annotations: {
          ...state.annotations,
          [drawingId]: current.filter((a) => a.id !== annotationId),
        },
        persistedIds: remaining,
        undoStack: [...state.undoStack, { drawingId, annotations: current }].slice(-50),
        // A persisted delete already reached the database, so it does not by
        // itself make the buffer dirty — other unsaved edits still might.
        dirty: wasPersisted ? state.dirty : true,
        selectedId: state.selectedId === annotationId ? null : state.selectedId,
        deletingId: null,
        saveError: null,
      }
    })
  },

  undo: () =>
    set((state) => {
      const previous = state.undoStack[state.undoStack.length - 1]
      if (!previous) return state
      return {
        annotations: { ...state.annotations, [previous.drawingId]: previous.annotations },
        undoStack: state.undoStack.slice(0, -1),
        dirty: true,
        selectedId: null,
      }
    }),

  save: async () => {
    const { project, annotations, saving } = get()
    if (!project || saving) return

    set({ saving: true, saveError: null })
    try {
      // Send every sheet, including the emptied ones — a drawing left out of
      // the payload is untouched on the server, so an omitted sheet would keep
      // rectangles the user has just deleted.
      const payload = project.drawings.map((drawing) => ({
        drawing_id: drawing.id,
        annotations: annotations[drawing.id] ?? [],
      }))

      const saved = await api.saveAnnotations(project.id, payload)
      set({
        project: saved,
        annotations: indexByDrawing(saved),
        persistedIds: persistedFrom(saved),
        dirty: false,
        saving: false,
        lastSavedAt: Date.now(),
        undoStack: [],
      })
    } catch (error) {
      set({
        saving: false,
        saveError: error instanceof Error ? error.message : 'Could not save your annotations.',
      })
    }
  },
}))
