import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Annotation, Project } from '../../types'

const saveAnnotations = vi.fn()
const deleteAnnotation = vi.fn()

vi.mock('../../lib/api', () => ({
  api: {
    saveAnnotations: (...args: unknown[]) => saveAnnotations(...args),
    deleteAnnotation: (...args: unknown[]) => deleteAnnotation(...args),
  },
}))

const { useAnnotationStore } = await import('./store')

const project = (): Project => ({
  id: 'p1',
  name: 'Level 2 Redlines',
  filename: 'A-101.pdf',
  page_count: 3,
  size_bytes: 1000,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  drawings: [
    { id: 'd1', page_number: 1, annotations: [] },
    { id: 'd2', page_number: 2, annotations: [] },
    { id: 'd3', page_number: 3, annotations: [] },
  ],
})

const rect = (id: string, over: Partial<Annotation> = {}): Annotation => ({
  id,
  kind: 'block',
  x: 0.1,
  y: 0.1,
  w: 0.2,
  h: 0.2,
  ...over,
})

describe('the annotation buffer', () => {
  beforeEach(() => {
    saveAnnotations.mockReset()
    deleteAnnotation.mockReset()
    deleteAnnotation.mockResolvedValue(null)
    useAnnotationStore.getState().reset()
    useAnnotationStore.getState().load(project())
  })

  it('starts clean', () => {
    expect(useAnnotationStore.getState().dirty).toBe(false)
  })

  it('does not touch the API when a rectangle is drawn', () => {
    // The requirement: drawing is buffered until Save is pressed.
    useAnnotationStore.getState().add('d1', rect('a1'))
    useAnnotationStore.getState().add('d2', rect('a2', { kind: 'capture' }))

    expect(saveAnnotations).not.toHaveBeenCalled()
    expect(useAnnotationStore.getState().dirty).toBe(true)
  })

  it('keeps each sheet’s rectangles separate', () => {
    useAnnotationStore.getState().add('d1', rect('a1'))
    useAnnotationStore.getState().add('d2', rect('a2'))

    const { annotations } = useAnnotationStore.getState()
    expect(annotations.d1.map((a) => a.id)).toEqual(['a1'])
    expect(annotations.d2.map((a) => a.id)).toEqual(['a2'])
    expect(annotations.d3).toEqual([])
  })

  it('undoes the last change', () => {
    useAnnotationStore.getState().add('d1', rect('a1'))
    useAnnotationStore.getState().add('d1', rect('a2'))
    useAnnotationStore.getState().undo()

    expect(useAnnotationStore.getState().annotations.d1.map((a) => a.id)).toEqual(['a1'])
  })

  it('undoes a delete as well as a draw', async () => {
    useAnnotationStore.getState().add('d1', rect('a1'))
    await useAnnotationStore.getState().deleteAnnotation('d1', 'a1')
    useAnnotationStore.getState().undo()

    expect(useAnnotationStore.getState().annotations.d1.map((a) => a.id)).toEqual(['a1'])
  })

  it('sends every sheet on save, including emptied ones', async () => {
    // A sheet left out of the payload is untouched server-side, so omitting a
    // cleared sheet would silently keep rectangles the user just deleted.
    useAnnotationStore.getState().add('d1', rect('a1'))
    saveAnnotations.mockResolvedValue(project())

    await useAnnotationStore.getState().save()

    const [projectId, payload] = saveAnnotations.mock.calls[0] as [string, unknown[]]
    expect(projectId).toBe('p1')
    expect(payload).toHaveLength(3)
    expect(payload).toContainEqual({ drawing_id: 'd3', annotations: [] })
  })

  it('is clean again after a successful save', async () => {
    useAnnotationStore.getState().add('d1', rect('a1'))
    saveAnnotations.mockResolvedValue({
      ...project(),
      drawings: [
        { id: 'd1', page_number: 1, annotations: [rect('a1')] },
        { id: 'd2', page_number: 2, annotations: [] },
        { id: 'd3', page_number: 3, annotations: [] },
      ],
    })

    await useAnnotationStore.getState().save()
    const state = useAnnotationStore.getState()

    expect(state.dirty).toBe(false)
    expect(state.saveError).toBeNull()
    expect(state.annotations.d1).toHaveLength(1)
  })

  it('stays dirty and reports the reason when a save fails', async () => {
    useAnnotationStore.getState().add('d1', rect('a1'))
    saveAnnotations.mockRejectedValue(new Error('Network is unreachable'))

    await useAnnotationStore.getState().save()
    const state = useAnnotationStore.getState()

    // Losing the user's work because the network blipped would be the worst
    // possible failure here.
    expect(state.dirty).toBe(true)
    expect(state.saveError).toBe('Network is unreachable')
    expect(state.annotations.d1).toHaveLength(1)
  })

  it('ignores a save while one is already running', async () => {
    useAnnotationStore.getState().add('d1', rect('a1'))
    let release: (value: Project) => void = () => {}
    saveAnnotations.mockReturnValue(new Promise<Project>((resolve) => (release = resolve)))

    const first = useAnnotationStore.getState().save()
    await useAnnotationStore.getState().save()
    release(project())
    await first

    expect(saveAnnotations).toHaveBeenCalledTimes(1)
  })

  it('adopts the server’s state as the new truth after saving', async () => {
    useAnnotationStore.getState().add('d1', rect('a1'))
    saveAnnotations.mockResolvedValue({
      ...project(),
      drawings: [
        { id: 'd1', page_number: 1, annotations: [rect('a1', { x: 0.9 })] },
        { id: 'd2', page_number: 2, annotations: [] },
        { id: 'd3', page_number: 3, annotations: [] },
      ],
    })

    await useAnnotationStore.getState().save()

    expect(useAnnotationStore.getState().annotations.d1[0].x).toBe(0.9)
  })
})

