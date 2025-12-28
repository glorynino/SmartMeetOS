'use client'

import { useEffect, useState } from 'react'
//import { api, Meeting } from '@/lib/api'

export default function MeetingsPage() {
  const [meetings, setMeetings] = useState<Meeting[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    loadMeetings()
  }, [])

  const loadMeetings = async () => {
    try {
      setLoading(true)
      const data = await api.getMeetings()
      setMeetings(data.meetings)
    } catch (err) {
      setError('Failed to load meetings')
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="p-8">Loading meetings...</div>
  if (error) return <div className="p-8 text-red-600">{error}</div>

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-6">Meetings</h1>
      
      <div className="grid gap-4">
        {meetings.map((meeting) => (
          <div key={meeting.id} className="bg-white p-4 rounded-lg shadow">
            <h3 className="font-semibold">{meeting.title}</h3>
            <p className="text-sm text-gray-600">
              {new Date(meeting.start_time).toLocaleString()}
            </p>
            <div className="flex items-center justify-between mt-2">
              <span className={`px-2 py-1 rounded text-xs ${
                meeting.status === 'completed' 
                  ? 'bg-green-100 text-green-800' 
                  : 'bg-yellow-100 text-yellow-800'
              }`}>
                {meeting.status}
              </span>
              <button
                onClick={() => window.location.href = `/meetings/${meeting.id}`}
                className="text-blue-600 hover:text-blue-800 text-sm"
              >
                View Details
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}