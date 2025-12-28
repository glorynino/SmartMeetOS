'use client'

import { useState, useEffect } from 'react'

type BotStatus = {
  is_running: boolean
  status: string
  last_activity?: string
}

export default function SettingsPage() {
  const [apiKey, setApiKey] = useState('')
  const [notionToken, setNotionToken] = useState('')
  const [botStatus, setBotStatus] = useState<BotStatus | null>(null)
  const [loadingBot, setLoadingBot] = useState(false)
  const [savingApiKey, setSavingApiKey] = useState(false)
  const [savingNotion, setSavingNotion] = useState(false)

  // Chargement des valeurs sauvegardées au montage
  useEffect(() => {
    const savedApiKey = localStorage.getItem('openaiApiKey')
    if (savedApiKey) setApiKey(savedApiKey)

    const savedNotionToken = localStorage.getItem('notionToken')
    if (savedNotionToken) setNotionToken(savedNotionToken)

    // Simulation initiale du bot (à remplacer par l'API réelle plus tard)
    setBotStatus({
      is_running: false,
      status: 'stopped'
    })
  }, [])

  // --- Gestion du Bot (simulation pour l'instant) ---
  const handleStartBot = async () => {
    setLoadingBot(true)
    // await api.startBot()  // À décommenter plus tard
    setTimeout(() => {
      setBotStatus({
        is_running: true,
        status: 'running',
        last_activity: new Date().toLocaleString('fr-FR'),
      })
      setLoadingBot(false)
    }, 800)
  }

  const handleStopBot = async () => {
    setLoadingBot(true)
    // await api.stopBot()  // À décommenter plus tard
    setTimeout(() => {
      setBotStatus({
        is_running: false,
        status: 'stopped',
      })
      setLoadingBot(false)
    }, 800)
  }

  // --- Sauvegarde Clé API ---
  const handleSaveApiKey = () => {
    if (!apiKey.trim()) {
      alert('Veuillez entrer une clé API valide.')
      return
    }
    setSavingApiKey(true)
    localStorage.setItem('openaiApiKey', apiKey.trim())
    setTimeout(() => {
      alert('Clé API sauvegardée avec succès !')
      setSavingApiKey(false)
    }, 500)
  }

  // --- Sauvegarde Token Notion ---
  const handleSaveNotionToken = () => {
    if (!notionToken.trim()) {
      alert('Veuillez entrer un token Notion valide.')
      return
    }
    setSavingNotion(true)
    localStorage.setItem('notionToken', notionToken.trim())
    setTimeout(() => {
      alert('Token Notion sauvegardé avec succès !')
      setSavingNotion(false)
    }, 500)
  }

  return (
    <div className="max-w-2xl mx-auto mt-10 p-6">
      <h1 className="text-2xl font-bold mb-6">Paramètres</h1>

      <div className="space-y-6">

        {/* Bot Status */}
        <div className="bg-white p-6 rounded-xl shadow">
          <h2 className="text-lg font-semibold mb-4">Statut du Bot</h2>

          {botStatus ? (
            <div className="space-y-2 mb-4">
              <div className="flex items-center">
                <div className={`w-3 h-3 rounded-full mr-2 ${botStatus.is_running ? 'bg-green-500' : 'bg-red-500'}`} />
                <span>
                  Statut : <strong>{botStatus.is_running ? 'En cours' : 'Arrêté'}</strong>
                </span>
              </div>
              <div className="text-sm text-gray-600">
                Dernière activité : {botStatus.last_activity || 'Jamais'}
              </div>
            </div>
          ) : (
            <p className="text-gray-500 mb-4">Chargement...</p>
          )}

          <div className="flex space-x-4">
            <button
              onClick={handleStartBot}
              disabled={loadingBot || botStatus?.is_running}
              className="bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loadingBot ? 'Démarrage...' : 'Démarrer le Bot'}
            </button>
            <button
              onClick={handleStopBot}
              disabled={loadingBot || !botStatus?.is_running}
              className="bg-red-600 text-white px-4 py-2 rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loadingBot ? 'Arrêt...' : 'Arrêter le Bot'}
            </button>
          </div>
        </div>

        {/* Clé API (OpenAI ou autre) */}
        <div className="bg-white p-6 rounded-xl shadow">
          <h2 className="text-lg font-semibold mb-4">Clé API IA</h2>
          <p className="text-sm text-gray-600 mb-4">
            Clé OpenAI, Anthropic, Grok, etc. (commence généralement par sk-...)
          </p>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-..."
            className="w-full p-3 border border-gray-300 rounded-lg mb-4 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            onClick={handleSaveApiKey}
            disabled={savingApiKey}
            className="bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {savingApiKey ? 'Sauvegarde...' : 'Sauvegarder la clé API'}
          </button>
        </div>

        {/* Token Notion */}
        <div className="bg-white p-6 rounded-xl shadow">
          <h2 className="text-lg font-semibold mb-4">Intégration Notion</h2>
          <p className="text-sm text-gray-600 mb-4">
            Token d'intégration interne Notion (<strong>Internal Integration Token</strong>)<br />
            Il commence par <code className="bg-gray-100 px-1 rounded">secret_</code>
          </p>
          <input
            type="password"
            value={notionToken}
            onChange={(e) => setNotionToken(e.target.value)}
            placeholder="secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            className="w-full p-3 border border-gray-300 rounded-lg mb-4 focus:outline-none focus:ring-2 focus:ring-purple-500"
          />
          <button
            onClick={handleSaveNotionToken}
            disabled={savingNotion}
            className="bg-purple-600 text-white px-6 py-2 rounded-lg hover:bg-purple-700 disabled:opacity-50"
          >
            {savingNotion ? 'Sauvegarde...' : 'Sauvegarder le token Notion'}
          </button>
        </div>

      </div>
    </div>
  )
}