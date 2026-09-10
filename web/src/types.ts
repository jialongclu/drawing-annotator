export type AnnotationKind = 'block' | 'capture'

/**
 * Geometry is normalized to the unrotated PDF page box, origin top-left, so a
 * rectangle lands in the same place at any zoom level or window size. Screen
 * pixels never cross the network.
 */
export interface Annotation {
  id: string
  kind: AnnotationKind
  x: number
  y: number
  w: number
  h: number
}

export interface Drawing {
  id: string
  page_number: number
  annotations: Annotation[]
}

export interface ProjectSummary {
  id: string
  name: string
  filename: string
  page_count: number
  size_bytes: number
  created_at: string
  updated_at: string
}

export interface Project extends ProjectSummary {
  drawings: Drawing[]
}

export interface User {
  id: string
  email: string
  display_name: string
  picture_url: string
}

export interface UploadTicket {
  file_id: string
  storage_path: string
  upload_url: string
  method: string
  headers: Record<string, string>
}
