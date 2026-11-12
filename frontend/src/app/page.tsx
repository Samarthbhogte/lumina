'use client'
import React, { useState } from 'react'
import FileUpload from '../components/FileUpload'
import ChatBox from '../components/ChatBox'
import ResponseCard from '../components/ResponseCard'
import { Toaster } from 'react-hot-toast'

export default function HomePage() {
  const [responses, setResponses] = useState<
    { question: string; answer: string; sources: string[] }[]
  >([])

  const handleUploadComplete = () => {
    // Text no longer needed to display
  }

  const handleNewResponse = (
    question: string,
    answer: string,
    sources: string[]
  ) => {
    setResponses((prev) => [...prev, { question, answer, sources }])
  }

  return (
    <main className="min-h-screen w-full flex flex-col items-center bg-gradient-to-br from-gray-950 via-gray-900 to-gray-800 text-white px-6 py-10">
      {/* Toast Notification System */}
      <Toaster position="top-center" />

      {/* Header */}
      <header className="text-center mb-10">
        <h1 className="text-4xl font-extrabold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-teal-400">
          Lumina — Compliance Intelligence
        </h1>
        <p className="text-gray-400 mt-2 text-lg">
          Upload policy PDFs, ask complex compliance questions, and get precise AI answers.
        </p>
      </header>

      {/* Upload Section */}
      <section className="w-full max-w-4xl bg-gray-900/70 border border-gray-700 backdrop-blur-xl p-6 rounded-2xl shadow-lg hover:shadow-blue-900/20 transition-all">
        <FileUpload onUploadComplete={handleUploadComplete} />
      </section>

      {/* Chat Input */}
      <section className="mt-10 w-full max-w-4xl bg-gray-900/70 border border-gray-700 backdrop-blur-xl rounded-2xl p-6 shadow-lg hover:shadow-teal-900/20 transition-all">
        <ChatBox onResponseGenerated={handleNewResponse} />
      </section>

      {/* Render Answers */}
      {responses.length > 0 && (
        <section className="mt-10 w-full max-w-4xl space-y-4">
          {responses.map((res, idx) => (
            <ResponseCard
              key={idx}
              question={res.question}
              answer={res.answer}
              sources={res.sources}
            />
          ))}
        </section>
      )}

      {/* Footer */}
      <footer className="mt-20 text-gray-500 text-sm">
        © {new Date().getFullYear()} Lumina AI — Compliance Assistant Platform
      </footer>
    </main>
  )
}
