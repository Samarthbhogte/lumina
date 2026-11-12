'use client'
import React, { useState } from 'react'
import axios, { AxiosError } from 'axios'
import { Send } from 'lucide-react'

interface Props {
  onResponseGenerated: (
    question: string,
    answer: string,
    sources: string[]
  ) => void
}

interface AskResponse {
  answer: string
  source_documents?: string[] | { source: string }[]
}

interface APIError {
  detail?: string
}

const ChatBox: React.FC<Props> = ({ onResponseGenerated }) => {
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!question.trim()) return

    setLoading(true)
    setError(null)

    try {
      const response = await axios.post<AskResponse>(
        `${process.env.NEXT_PUBLIC_API_URL}/ask`,
        { question }
      )

      const { answer, source_documents } = response.data

let sources: string[] = []
if (Array.isArray(source_documents)) {
  sources = source_documents.map((src) =>
    typeof src === 'string' ? src : (src as { source?: string })?.source || 'Unknown'
  )
}


      onResponseGenerated(question, answer, sources)
      setQuestion('')
    } catch (err) {
      const errorObj = err as AxiosError<APIError>
      const message =
        errorObj.response?.data?.detail ||
        errorObj.message ||
        'Failed to get a response.'
      setError(message)
      console.error('❌ Chat error:', message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative w-full">
      <form
        onSubmit={handleSubmit}
        className="flex items-center bg-gray-800/60 border border-gray-700 rounded-full shadow-lg 
                 backdrop-blur-md px-5 py-3 transition-all duration-300 focus-within:border-blue-500"
      >
        <input
          type="text"
          placeholder="Ask Lumina anything about your compliance document..."
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={loading}
          className="flex-grow bg-transparent outline-none text-gray-100 placeholder-gray-500 text-sm md:text-base"
        />

        <button
          type="submit"
          disabled={loading}
          className={`ml-3 p-2 rounded-full transition-all duration-300 ${
            loading
              ? 'bg-gray-700 cursor-not-allowed'
              : 'bg-gradient-to-r from-blue-500 to-teal-400 hover:opacity-90'
          }`}
        >
          <Send size={18} className="text-white" />
        </button>
      </form>

      {error && <p className="text-red-400 mt-2 text-sm text-center">{error}</p>}

      {loading && (
        <div className="mt-3 flex justify-center">
          <div className="w-5 h-5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin"></div>
        </div>
      )}
    </div>
  )
}

export default ChatBox
