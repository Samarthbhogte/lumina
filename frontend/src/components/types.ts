import type { AskResult, Source } from '@/lib/api'

export interface UserMessage {
  id: string
  role: 'user'
  content: string
}

export interface AssistantMessage {
  id: string
  role: 'assistant'
  content: string
  status: 'streaming' | 'done' | 'error'
  question: string
  sources: Source[]
  result?: AskResult
  error?: string
}

export type Message = UserMessage | AssistantMessage
