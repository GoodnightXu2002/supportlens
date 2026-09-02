import { useEffect, useState } from 'react'

type ConnectionState = 'checking' | 'connected' | 'error'

type HealthResponse = {
  status: string
}

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
).replace(/\/$/, '')

function App() {
  const [connectionState, setConnectionState] =
    useState<ConnectionState>('checking')

  useEffect(() => {
    const controller = new AbortController()

    async function checkHealth() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/health`, {
          signal: controller.signal,
        })

        if (!response.ok) {
          throw new Error(`Health check returned ${response.status}`)
        }

        const health: HealthResponse = await response.json()
        setConnectionState(health.status === 'ok' ? 'connected' : 'error')
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') {
          return
        }
        setConnectionState('error')
      }
    }

    void checkHealth()
    return () => controller.abort()
  }, [])

  const stateCopy = {
    checking: 'Checking API connection…',
    connected: 'API connected',
    error: 'API unavailable',
  }[connectionState]

  return (
    <main className="shell">
      <section className="status-panel" aria-labelledby="page-title">
        <div className="wordmark">SupportLens</div>
        <div className="status-line">
          <span
            className={`status-dot status-dot--${connectionState}`}
            aria-hidden="true"
          />
          <span role="status">{stateCopy}</span>
        </div>
        <h1 id="page-title">Local development is ready.</h1>
        <p>
          This minimum workspace confirms that the React client can reach the
          FastAPI service.
        </p>
        <dl>
          <div>
            <dt>Health endpoint</dt>
            <dd>{API_BASE_URL}/api/health</dd>
          </div>
        </dl>
      </section>
    </main>
  )
}

export default App

