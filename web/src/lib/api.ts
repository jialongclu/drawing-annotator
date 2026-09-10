import type { Annotation, Project, ProjectSummary, UploadTicket, User } from '../types'

/**
 * Where the API lives.
 *
 * Empty by default, which means same-origin: in production Django serves the
 * SPA itself, and in development Vite proxies /api to Django. Either way the
 * browser sees one origin and CORS never enters the picture.
 *
 * Set `VITE_API_BASE_URL=http://127.0.0.1:8000` to bypass the proxy and call
 * Django directly. That is a genuine cross-origin setup, so it also needs
 * `REFRESH_COOKIE_SAMESITE=None` and `REFRESH_COOKIE_SECURE=1` on the server
 * or the refresh cookie will not be sent back.
 */
const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? ''

/** Resolve an API path, and any server-issued relative URL, against that base. */
export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
}

/**
 * The access token lives in memory only — never localStorage, where any script
 * on the page could read it. The refresh token is an HttpOnly cookie the API
 * sets, so a full page reload recovers the session without JavaScript ever
 * touching the long-lived credential.
 */
let accessToken: string | null = null
let refreshInFlight: Promise<boolean> | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export class ApiError extends Error {
  status: number
  payload: unknown

  constructor(status: number, message: string, payload?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

function messageFrom(payload: unknown, fallback: string): string {
  if (typeof payload === 'string' && payload) return payload
  if (payload && typeof payload === 'object') {
    const record = payload as Record<string, unknown>
    if (typeof record.detail === 'string') return record.detail
    const first = Object.values(record)[0]
    if (Array.isArray(first) && typeof first[0] === 'string') return first[0]
    if (typeof first === 'string') return first
  }
  return fallback
}

async function parse(response: Response): Promise<unknown> {
  if (response.status === 204) return null
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

/** Refresh once even if several requests hit a 401 at the same moment. */
async function refreshAccessToken(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      const response = await fetch(apiUrl('/api/auth/refresh/'), {
        method: 'POST',
        credentials: 'include',
      })
      if (!response.ok) {
        accessToken = null
        return false
      }
      const data = (await response.json()) as { access_token: string }
      accessToken = data.access_token
      return true
    })().finally(() => {
      refreshInFlight = null
    })
  }
  return refreshInFlight
}

interface RequestOptions {
  method?: string
  body?: unknown
  retryOnUnauthorized?: boolean
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, retryOnUnauthorized = true } = options

  const headers: Record<string, string> = {}
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const response = await fetch(apiUrl(path), {
    method,
    headers,
    credentials: 'include',
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (response.status === 401 && retryOnUnauthorized) {
    if (await refreshAccessToken()) {
      return request<T>(path, { ...options, retryOnUnauthorized: false })
    }
  }

  const payload = await parse(response)
  if (!response.ok) {
    throw new ApiError(response.status, messageFrom(payload, response.statusText), payload)
  }
  return payload as T
}

export const api = {
  restoreSession: async (): Promise<User | null> => {
    const response = await fetch(apiUrl('/api/auth/refresh/'), {
      method: 'POST',
      credentials: 'include',
    })
    if (!response.ok) return null
    const data = (await response.json()) as { access_token: string; user: User }
    accessToken = data.access_token
    return data.user
  },

  signInWithGoogle: async (idToken: string): Promise<User> => {
    const data = await request<{ access_token: string; user: User }>('/api/auth/google/', {
      method: 'POST',
      body: { id_token: idToken },
      retryOnUnauthorized: false,
    })
    accessToken = data.access_token
    return data.user
  },

  signInAsDeveloper: async (email: string): Promise<User> => {
    const data = await request<{ access_token: string; user: User }>('/api/auth/dev/', {
      method: 'POST',
      body: { email },
      retryOnUnauthorized: false,
    })
    accessToken = data.access_token
    return data.user
  },

  signOut: async (): Promise<void> => {
    await request('/api/auth/logout/', { method: 'POST', retryOnUnauthorized: false })
    accessToken = null
  },

  listProjects: () => request<ProjectSummary[]>('/api/projects/'),

  getProject: (id: string) => request<Project>(`/api/projects/${id}/`),

  deleteProject: (id: string) => request<null>(`/api/projects/${id}/`, { method: 'DELETE' }),

  renameProject: (id: string, name: string) =>
    request<Project>(`/api/projects/${id}/`, { method: 'PATCH', body: { name } }),

  getUploadTicket: (filename: string, sizeBytes: number) =>
    request<UploadTicket>('/api/upload-ticket/', {
      method: 'POST',
      body: { filename, size_bytes: sizeBytes },
    }),

  createProject: (payload: {
    id: string
    name: string
    filename: string
    storage_path: string
    size_bytes: number
    page_count: number
  }) => request<Project>('/api/projects/', { method: 'POST', body: payload }),

  getSourceUrl: (id: string) =>
    request<{ url: string; expires_in: number }>(`/api/projects/${id}/source/`),

  saveAnnotations: (
    projectId: string,
    drawings: { drawing_id: string; annotations: Annotation[] }[],
  ) =>
    request<Project>(`/api/projects/${projectId}/annotations/`, {
      method: 'PUT',
      body: { drawings },
    }),

  /**
   * Delete one rectangle straight away, rather than waiting for Save.
   *
   * Scoped under its project: `/api/projects/{id}/` on its own deletes the
   * whole folder, so the annotation id has to be part of the path.
   */
  deleteAnnotation: (projectId: string, annotationId: string) =>
    request<null>(`/api/projects/${projectId}/annotations/${annotationId}/`, {
      method: 'DELETE',
    }),
}

/**
 * Send the PDF straight to object storage on the signed URL.
 *
 * It never passes through the API, so a large drawing set does not occupy a
 * web worker for the length of the transfer.
 */
export async function uploadToStorage(ticket: UploadTicket, file: File): Promise<void> {
  // The on-disk backend returns a root-relative URL, which a browser would
  // otherwise resolve against the page's origin rather than the API's — fine
  // behind the Vite proxy, wrong when the SPA talks to Django directly.
  const response = await fetch(apiUrl(ticket.upload_url), {
    method: ticket.method,
    headers: ticket.headers,
    // Never cookies: both backends authorize the upload with the signed token
    // in the URL, and omitting credentials keeps this out of CORS' stricter
    // credentialed path.
    credentials: 'omit',
    body: file,
  })
  if (!response.ok) {
    throw new ApiError(response.status, 'The file could not be uploaded. Please try again.')
  }
}
