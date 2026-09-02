import { useEffect } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
).replace(/\/$/, '')

const navigationItems = [
  { label: 'Start Quality Review', to: '/review' },
  { label: 'Dataset', to: '/dataset' },
  { label: 'Baseline Analysis', to: '/baseline' },
  { label: 'Target & Plan', to: '/target-plan' },
  { label: 'Candidate Validation', to: '/validation' },
]

function AppShell() {
  useEffect(() => {
    const controller = new AbortController()

    async function checkHealth() {
      const response = await fetch(`${API_BASE_URL}/api/health`, {
        signal: controller.signal,
      })

      if (!response.ok) {
        throw new Error(`Health check returned ${response.status}`)
      }

      await response.json()
    }

    void checkHealth().catch(() => undefined)
    return () => controller.abort()
  }, [])

  return (
    <div className="app-shell">
      <header className="app-header">
        <NavLink className="wordmark" to="/review">
          SupportLens
        </NavLink>
        <nav className="app-navigation" aria-label="Quality review pages">
          {navigationItems.map((item) => (
            <NavLink
              className={({ isActive }) =>
                isActive ? 'nav-link nav-link--active' : 'nav-link'
              }
              key={item.to}
              to={item.to}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="page-content">
        <Outlet />
      </main>
    </div>
  )
}

export default AppShell
