'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { api, MeetingDetail } from '@/lib/api'

export default function MeetingDetailPage() {
  const params = useParams()
  const [meeting, setMeeting] = useState<MeetingDetail | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (params.id) {
      loadMeeting(params.id as string)
    }
  }, [params.id])

  const loadMeeting = async (id: string) => {
    try {
      const data = await api.getMeeting(id)
      setMeeting(data)
    } catch (err) {
      console.error('Failed to load meeting', err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="p-8">Loading...</div>
  if (!meeting) return <div className="p-8">Meeting not found</div>

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">{meeting.title}</h1>
        <p className="text-gray-600">
          {new Date(meeting.start_time).toLocaleString()}
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* Transcript */}
        <div className="bg-white p-6 rounded-lg shadow">
          <h2 className="text-lg font-semibold mb-4">Transcript</h2>
          <div className="whitespace-pre-wrap bg-gray-50 p-4 rounded max-h-96 overflow-y-auto">
            {meeting.transcript || 'No transcript available'}
          </div>
        </div>

        {/* Chunks */}
        <div className="bg-white p-6 rounded-lg shadow">
          <h2 className="text-lg font-semibold mb-4">Conversation</h2>
          <div className="space-y-4 max-h-96 overflow-y-auto">
            {meeting.chunks.map((chunk) => (
              <div key={chunk.index} className="border-l-4 border-blue-500 pl-4">
                <div className="font-medium text-blue-700">{chunk.speaker}</div>
                <div className="text-gray-700">{chunk.content}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}