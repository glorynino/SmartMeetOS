'use client' 

import { usePathname } from 'next/navigation'
import Link from 'next/link'
import './globals.css'

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const pathname = usePathname()
  const hideAuthNav = ['/chat', '/settings'].includes(pathname || '')
  
  return (
    <html lang="fr">
      <head>
        <title>Recaply</title>
        <meta name="description" content="" />
        <link rel="icon" href='/mini.png' />
      </head>
      <body>
        {/* Navigation intégrée */}
        <nav className="bg-white border-b border-gray-200 px-4 py-3">
          <div className="max-w-6xl mx-auto flex justify-between items-center">
            <div className="flex items-center space-x-3">
              <div className="relative w-30 h-10">
                <img 
                  src="/logo.png" 
                  alt="Logo" 
                  className="w-full h-full object-contain"
                />
              </div>
            </div>
            
            <div className="flex items-center space-x-4">
              {!hideAuthNav ? (
                <>
                  <Link href="/login" className="text-gray-700 hover:text-[#3e2ba9] font-medium">
                    Log In
                  </Link>
                  <Link href="/signup" className="bg-[#3e2ba9] text-white px-4 py-2 rounded-lg hover:bg-[#2a1d8a] font-medium">
                    Sign Up
                  </Link>
                </>
              ) : (
                <>
                   <Link href="/meetings" className={`px-3 py-2 rounded-lg font-medium ${pathname === '/meetings' ? 'bg-gray-100 text-gray-900' : 'text-gray-700 hover:text-[#3e2ba9]'}`}>
                     Meetings
                   </Link>
                  <Link href="/chat" className={`px-3 py-2 rounded-lg font-medium ${pathname === '/chat' ? 'bg-gray-100 text-gray-900' : 'text-gray-700 hover:text-[#3e2ba9]'}`}>
                    Chat
                  </Link>
                  <Link href="/settings" className={`px-3 py-2 rounded-lg font-medium ${pathname === '/settings' ? 'bg-gray-100 text-gray-900' : 'text-gray-700 hover:text-[#3e2ba9]'}`}>
                    Settings
                  </Link>
                  <div className="w-8 h-8 bg-gradient-to-r from-[#3e2ba9] to-[#6d5ce8] rounded-full flex items-center justify-center text-white font-medium">
                    U
                  </div>
                </>
              )}
            </div>
          </div>
        </nav>
        
        <main className="min-h-screen bg-gray-50">
          {children}
        </main>
      </body>
    </html>
  )
}