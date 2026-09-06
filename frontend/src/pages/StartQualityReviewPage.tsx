import { useEffect, useState } from 'react'
import {
  MdCheckCircleOutline,
  MdOpenInNew,
  MdPlayArrow,
  MdSmartToy,
  MdTune,
} from 'react-icons/md'
import { PiDatabase } from 'react-icons/pi'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import {
  ApiRequestError,
  createBaselineRun,
  executeBaselineRun,
  getDatasetDetail,
  getDatasets,
  getEvaluationRun,
  type DatasetDetail,
  type DatasetListItem,
  type EvaluationRun,
} from '../api'
import './StartQualityReviewPage.css'

type PageStatus =
  | 'loading'
  | 'ready'
  | 'running'
  | 'completed'
  | 'partial_failure'
  | 'failed'
  | 'invalid'
  | 'error'

const statusCopy: Record<PageStatus, { label: string; detail: string }> = {
  loading: { label: '正在读取', detail: '正在从 Backend 读取真实 Dataset 与 Run。' },
  ready: { label: '已就绪 READY', detail: '可以创建并启动真实 Baseline EvaluationRun。' },
  running: { label: '运行中 RUNNING', detail: 'Backend 正在执行 Baseline EvaluationRun。' },
  completed: { label: '已完成 COMPLETED', detail: '正在进入基线分析。' },
  partial_failure: { label: '部分失败 PARTIAL_FAILURE', detail: '部分案例执行失败，已保留成功结果。' },
  failed: { label: '失败 FAILED', detail: '本次运行没有生成可用结果。' },
  invalid: { label: '无效 INVALID', detail: '本次运行的输入或快照无效。' },
  error: { label: '读取失败', detail: '无法读取真实 Dataset 或 EvaluationRun。' },
}

function errorMessage(error: unknown) {
  return error instanceof ApiRequestError
    ? error.message
    : '无法连接 Backend，请确认服务正在运行后重试。'
}

function formatScenarioDistribution(distribution: Record<string, number>) {
  const entries = Object.entries(distribution)
  return entries.length
    ? entries.map(([scenario, count]) => `${scenario} ${count}`).join(' / ')
    : '未提供场景分类'
}

function StartQualityReviewPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedDatasetId = searchParams.get('dataset_id')
  const runId = searchParams.get('run_id')?.trim() ?? ''
  const [datasets, setDatasets] = useState<DatasetListItem[]>([])
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(
    requestedDatasetId,
  )
  const [dataset, setDataset] = useState<DatasetDetail | null>(null)
  const [run, setRun] = useState<EvaluationRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void getDatasets(controller.signal)
      .then((items) => {
        if (controller.signal.aborted) return
        setDatasets(items)
        setSelectedDatasetId((current) =>
          current && items.some((item) => item.dataset_id === current)
            ? current
            : (items[0]?.dataset_id ?? null),
        )
        setMessage(null)
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setMessage(errorMessage(error))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!selectedDatasetId) return
    const controller = new AbortController()
    void getDatasetDetail(selectedDatasetId, controller.signal)
      .then((detail) => {
        if (!controller.signal.aborted) setDataset(detail)
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setMessage(errorMessage(error))
      })
    return () => controller.abort()
  }, [selectedDatasetId])

  useEffect(() => {
    if (!runId) return
    const controller = new AbortController()
    void getEvaluationRun(runId, controller.signal)
      .then((storedRun) => {
        if (controller.signal.aborted) return
        setRun(storedRun)
        setSelectedDatasetId(storedRun.dataset_id)
        setMessage(null)
        if (storedRun.status === 'completed') {
          navigate(`/baseline?run_id=${encodeURIComponent(storedRun.id)}`, {
            replace: true,
          })
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setMessage(errorMessage(error))
      })
    return () => controller.abort()
  }, [navigate, runId])

  useEffect(() => {
    if (!runId || run?.id !== runId || run.status !== 'running') return
    const controller = new AbortController()
    const timer = window.setInterval(() => {
      void getEvaluationRun(runId, controller.signal)
        .then((storedRun) => {
          setRun(storedRun)
          if (storedRun.status === 'completed') {
            navigate(`/baseline?run_id=${encodeURIComponent(storedRun.id)}`, {
              replace: true,
            })
          }
        })
        .catch((error: unknown) => {
          if (!controller.signal.aborted) setMessage(errorMessage(error))
        })
    }, 1500)
    return () => {
      controller.abort()
      window.clearInterval(timer)
    }
  }, [navigate, run?.id, run?.status, runId])

  const pageStatus: PageStatus = (
    loading
    || (selectedDatasetId && dataset?.dataset_id !== selectedDatasetId)
    || (runId && run?.id !== runId)
  )
    ? 'loading'
    : message && !run
      ? 'error'
      : run?.status === 'pending'
        ? 'ready'
        : (run?.status ?? (dataset?.conversation_count ? 'ready' : 'error'))
  const currentStatus = statusCopy[pageStatus]
  const runError = run?.error_message ?? message
  const readinessGates = [
    { label: '数据集', status: dataset ? 'VALID' : 'UNAVAILABLE' },
    { label: '案例', status: `${dataset?.conversation_count ?? 0} CASES` },
    { label: '来源', status: dataset?.source ?? '—' },
    { label: '隐私', status: dataset?.privacy_status ?? '—' },
    { label: '版本', status: dataset?.version ?? '—' },
  ]

  function selectDataset(datasetId: string) {
    setSelectedDatasetId(datasetId)
    setDataset(null)
    setRun(null)
    setMessage(null)
    setSearchParams({ dataset_id: datasetId })
  }

  async function startBaseline() {
    if (!dataset || working || pageStatus === 'running') return
    setWorking(true)
    setMessage(null)
    let startableRun: EvaluationRun | null = null
    try {
      startableRun =
        run?.status === 'pending' && run.dataset_id === dataset.dataset_id
          ? run
          : await createBaselineRun(dataset.dataset_id)
      setRun(startableRun)
      setSearchParams({
        dataset_id: dataset.dataset_id,
        run_id: startableRun.id,
      }, { replace: true })
      setRun({ ...startableRun, status: 'running' })
      const completedRun = await executeBaselineRun(startableRun.id)
      setRun(completedRun)
      if (completedRun.status === 'completed') {
        navigate(`/baseline?run_id=${encodeURIComponent(completedRun.id)}`)
      }
    } catch (error) {
      setMessage(errorMessage(error))
      if (startableRun) {
        try {
          const storedRun = await getEvaluationRun(startableRun.id)
          setRun(storedRun)
          if (storedRun.status === 'completed') {
            navigate(`/baseline?run_id=${encodeURIComponent(storedRun.id)}`)
          }
        } catch {
          // Keep the actionable request error when the authoritative read also fails.
        }
      }
    } finally {
      setWorking(false)
    }
  }

  const canStart = Boolean(dataset?.conversation_count) && !working && pageStatus !== 'running'
  const actionLabel = run && ['partial_failure', 'failed', 'invalid'].includes(run.status)
    ? '重新开始质量复盘'
    : '开始质量复盘'

  return (
    <section className="s01-page" aria-label="开始质量复盘">
      <div className="s01-workspace">
        <div className="s01-workspace-content">
          <div className={`s01-ready-banner s01-ready-banner--${pageStatus}`} role="status">
            <MdCheckCircleOutline aria-hidden="true" />
            <div className="s01-ready-copy">
              <strong>{currentStatus.label}</strong>
              <span>{runError ?? currentStatus.detail}</span>
            </div>
          </div>

          <section className="s01-context" aria-labelledby="s01-context-title">
            <div className="s01-section-heading"><h2 id="s01-context-title">评测上下文</h2></div>

            <article className="s01-context-row">
              <div className="s01-context-icon" aria-hidden="true"><PiDatabase /></div>
              <div className="s01-context-content">
                <div className="s01-context-topline">
                  <div>
                    <h3>数据集</h3>
                    <code className="s01-code-chip">
                      {dataset ? `${dataset.name} ${dataset.version}` : '未选择 Dataset'}
                    </code>
                  </div>
                  <div className="s01-context-actions">
                    <Link
                      className="s01-text-action s01-text-action--info"
                      to={dataset ? `/dataset?dataset_id=${encodeURIComponent(dataset.dataset_id)}` : '/dataset'}
                    >
                      查看数据集详情<MdOpenInNew aria-hidden="true" />
                    </Link>
                    <label className="s01-dataset-switcher">
                      <span>更换数据集</span>
                      <select
                        aria-label="更换数据集"
                        value={selectedDatasetId ?? ''}
                        disabled={working || pageStatus === 'running' || datasets.length === 0}
                        onChange={(event) => selectDataset(event.target.value)}
                      >
                        {datasets.length === 0 ? <option value="">无可用 Dataset</option> : null}
                        {datasets.map((item) => (
                          <option key={item.dataset_id} value={item.dataset_id}>
                            {item.name} · {item.version}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                </div>
                <div className="s01-details-grid s01-details-grid--dataset">
                  <p><strong>详情:</strong> {dataset ? `${dataset.conversation_count} 个案例` : '—'}</p>
                  <p><strong>场景分布:</strong> {dataset ? formatScenarioDistribution(dataset.scenario_distribution) : '—'}</p>
                  <p className="s01-details-wide"><strong>结论边界:</strong> {dataset?.representativeness_statement ?? '未提供'}</p>
                  <p><strong>数据集快照:</strong> <code className="s01-inline-code">{dataset?.dataset_id ?? '—'}</code></p>
                </div>
              </div>
            </article>

            <article className="s01-context-row">
              <div className="s01-context-icon" aria-hidden="true"><MdSmartToy /></div>
              <div className="s01-context-content">
                <div className="s01-context-topline">
                  <div>
                    <h3>基线运行</h3>
                    <code className="s01-code-chip">{run?.id ?? '启动时创建真实 EvaluationRun'}</code>
                  </div>
                </div>
                <div className="s01-details-grid">
                  <p><strong>回答集:</strong> <code className="s01-inline-code">{run?.response_set_key ?? '所选 Dataset Conversations'}</code></p>
                  <p className="s01-status-line"><strong>状态:</strong><code className={`s01-status-chip s01-status-chip--${pageStatus}`}>{pageStatus.toUpperCase()}</code></p>
                </div>
              </div>
            </article>

            <article className="s01-context-row">
              <div className="s01-context-icon" aria-hidden="true"><MdTune /></div>
              <div className="s01-context-content">
                <div className="s01-context-topline">
                  <div>
                    <h3>评测配置</h3>
                    <code className="s01-code-chip">{run?.judge_contract_version ?? '启动时由 Backend 固化'}</code>
                  </div>
                </div>
                <div className="s01-details-grid s01-details-grid--config">
                  <p><strong>Judge Model:</strong> <code className="s01-inline-code">{run?.judge_model ?? '—'}</code></p>
                  <p><strong>Run Source:</strong> <code className="s01-inline-code">{run?.run_source ?? '—'}</code></p>
                </div>
              </div>
            </article>
          </section>

          <section className="s01-gates" aria-labelledby="s01-gates-title">
            <div className="s01-gates-heading">
              <h2 id="s01-gates-title">就绪门槛</h2>
              <code>{dataset && dataset.conversation_count > 0 ? '2 / 2 PASSED' : 'NOT READY'}</code>
            </div>
            <div className="s01-gates-grid">
              {readinessGates.map((gate) => (
                <div className="s01-gate" key={gate.label}><span>{gate.label}</span><code>{gate.status}</code></div>
              ))}
            </div>
          </section>
        </div>
      </div>

      <footer className="s01-action-rail">
        <div className="s01-action-copy">
          <span>状态: {currentStatus.label}</span>
          <span>{run ? `Run ID: ${run.id}` : '启动后生成真实 Run ID；完成后进入 S03 基线分析。'}</span>
        </div>
        <button className="s01-primary-action" type="button" disabled={!canStart} onClick={() => void startBaseline()}>
          {working || pageStatus === 'running' ? '评测运行中' : actionLabel}<MdPlayArrow aria-hidden="true" />
        </button>
      </footer>
    </section>
  )
}

export default StartQualityReviewPage
