'use client'
import React, { useState } from 'react'
import axios, { AxiosError } from 'axios'
import toast from 'react-hot-toast'
import { Upload, Loader2 } from 'lucide-react'

interface UploadResult {
  filename: string
  status: string
  preview?: string
}

interface APIResponse {
  summary: string
  results: UploadResult[]
}

interface Props {
  onUploadComplete: (data: { filename: string; text: string }) => void
}

const FileUpload: React.FC<Props> = ({ onUploadComplete }) => {
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    setUploading(true)
    setProgress(0)

    const formData = new FormData()
    Array.from(files).forEach((file) => {
      formData.append('files', file)
    })

    const uploadToast = toast.loading('Uploading and processing file(s)...')

    try {
      const response = await axios.post<APIResponse>(
        `${process.env.NEXT_PUBLIC_API_URL}/upload`,
        formData,
        {
          headers: { 'Content-Type': 'multipart/form-data' },
          onUploadProgress: (event) => {
            if (event.total) {
              const percent = Math.round((event.loaded * 100) / event.total)
              setProgress(percent)
            }
          },
        }
      )

      const { results } = response.data
      const successCount = results.filter((r) => r.status.startsWith('✅')).length
      const failCount = results.length - successCount

      if (successCount > 0) {
        toast.success(`${successCount} file(s) embedded successfully`, { id: uploadToast })
      } else {
        toast.error('❌ All uploads failed.', { id: uploadToast })
      }

      if (failCount > 0) {
        results
          .filter((r) => !r.status.startsWith('✅'))
          .forEach((r) => toast.error(`❌ ${r.filename}: ${r.status}`))
      }

      const firstSuccessful = results.find(r => r.preview)
      if (firstSuccessful) {
        onUploadComplete({
          filename: firstSuccessful.filename,
          text: firstSuccessful.preview || ''
        })
      }

    } catch (error) {
      const err = error as AxiosError<{ detail?: string }>
      const message =
        err.response?.data?.detail || err.message || 'Upload failed. Please try again.'
      toast.error(`❌ Upload error: ${message}`, { id: uploadToast })
    } finally {
      setUploading(false)
      setProgress(0)
    }
  }

  return (
    <div className="w-full flex flex-col items-center">
      <label className="block text-gray-300 mb-3 font-medium flex items-center gap-2">
        <Upload size={18} className="text-blue-400" />
        Upload PDF file(s):
      </label>

      <input
        type="file"
        accept="application/pdf"
        multiple
        onChange={handleFileChange}
        disabled={uploading}
        className="block w-full text-sm text-gray-200
                   file:mr-4 file:py-2 file:px-4
                   file:rounded-lg file:border-0
                   file:text-sm file:font-medium
                   file:bg-blue-500/20 file:text-blue-300
                   hover:file:bg-blue-500/30 cursor-pointer
                   transition-all duration-300"
      />

      {uploading && (
        <>
          <div className="w-full bg-gray-800 rounded-full h-2 mt-4 overflow-hidden">
            <div
              className="bg-gradient-to-r from-blue-500 to-teal-400 h-2 transition-all"
              style={{ width: `${progress}%` }}
            ></div>
          </div>
          <div className="flex items-center gap-2 text-gray-400 mt-3 text-sm animate-pulse">
            <Loader2 size={16} className="animate-spin" /> Uploading...
          </div>
        </>
      )}
    </div>
  )
}

export default FileUpload
