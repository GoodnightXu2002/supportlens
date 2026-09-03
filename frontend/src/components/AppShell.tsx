import { useEffect } from 'react'
import { MdAddCircleOutline, MdHistory, MdMenuBook } from 'react-icons/md'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
).replace(/\/$/, '')

const qualityReviewPaths = new Set([
  '/review',
  '/baseline',
  '/target-plan',
  '/validation',
])

const workflowNavigationItems = [
  { label: '基线分析', to: '/baseline' },
  { label: '目标与计划', to: '/target-plan' },
  { label: '候选版本验证', to: '/validation' },
]

function AppShell() {
  const location = useLocation()
  const isReviewRoute = location.pathname === '/review'
  const isQualityReviewRoute = qualityReviewPaths.has(location.pathname)
  const isDatasetRoute = location.pathname === '/dataset'

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
      <aside className="app-sidebar">
        <Link className="brand" to="/review" aria-label="SupportLens home">
          <span className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </span>
          <span className="brand-name">SupportLens</span>
        </Link>

        <nav className="sidebar-navigation" aria-label="Primary navigation">
          <Link
            aria-current={isQualityReviewRoute ? 'page' : undefined}
            className={
              isQualityReviewRoute
                ? 'sidebar-nav-link sidebar-nav-link--active'
                : 'sidebar-nav-link'
            }
            to="/review"
          >
            <svg
              className="sidebar-nav-icon"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path d="M5 4.5h14v15H5zM8 9h2m2 0h4M8 13l1.4 1.4L12 12m2 2h2" />
            </svg>
            <span>质量复盘</span>
          </Link>
          <Link
            aria-current={isDatasetRoute ? 'page' : undefined}
            className={
              isDatasetRoute
                ? 'sidebar-nav-link sidebar-nav-link--active'
                : 'sidebar-nav-link'
            }
            to="/dataset"
          >
            <svg
              className="sidebar-nav-icon"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <ellipse cx="12" cy="6" rx="7" ry="3" />
              <path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
            </svg>
            <span>数据集</span>
          </Link>
        </nav>
      </aside>

      <div className="app-frame">
        <header
          className={
            isReviewRoute ? 'app-header app-header--review' : 'app-header'
          }
        >
          {isReviewRoute ? (
            <div className="route-header route-header--review">
              <h1 className="route-header-title">开始质量复盘</h1>
              <span className="route-header-description">
                本轮要评什么 Dataset / Evaluation Set，以及哪个 Baseline？
              </span>
            </div>
          ) : isDatasetRoute ? (
            <div className="route-header route-header--dataset">
              <span className="route-header-title">数据集详情</span>
              <div className="dataset-header-actions">
                <button className="dataset-header-action dataset-header-action--plain" type="button">
                  <MdHistory aria-hidden="true" />查看历史不可变版本
                </button>
                <button className="dataset-header-action" type="button">
                  <MdAddCircleOutline aria-hidden="true" />新建/导入数据集
                </button>
                <button className="dataset-header-action" type="button">
                  <MdMenuBook aria-hidden="true" />查看参考依据
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="workspace-title">证据链工作区</div>
              <nav
                className="workflow-navigation"
                aria-label="Evidence workflow stages"
              >
                {workflowNavigationItems.map((item, index) => (
                  <div className="workflow-step" key={item.to}>
                    <NavLink
                      className={({ isActive }) =>
                        isActive
                          ? 'workflow-link workflow-link--active'
                          : 'workflow-link'
                      }
                      to={item.to}
                    >
                      {item.label}
                    </NavLink>
                    {index < workflowNavigationItems.length - 1 ? (
                      <span className="workflow-separator" aria-hidden="true">
                        ›
                      </span>
                    ) : null}
                  </div>
                ))}
              </nav>
            </>
          )}
        </header>

        <main className="page-content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export default AppShell