describe('deleting a selected rectangle', () => {
  /** A folder that already holds one saved rectangle on sheet one. */
  const withSaved = (): Project => ({
    ...project(),
    drawings: [
      { id: 'd1', page_number: 1, annotations: [rect('saved')] },
      { id: 'd2', page_number: 2, annotations: [] },
      { id: 'd3', page_number: 3, annotations: [] },
    ],
  })

  beforeEach(() => {
    saveAnnotations.mockReset()
    deleteAnnotation.mockReset()
    deleteAnnotation.mockResolvedValue(null)
    useAnnotationStore.getState().reset()
    useAnnotationStore.getState().load(withSaved())
  })

  it('calls the API for a rectangle the server already holds', async () => {
    useAnnotationStore.getState().select('saved')

    await useAnnotationStore.getState().deleteAnnotation('d1', 'saved')

    expect(deleteAnnotation).toHaveBeenCalledWith('p1', 'saved')
    expect(useAnnotationStore.getState().annotations.d1).toHaveLength(0)
  })

  it('does not call the API for a rectangle that was never saved', async () => {
    // Draw a box, change your mind before saving: there is nothing on the
    // server to delete, and asking would only produce a spurious 404.
    useAnnotationStore.getState().add('d1', rect('fresh'))

    await useAnnotationStore.getState().deleteAnnotation('d1', 'fresh')

    expect(deleteAnnotation).not.toHaveBeenCalled()
    expect(useAnnotationStore.getState().annotations.d1.map((a) => a.id)).toEqual(['saved'])
  })

  it('clears the selection so the popover closes', async () => {
    useAnnotationStore.getState().select('saved')

    await useAnnotationStore.getState().deleteAnnotation('d1', 'saved')

    expect(useAnnotationStore.getState().selectedId).toBeNull()
  })

  it('keeps the rectangle when the API call fails', async () => {
    deleteAnnotation.mockRejectedValue(new Error('Service unavailable'))

    await useAnnotationStore.getState().deleteAnnotation('d1', 'saved')
    const state = useAnnotationStore.getState()

    // Showing it as gone when the server still has it would mean the next
    // reload silently brings it back.
    expect(state.annotations.d1).toHaveLength(1)
    expect(state.saveError).toBe('Service unavailable')
    expect(state.deletingId).toBeNull()
  })

  it('does not mark the buffer dirty when the delete already reached the server', async () => {
    await useAnnotationStore.getState().deleteAnnotation('d1', 'saved')

    expect(useAnnotationStore.getState().dirty).toBe(false)
  })

  it('leaves other unsaved work dirty', async () => {
    useAnnotationStore.getState().add('d2', rect('fresh'))

    await useAnnotationStore.getState().deleteAnnotation('d1', 'saved')

    expect(useAnnotationStore.getState().dirty).toBe(true)
  })

  it('ignores a second delete while one is in flight', async () => {
    let release: (value: null) => void = () => {}
    deleteAnnotation.mockReturnValue(new Promise<null>((resolve) => (release = resolve)))

    const first = useAnnotationStore.getState().deleteAnnotation('d1', 'saved')
    await useAnnotationStore.getState().deleteAnnotation('d1', 'saved')
    release(null)
    await first

    expect(deleteAnnotation).toHaveBeenCalledTimes(1)
  })

  it('ignores a rectangle that is not on the given sheet', async () => {
    await useAnnotationStore.getState().deleteAnnotation('d2', 'saved')

    expect(deleteAnnotation).not.toHaveBeenCalled()
    expect(useAnnotationStore.getState().annotations.d1).toHaveLength(1)
  })

  it('re-creates the rectangle on save if the delete is undone', async () => {
    await useAnnotationStore.getState().deleteAnnotation('d1', 'saved')
    useAnnotationStore.getState().undo()
    saveAnnotations.mockResolvedValue(withSaved())

    await useAnnotationStore.getState().save()

    const [, payload] = saveAnnotations.mock.calls[0] as [string, { annotations: Annotation[] }[]]
    expect(payload[0].annotations.map((a) => a.id)).toEqual(['saved'])
  })
})
