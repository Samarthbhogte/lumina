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
  ai_configured: boolean
  provider: string
  chat_model: string
  documents: number
  chunks: number
}

export interface HistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

// Same-origin: Next.js proxies /api/* to FastAPI (see next.config.ts), so session cookies
// reach every request and no CORS is needed.
const API = '/api'

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
    throw new ApiError("Can't reach the Lumina API. Is the backend running?", 0)
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
    throw new ApiError("Can't reach the Lumina API. Is the backend running?", 0)
  }
  if (!res.ok || !res.body) throw await errorFrom(res)

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  let finished = false

  const handle = (block: string) => {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith(':')) continue // comment / heartbeat
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
    }
    if (!data.length) return
    let payload
    try {
      payload = JSON.parse(data.join('\n'))
    } catch {
      throw new ApiError('The server sent a malformed response.', 502)
    }
    if (event === 'sources') handlers.onSources(payload)
    else if (event === 'token') handlers.onToken(payload.text)
    else if (event === 'done') {
      finished = true
      handlers.onDone(payload)
    } else if (event === 'error') throw new ApiError(payload.message, 502)
  }

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer = (buffer + value).replace(/\r\n?/g, '\n')
      let split: number
      while ((split = buffer.indexOf('\n\n')) !== -1) {
        handle(buffer.slice(0, split))
        buffer = buffer.slice(split + 2)
      }
    }
    if (buffer.trim()) handle(buffer)
  } finally {
    reader.cancel().catch(() => {})
  }
  if (!finished) throw new ApiError('The answer was cut off. Please try again.', 0)
}
