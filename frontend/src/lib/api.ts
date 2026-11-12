// Typed client for the Lumina API. Shapes mirror backend/schemas.py.

export type Confidence = 'high' | 'medium' | 'low'

export interface Source {
  n: number
  document_id: string
  filename: string
  page: number
  snippet: string
  score: number
}

export interface AskResult {
  answer: string
  sources: Source[]
  cited: number[]
  confidence: Confidence
  found: boolean
  flagged: boolean
}

export interface DocumentInfo {
  id: string
  filename: string
  pages: number
  chunks: number
  size_bytes: number
  uploaded_at: string
}

export interface UploadResult {
  filename: string
  status: 'indexed' | 'duplicate' | 'failed'
  document: DocumentInfo | null
  error: string | null
}

export interface Health {
  status: 'ok'
  openai_configured: boolean
  chat_model: string
  documents: number
  chunks: number
}

export interface HistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

// Accept values with or without a trailing /api so older .env files keep working.
const API_ROOT = (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000')
  .replace(/\/+$/, '')
  .replace(/\/api$/, '')
const API = `${API_ROOT}/api`

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
  }
}

async function errorFrom(res: Response): Promise<ApiError> {
  let message = `Request failed (${res.status})`
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') message = body.detail
    else if (Array.isArray(body?.detail) && body.detail[0]?.msg) message = body.detail[0].msg
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(message.replace(/^Value error, /, ''), res.status)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API}${path}`, init)
  } catch {
    throw new ApiError(`Can't reach the Lumina API at ${API_ROOT}. Is the backend running?`, 0)
  }
  if (!res.ok) throw await errorFrom(res)
  return (res.status === 204 ? undefined : await res.json()) as T
}

export const getHealth = () => request<Health>('/health')

export const listDocuments = () => request<DocumentInfo[]>('/documents')

export const deleteDocument = (id: string) =>
  request<void>(`/documents/${id}`, { method: 'DELETE' })

export function uploadDocuments(files: File[]) {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  return request<{ results: UploadResult[] }>('/documents', { method: 'POST', body: form })
}

export const documentFileUrl = (id: string, page?: number) =>
  `${API}/documents/${id}/file${page ? `#page=${page}` : ''}`

export interface StreamHandlers {
  onSources: (sources: Source[]) => void
  onToken: (text: string) => void
  onDone: (result: AskResult) => void
}

/** POST a question and read the server-sent event stream until `done`. */
export async function askStream(
  body: { question: string; history: HistoryMessage[]; document_ids?: string[] },
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${API}/ask/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err
    throw new ApiError(`Can't reach the Lumina API at ${API_ROOT}. Is the backend running?`, 0)
  }
  if (!res.ok || !res.body) throw await errorFrom(res)

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  let finished = false
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let split: number
    while ((split = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, split)
      buffer = buffer.slice(split + 2)
      const event = /^event: (.+)$/m.exec(block)?.[1]
      const data = /^data: (.*)$/m.exec(block)?.[1]
      if (!event || data === undefined) continue
      const payload = JSON.parse(data)
      if (event === 'sources') handlers.onSources(payload)
      else if (event === 'token') handlers.onToken(payload.text)
      else if (event === 'done') {
        finished = true
        handlers.onDone(payload)
      } else if (event === 'error') throw new ApiError(payload.message, 502)
    }
  }
  if (!finished) throw new ApiError('The answer was cut off. Please try again.', 0)
}
