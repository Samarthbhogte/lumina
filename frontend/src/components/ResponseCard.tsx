'use client'
import React from 'react'
import { motion } from 'framer-motion'

interface Props {
  question: string
  answer: string
  sources?: string[]  // Optional in case some responses don't include sources
}

const ResponseCard: React.FC<Props> = ({ question, answer, sources = [] }) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: 'easeOut' }}
      className="relative bg-gray-900/70 backdrop-blur-md border border-gray-800 
                 rounded-2xl shadow-lg hover:shadow-blue-900/20 p-6 transition-all duration-300"
    >
      <div className="mb-4">
        <p className="text-sm font-semibold text-blue-400 mb-1">You:</p>
        <p className="text-gray-200 whitespace-pre-wrap leading-relaxed">{question}</p>
      </div>

      <div className="pt-4 border-t border-gray-700">
        <p className="text-sm font-semibold text-teal-400 mb-1">Lumina:</p>
        <p className="text-gray-100 whitespace-pre-wrap leading-relaxed">{answer}</p>
      </div>

      {sources.length > 0 && (
        <div className="mt-4 border-t border-gray-700 pt-3 text-sm text-gray-400">
          <p className="font-semibold text-blue-300 mb-1">📁 Source Files:</p>
          <ul className="list-disc list-inside">
            {sources.map((src, idx) => (
              <li key={idx}>{src}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="absolute top-0 left-0 w-full h-[2px] bg-gradient-to-r from-blue-500 via-teal-400 to-blue-500 rounded-t-2xl opacity-70"></div>
    </motion.div>
  )
}

export default ResponseCard
