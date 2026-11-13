// Typed client for the Lumina API. Shapes mirror backend/schemas.py.

export type Confidence = 'high' | 'medium' | 'low'

export interface Source {
  n: number
  document_id: string
  filename: string
  page: number
  snippet: string
  score: number
  page_end?: number | null
  section?: string | null
  heading?: string | null
  clause?: string | null // set when the answer shows which clause it relied on
  label: string // e.g. "GDPR Sample Compliance §7.2, p.1"
}

export interface AskResult {
  answer: string
  sources: Source[]
  cited: number[]
  confidence: Confidence
  found: boolean
  flagged: boolean
  model?: string | null
  conversation_id?: string | null
  message_id?: string | null
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
  needs_setup: boolean
}

export type Role = 'viewer' | 'editor' | 'owner'

export interface WorkspaceInfo {
  id: string
  name: string
  kind: 'personal' | 'team'
  role: Role
}

export interface Me {
  user: { id: string; email: string; display_name: string; is_admin: boolean }
  workspaces: WorkspaceInfo[]
  questions_used_today: number
  questions_per_day: number
}

export interface Conversation {
  id: string
  title: string
  updated_at: string
}

export interface StoredMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  result: AskResult | null
  created_at: string
}

export interface Member {
  user_id: string
  email: string
  display_name: string
  role: Role
}

export interface Invite {
  id: string
  role: Role
  email: string | null
  expires_at: string
  link?: string | null
}

// Same-origin: Next.js proxies /api/* to FastAPI (see next.config.ts), so the session cookie
// reaches every request (including streams and PDF links) and no CORS is needed.
const API = '/api'
const UNREACHABLE = "Can't reach the Lumina API. Is the backend running?"

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

// State-changing requests carry a custom header the server requires (a CSRF defence:
// cross-site forms can't set it).
function withCsrf(init?: RequestInit): RequestInit {
  const method = (init?.method ?? 'GET').toUpperCase()
  if (method === 'GET' || method === 'HEAD') return init ?? {}
  return { ...init, headers: { ...(init?.headers ?? {}), 'X-Lumina-CSRF': '1' } }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API}${path}`, withCsrf(init))
  } catch {
    throw new ApiError(UNREACHABLE, 0)
  }
  if (!res.ok) throw await errorFrom(res)
  return (res.status === 204 ? undefined : await res.json()) as T
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

// ---------- accounts ----------

export const getHealth = () => request<Health>('/health')
export const getMe = () => request<Me>('/auth/me')
export const signIn = (email: string, password: string) => request<Me>('/auth/login', json('POST', { email, password }))
export const signUp = (body: { email: string; password: string; display_name: string; invite_token?: string }) =>
  request<Me>('/auth/signup', json('POST', body))
export const signOut = () => request<void>('/auth/logout', { method: 'POST' })
export const resetPassword = (token: string, new_password: string) =>
  request<void>('/auth/reset', json('POST', { token, new_password }))
export const previewInvite = (token: string) =>
  request<{ workspace: string; role: Role; signed_in: boolean }>(`/invites/${token}`)
export const acceptInvite = (token: string) => request<WorkspaceInfo>(`/invites/${token}/accept`, { method: 'POST' })

export const createWorkspace = (name: string) => request<WorkspaceInfo>('/workspaces', json('POST', { name }))
export const listMembers = (ws: string) => request<Member[]>(`/workspaces/${ws}/members`)
export const setMemberRole = (ws: string, userId: string, role: Role) =>
  request<Member>(`/workspaces/${ws}/members/${userId}`, json('PATCH', { role }))
export const removeMember = (ws: string, userId: string) =>
  request<void>(`/workspaces/${ws}/members/${userId}`, { method: 'DELETE' })
export const listInvites = (ws: string) => request<Invite[]>(`/workspaces/${ws}/invites`)
export const createInvite = (ws: string, role: Role, email?: string) =>
  request<Invite>(`/workspaces/${ws}/invites`, json('POST', { role, email: email || null }))
export const revokeInvite = (ws: string, id: string) =>
  request<void>(`/workspaces/${ws}/invites/${id}`, { method: 'DELETE' })

// ---------- workspace content ----------

export const listDocuments = (ws: string) => request<DocumentInfo[]>(`/workspaces/${ws}/documents`)

export const deleteDocument = (ws: string, id: string) =>
  request<void>(`/workspaces/${ws}/documents/${id}`, { method: 'DELETE' })

export function uploadDocuments(ws: string, files: File[]) {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  return request<{ results: UploadResult[] }>(`/workspaces/${ws}/documents`, { method: 'POST', body: form })
}

// Evidence packs: a PDF of recorded answers with an integrity hash (downloads, cookie-authenticated).
export const answerExportUrl = (ws: string, messageId: string) => `${API}/workspaces/${ws}/answers/${messageId}/export`
export const conversationExportUrl = (ws: string, conversationId: string) =>
  `${API}/workspaces/${ws}/conversations/${conversationId}/export`

export const documentFileUrl = (ws: string, id: string, page?: number) =>
  `${API}/workspaces/${ws}/documents/${id}/file${page ? `#page=${page}` : ''}`

export const listConversations = (ws: string) => request<Conversation[]>(`/workspaces/${ws}/conversations`)
export const getConversation = (ws: string, id: string) =>
  request<Conversation & { messages: StoredMessage[] }>(`/workspaces/${ws}/conversations/${id}`)
export const deleteConversation = (ws: string, id: string) =>
  request<void>(`/workspaces/${ws}/conversations/${id}`, { method: 'DELETE' })

export interface StreamHandlers {
  onSources: (sources: Source[]) => void
  onToken: (text: string) => void
  onDone: (result: AskResult) => void
}

/** POST a question and read the server-sent event stream until `done`. */
export async function askStream(
  ws: string,
  body: { question: string; conversation_id?: string | null; document_ids?: string[] },
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${API}/workspaces/${ws}/ask/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Lumina-CSRF': '1' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err
    throw new ApiError(UNREACHABLE, 0)
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
