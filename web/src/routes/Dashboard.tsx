import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../features/auth/AuthContext'
import { api, uploadToStorage } from '../lib/api'
import { readPageCount } from '../lib/pdf'
import type { ProjectSummary } from '../types'

type UploadStage = 'idle' | 'reading' | 'uploading' | 'registering'

const STAGE_LABEL: Record<Exclude<UploadStage, 'idle'>, string> = {
  reading: 'Reading the drawing set…',
  uploading: 'Uploading…',
  registering: 'Creating the folder…',
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatWhen(iso: string): string {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`
  return `${Math.floor(seconds / 86400)} d ago`
}

export function Dashboard() {
  const navigate = useNavigate()
  const { user, signOut } = useAuth()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [projects, setProjects] = useState<ProjectSummary[] | null>(null)
  const [stage, setStage] = useState<UploadStage>('idle')
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      setProjects(await api.listProjects())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load your drawings.')
      setProjects([])
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  /**
   * Upload, then register. The PDF goes straight to storage on a signed URL —
   * it never passes through the API, which caps request bodies well below the
   * size of a real drawing set.
   */
  const onFileChosen = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = '' // let the same file be picked again after an error
    if (!file) return

    setError(null)
    try {
      setStage('reading')
      const pageCount = await readPageCount(file)

      setStage('uploading')
      const ticket = await api.getUploadTicket(file.name, file.size)
      await uploadToStorage(ticket, file)

      setStage('registering')
      const project = await api.createProject({
        id: crypto.randomUUID(),
        name: file.name.replace(/\.pdf$/i, ''),
        filename: file.name,
        storage_path: ticket.storage_path,
        size_bytes: file.size,
        page_count: pageCount,
      })

      setStage('idle')
      navigate(`/projects/${project.id}`)
    } catch (err) {
      setStage('idle')
      setError(
        err instanceof Error
          ? err.message
          : 'That file could not be added. Check it is a PDF and try again.',
      )
    }
  }

  const openPicker = () => fileInputRef.current?.click()

  const onDelete = async (project: ProjectSummary, event: React.MouseEvent) => {
    event.stopPropagation()
    if (!window.confirm(`Delete "${project.name}" and all of its annotations?`)) return
    try {
      await api.deleteProject(project.id)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete that folder.')
    }
  }

  const busy = stage !== 'idle'
  const hasProjects = projects !== null && projects.length > 0

  return (
    <div className="page">
      <input
        ref={fileInputRef}
        type="file"
        accept="application/pdf,.pdf"
        className="visually-hidden"
        onChange={onFileChosen}
      />

      <header className="topbar">
        <div className="topbar-identity">
          <span className="wordmark">Drawing Annotator</span>
        </div>
        <div className="topbar-actions">
          {user && <span className="topbar-user">{user.email}</span>}
          {/* Once there are folders, adding more lives up here rather than
              in the middle of the page. */}
          {hasProjects && (
            <button className="button button-primary" onClick={openPicker} disabled={busy}>
              {busy ? STAGE_LABEL[stage as Exclude<UploadStage, 'idle'>] : 'Add drawings'}
            </button>
          )}
          <button className="button button-quiet" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>

      <main className="dashboard">
        {error && (
          <div className="banner banner-error" role="alert">
            {error}
          </div>
        )}

        {projects === null && <p className="muted">Loading your drawings…</p>}

        {projects !== null && !hasProjects && (
          <section className="empty">
            <div className="empty-icon" aria-hidden="true">
              <svg viewBox="0 0 48 48" width="48" height="48" fill="none" stroke="currentColor" strokeWidth="1.5">
                <rect x="8" y="5" width="32" height="38" rx="2" />
                <path d="M14 15h20M14 22h20M14 29h13" />
              </svg>
            </div>
            <h2 className="empty-title">No drawings yet</h2>
            <p className="empty-lede">Add a PDF drawing set to start marking it up.</p>
            <button className="button button-primary button-large" onClick={openPicker} disabled={busy}>
              {busy ? STAGE_LABEL[stage as Exclude<UploadStage, 'idle'>] : 'Add drawings'}
            </button>
          </section>
        )}

        {hasProjects && (
          <>
            <h1 className="dashboard-title">Your drawings</h1>
            <ul className="folders">
              {projects.map((project) => (
                <li key={project.id}>
                  <button className="folder" onClick={() => navigate(`/projects/${project.id}`)}>
                    <span className="folder-icon" aria-hidden="true">
                      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.5">
                        <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                      </svg>
                    </span>
                    <span className="folder-body">
                      <span className="folder-name">{project.name}</span>
                      <span className="folder-meta">
                        {project.page_count} {project.page_count === 1 ? 'sheet' : 'sheets'} ·{' '}
                        {formatSize(project.size_bytes)} · {formatWhen(project.updated_at)}
                      </span>
                    </span>
                    <span
                      className="folder-delete"
                      role="button"
                      tabIndex={0}
                      aria-label={`Delete ${project.name}`}
                      onClick={(event) => void onDelete(project, event)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          event.stopPropagation()
                          void onDelete(project, event as unknown as React.MouseEvent)
                        }
                      }}
                    >
                      Delete
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </main>
    </div>
  )
}
