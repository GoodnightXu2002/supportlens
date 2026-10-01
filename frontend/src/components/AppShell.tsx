import { useEffect, useRef, useState } from 'react'
import { MdAddCircleOutline, MdHistory, MdMenuBook } from 'react-icons/md'
import { Link, Outlet, useLocation } from 'react-router-dom'

import { API_BASE_URL } from '../api'

const qualityReviewPaths = new Set([
  '/review',
  '/baseline',
  '/target-plan',
  '/validation',
])

const workflowNavigationItems = [
  { label: '基线分析', path: '/baseline' },
  { label: '目标与计划', path: '/target-plan' },
  { label: '候选版本验证', path: '/validation' },
]

function AppShell() {
  const location = useLocation()
  const isReviewRoute = location.pathname === '/review'
  const isQualityReviewRoute = qualityReviewPaths.has(location.pathname)
  const isDatasetRoute = location.pathname === '/dataset'
  const workflowStepIndex = workflowNavigationItems.findIndex((item) => item.path === location.pathname)
  const workflowParams = new URLSearchParams(location.search)
  const workflowRunId = workflowParams.get('run_id')?.trim() ?? ''
  const workflowProblemId = workflowParams.get('problem_id')?.trim() ?? ''
  const workflowProblemIds = workflowParams.get('problem_ids')?.trim() ?? ''
  const workflowTargetId = workflowParams.get('target_id')?.trim() ?? ''
  const workflowCandidateRunId = workflowParams.get('candidate_run_id')?.trim() ?? ''
  const workflowValidationTaskId = workflowParams.get('validation_task_id')?.trim() ?? ''
  const workflowContext = new URLSearchParams({ run_id: workflowRunId })
  if (workflowProblemId) workflowContext.set('problem_id', workflowProblemId)
  if (workflowProblemIds) workflowContext.set('problem_ids', workflowProblemIds)
  if (workflowTargetId) workflowContext.set('target_id', workflowTargetId)
  if (workflowCandidateRunId) workflowContext.set('candidate_run_id', workflowCandidateRunId)
  if (workflowValidationTaskId) workflowContext.set('validation_task_id', workflowValidationTaskId)
  const workflowContextQuery = workflowContext.toString()
  const workflowRoutes = [
    workflowRunId ? `/baseline?${workflowContextQuery}` : null,
    workflowRunId && workflowProblemId && workflowTargetId
      ? `/target-plan?${workflowContextQuery}`
      : null,
    workflowRunId && workflowProblemId && workflowTargetId
      ? `/validation?${workflowContextQuery}`
      : null,
  ]
  const [datasetImportOpen, setDatasetImportOpen] = useState(false)
  const datasetImportButtonRef = useRef<HTMLButtonElement>(null)

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

  function closeDatasetImport() {
    setDatasetImportOpen(false)
    window.requestAnimationFrame(() => datasetImportButtonRef.current?.focus())
  }

  function openDatasetImport() {
    setDatasetImportOpen(true)
  }

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <Link
          className="brand"
          to="/"
          aria-label="SupportLens 首页"
          onClick={() => setDatasetImportOpen(false)}
        >
          <svg
            className="brand-mark"
            viewBox="0 0 32 32"
            aria-hidden="true"
          >
            <path d="M18 3H8a2 2 0 0 0-2 2v22a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9l-6-6Z" />
            <path d="M18 3v6h6M11 13h7M11 17h6M11 21h4" />
            <circle cx="21" cy="22" r="5" />
            <path d="m24.75 25.75 4.25 4.25" />
          </svg>
          <span className="brand-name">SupportLens</span>
        </Link>

        <nav className="sidebar-navigation" aria-label="主导航">
          <Link
            aria-current={isQualityReviewRoute ? 'page' : undefined}
            className={
              isQualityReviewRoute
                ? 'sidebar-nav-link sidebar-nav-link--active'
                : 'sidebar-nav-link'
            }
            to="/review"
            onClick={() => setDatasetImportOpen(false)}
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
                本轮要评测哪个数据集 / 评测集，以及使用哪条基线？
              </span>
            </div>
          ) : isDatasetRoute ? (
            <div className="route-header route-header--dataset">
              <span className="route-header-title">数据集详情</span>
              <div className="dataset-header-actions">
                <button className="dataset-header-action dataset-header-action--plain" type="button">
                  <MdHistory aria-hidden="true" />查看历史不可变版本
                </button>
                <button
                  ref={datasetImportButtonRef}
                  className="dataset-header-action"
                  type="button"
                  aria-haspopup="dialog"
                  aria-expanded={datasetImportOpen}
                  onClick={openDatasetImport}
                >
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
                aria-label="评测工作流阶段"
              >
                {workflowNavigationItems.map((item, index) => {
                  const current = index === workflowStepIndex
                  const destination = current ? null : workflowRoutes[index]
                  return (
                    <div className="workflow-step" key={item.path}>
                      {destination ? (
                        <Link className="workflow-link" to={destination}>{item.label}</Link>
                      ) : (
                        <span
                          aria-current={current ? 'step' : undefined}
                          aria-disabled={current ? undefined : true}
                          className={current ? 'workflow-link workflow-link--active' : 'workflow-link workflow-link--locked'}
                        >
                          {item.label}
                        </span>
                      )}
                      {index < workflowNavigationItems.length - 1 ? (
                        <span className="workflow-separator" aria-hidden="true">›</span>
                      ) : null}
                    </div>
                  )
                })}
              </nav>
            </>
          )}
        </header>

        <main className="page-content">
          <Outlet
            context={{
              datasetImportOpen,
              openDatasetImport,
              closeDatasetImport,
            }}
          />
        </main>
      </div>
    </div>
  )
}

export default AppShell
