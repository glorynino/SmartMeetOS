'use client'

import { usePathname } from 'next/navigation'
import Link from 'next/link'

export default function Navigation() {
  const pathname = usePathname()
  
  // FORCEZ l'affichage des liens app
  const forceAppNav = true // Changez en false pour voir login/signup
  
  return (
    <nav className="bg-white border-b border-gray-200 px-4 py-3">
      <div className="max-w-6xl mx-auto flex justify-between items-center">
        <div className="flex items-center space-x-3">
          <div className="relative w-10 h-10">
            <img 
              src="/logo.png" 
              alt="Logo" 
              className="w-full h-full object-contain"
            />
          </div>
          <h1 className="text-xl font-semibold text-gray-900">Recaply</h1>
        </div>
        
        <div className="flex items-center space-x-4">
          {forceAppNav ? (
            // TOUJOURS montrer Meetings, Chat, Settings
            <>
              <Link href="/meetings" className="px-3 py-2 rounded-lg font-medium text-gray-700 hover:text-[#3e2ba9]">
                Meetings
              </Link>
              <Link href="/chat" className="px-3 py-2 rounded-lg font-medium text-gray-700 hover:text-[#3e2ba9]">
                Chat
              </Link>
              <Link href="/settings" className="px-3 py-2 rounded-lg font-medium text-gray-700 hover:text-[#3e2ba9]">
                Settings
              </Link>
              <div className="w-8 h-8 bg-gradient-to-r from-[#3e2ba9] to-[#6d5ce8] rounded-full flex items-center justify-center text-white font-medium">
                U
              </div>
            </>
          ) : (
            // Montrer login/signup
            <>
              <Link href="/login" className="text-gray-700 hover:text-[#3e2ba9] font-medium">
                Log In
              </Link>
              <Link href="/signup" className="bg-[#3e2ba9] text-white px-4 py-2 rounded-lg hover:bg-[#2a1d8a] font-medium">
                Sign Up
              </Link>
            </>
          )}
        </div>
      </div>
    </nav>
  )
}