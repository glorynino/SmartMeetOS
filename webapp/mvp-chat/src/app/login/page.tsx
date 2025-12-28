'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    console.log('Login attempt:', email)
    router.push('/chat') // Redirection après login
  }

  return (
    <div className="max-w-md mx-auto mt-20 p-8 bg-white rounded-xl shadow">
      <div className="mb-8">
        <div className="w-12 h-12 bg-[#2a1f73] rounded-lg flex items-center justify-center mx-auto mb-4">
          <span className="text-white font-bold text-xl">AI</span>
        </div>
        <h2 className="text-2xl font-bold text-center mb-2">Welcome back</h2>
        <p className="text-gray-600 text-center">Log in to your AI Agents account</p>
      </div>
      
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium mb-1">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2a1f73]"
            required
          />
        </div>
        
        <div>
          <label className="block text-sm font-medium mb-1">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            className="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2a1f73]"
            required
          />
        </div>
        
        <button
          type="submit"
          className="w-full bg-[#2a1f73] text-white p-3 rounded-lg hover:bg-[#3e2ba9] font-medium"
        >
          Log In
        </button>
      </form>
      
      {/* Bypass pour MVP */}
      <div className="mt-6 pt-6 border-t text-center">
        <button
          onClick={() => router.push('/chat')}
          className="text-sm text-gray-600 hover:text-[#2a1f73] underline"
        >
          Continue without account (MVP)
        </button>
      </div>
      
      {/* Lien vers Sign Up */}
      <div className="mt-8 text-center">
        <p className="text-gray-600">
          Don't have an account?{' '}
          <Link href="/signup" className="text-[#2a1f73] hover:underline font-medium">
            Sign Up
          </Link>
        </p>
      </div>
    </div>
  )
}