'use client'

import { useState, useRef, useEffect } from 'react'
import { api } from '@/lib/api' // ⬅️ Assurez-vous d'avoir ce fichier

type Message = {
  id: number
  text: string
  isUser: boolean
}

const HARDCODED_USER_ID = '850fc7f7-22a6-43be-a2f1-0649cce9c5c7'

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([
    { 
      id: 1, 
      text: `Bonjour ! Je suis votre assistant AI. (User ID: ${HARDCODED_USER_ID}) Posez-moi une question sur vos meetings.`, 
      isUser: false 
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const sendMessage = async () => {
    if (!input.trim() || loading) return
    
    // Message utilisateur
    const userMessage: Message = {
      id: Date.now(),
      text: input,
      isUser: true
    }
    
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setLoading(true)
    
    try {
      // ⚠️ Appel API pour sauvegarder le prompt
      const result = await api.saveUserPrompt(HARDCODED_USER_ID, input)
      console.log('Prompt saved:', result)
      
      // Simulation réponse IA avec confirmation
      setTimeout(() => {
        const aiResponse: Message = {
          id: Date.now() + 1,
          text: `✅ Prompt sauvegardé pour l'utilisateur "${HARDCODED_USER_ID}".\n\nVotre message: "${input}"\n\n(Simulation MVP - Connectez à une vraie AI pour des réponses)`,
          isUser: false
        }
        setMessages(prev => [...prev, aiResponse])
        setLoading(false)
      }, 800)
      
    } catch (error) {
      console.error('Erreur API:', error)
      // Message d'erreur
      const errorMessage: Message = {
        id: Date.now() + 1,
        text: `❌ Erreur: Impossible de sauvegarder le prompt. Vérifiez que l'API est lancée sur http://localhost:8000`,
        isUser: false
      }
      setMessages(prev => [...prev, errorMessage])
      setLoading(false)
    }
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex flex-col h-[calc(100vh-140px)]">
        {/* En-tête avec info utilisateur */}
        <div className="mb-4 p-4 bg-white rounded-lg shadow">
          <h1 className="text-xl font-bold mb-2">Recaply Chat</h1>
          <div className="text-sm text-gray-600">
            <span>Utilisateur: </span>
            <code className="bg-gray-100 px-2 py-1 rounded text-[#3e2ba9] font-mono">
              {HARDCODED_USER_ID}
            </code>
            <span className="ml-2 text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded">
              Hardcodé pour MVP
            </span>
          </div>
        </div>
        
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${msg.isUser ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[80%] p-4 rounded-2xl ${
                  msg.isUser
                    ? 'bg-[#3e2ba9] text-white rounded-tr-none'
                    : 'bg-gray-100 text-gray-800 rounded-tl-none border border-gray-200'
                }`}
              >
                {msg.text.split('\n').map((line, i) => (
                  <p key={i} className={i > 0 ? 'mt-2' : ''}>{line}</p>
                ))}
              </div>
            </div>
          ))}
          
          {loading && (
            <div className="flex justify-start">
              <div className="bg-gray-100 text-gray-800 p-4 rounded-2xl rounded-tl-none">
                <div className="flex items-center space-x-2">
                  <div className="w-2 h-2 bg-gray-500 rounded-full animate-pulse"></div>
                  <div className="w-2 h-2 bg-gray-500 rounded-full animate-pulse" style={{animationDelay: '0.2s'}}></div>
                  <div className="w-2 h-2 bg-gray-500 rounded-full animate-pulse" style={{animationDelay: '0.4s'}}></div>
                  <span className="text-sm">Envoi à l'API...</span>
                </div>
              </div>
            </div>
          )}
          
          <div ref={messagesEndRef} />
        </div>
        
        {/* Input */}
        <div className="border-t p-4 bg-white">
          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage()}
              placeholder={`Tapez votre prompt (sera sauvegardé pour ${HARDCODED_USER_ID})...`}
              disabled={loading}
              className="flex-1 p-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-[#3e2ba9] disabled:opacity-50"
            />
            <button
              onClick={sendMessage}
              disabled={loading || !input.trim()}
              className="bg-[#3e2ba9] text-white px-6 rounded-lg hover:bg-[#2a1d8a] disabled:opacity-50 font-medium"
            >
              {loading ? 'Envoi...' : 'Envoyer'}
            </button>
          </div>
          <div className="mt-2 text-xs text-gray-500 flex justify-between">
            <span>
              API: POST /api/users/
              <code className="bg-gray-100 px-1 mx-1">{HARDCODED_USER_ID}</code>
              /prompt
            </span>
            <span className="text-[#3e2ba9]">MVP Demo</span>
          </div>
        </div>
      </div>
    </div>
  )
}