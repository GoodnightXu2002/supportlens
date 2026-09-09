import { useCallback, useEffect, useState } from 'react'
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
  generateProblems,
  getDatasetConversations,
  getDatasetDetail,
  getDatasetEvaluationRuns,
  getDatasets,
  getEvaluationRun,
  getFinalEffectiveResults,
  submitHumanReview,
  type DatasetConversation,
  type DatasetDetail,
  type DatasetListItem,
  type EvaluationRun,
  type FinalEffectiveResult,
  type JudgeOutput,
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

type ReviewData = {
  runId: string
  results: FinalEffectiveResult[]
  conversations: DatasetConversation[]
}

type CorrectionDraft = {
  resultId: string
  judgment: JudgeOutput['judgment']
  primaryFailureMode: JudgeOutput['primary_failure_mode']
  problem: string
  severity: JudgeOutput['severity']
  reviewRequired: JudgeOutput['review_required']
  changeReason: string
}

const failureModes = [
  'incorrect_information',
  'incomplete_unresolved',
  'intent_relevance_failure',
  'improper_refusal',
  'policy_procedure_violation',
  'other',
] as const

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

function formatRunDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

async function prepareBaselineAnalysis(run: EvaluationRun) {
  if (!run.problem_aggregation_completed_at) await generateProblems(run.id)
  return `/baseline?run_id=${encodeURIComponent(run.id)}`
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
  const [reviewData, setReviewData] = useState<ReviewData | null>(null)
  const [reviewLoading, setReviewLoading] = useState(false)
  const [reviewer, setReviewer] = useState('')
  const [reviewBusyId, setReviewBusyId] = useState<string | null>(null)
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [correctionDraft, setCorrectionDraft] = useState<CorrectionDraft | null>(null)
  const [historyResult, setHistoryResult] = useState<{
    datasetId: string
    runs: EvaluationRun[]
    error: string | null
  } | null>(null)

  const resumeCompletedRun = useCallback(async (
    completedRun: EvaluationRun,
    signal?: AbortSignal,
  ) => {
    setReviewLoading(true)
    setMessage(null)
    try {
      const [results, conversations] = await Promise.all([
        getFinalEffectiveResults(completedRun.id, signal),
        getDatasetConversations(completedRun.dataset_id, signal),
      ])
      if (signal?.aborted) return
      setReviewData({ runId: completedRun.id, results, conversations })
      if (results.some((result) => result.status === 'pending_review')) return
      const path = await prepareBaselineAnalysis(completedRun)
      if (!signal?.aborted) navigate(path, { replace: true })
    } catch (error) {
      if (!signal?.aborted) setMessage(errorMessage(error))
    } finally {
      if (!signal?.aborted) setReviewLoading(false)
    }
  }, [navigate])

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
    if (!selectedDatasetId) return
    const controller = new AbortController()
    void getDatasetEvaluationRuns(selectedDatasetId, controller.signal)
      .then((items) => {
        if (controller.signal.aborted) return
        setHistoryResult({
          datasetId: selectedDatasetId,
          runs: items.filter((item) => (
            item.dataset_id === selectedDatasetId
            && item.run_type === 'baseline'
            && item.status === 'completed'
          )),
          error: null,
        })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setHistoryResult({
            datasetId: selectedDatasetId,
            runs: [],
            error: errorMessage(error),
          })
        }
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
          void resumeCompletedRun(storedRun, controller.signal)
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setMessage(errorMessage(error))
      })
    return () => controller.abort()
  }, [resumeCompletedRun, runId])

  useEffect(() => {
    if (!runId || run?.id !== runId || run.status !== 'running' || working) return
    const controller = new AbortController()
    const timer = window.setInterval(() => {
      void getEvaluationRun(runId, controller.signal)
        .then((storedRun) => {
          setRun(storedRun)
          if (storedRun.status === 'completed') {
            window.clearInterval(timer)
            void resumeCompletedRun(storedRun)
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
  }, [resumeCompletedRun, run?.id, run?.status, runId, working])

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
  const currentReviewData = reviewData?.runId === run?.id ? reviewData : null
  const pendingReviewResults = currentReviewData?.results.filter(
    (result) => result.status === 'pending_review',
  ) ?? []
  let currentStatus = statusCopy[pageStatus]
  if (run?.status === 'completed' && reviewLoading && !currentReviewData) {
    currentStatus = {
      label: '正在检查人工复核',
      detail: '正在读取真实 Final Effective Results。',
    }
  } else if (run?.status === 'completed' && currentReviewData) {
    currentStatus = pendingReviewResults.length > 0
      ? {
          label: `待人工复核 ${pendingReviewResults.length} 条`,
          detail: '完成全部真实 Human Review 后才会生成 Problem 并进入 S03。',
        }
      : {
          label: '人工复核完成 · 待复核 0',
          detail: '正在继续 Problem Aggregation 并进入 S03。',
        }
  }
  const runError = run?.error_message ?? message
  const readinessGates = [
    { label: '数据集', status: dataset ? 'VALID' : 'UNAVAILABLE', pass: Boolean(dataset) },
    { label: '案例', status: `${dataset?.conversation_count ?? 0} CASES`, pass: false },
    { label: '来源', status: dataset?.source ?? '—', pass: false },
    { label: '隐私', status: dataset?.privacy_status ?? '—', pass: false },
    { label: '版本', status: dataset?.version ?? '—', pass: false },
  ]

  function selectDataset(datasetId: string) {
    setSelectedDatasetId(datasetId)
    setDataset(null)
    setRun(null)
    setReviewData(null)
    setReviewError(null)
    setCorrectionDraft(null)
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
        await resumeCompletedRun(completedRun)
      }
    } catch (error) {
      setMessage(errorMessage(error))
      if (startableRun) {
        try {
          const storedRun = await getEvaluationRun(startableRun.id)
          setRun(storedRun)
          if (storedRun.status === 'completed') {
            await resumeCompletedRun(storedRun)
          }
        } catch {
          // Keep the actionable request error when the authoritative read also fails.
        }
      }
    } finally {
      setWorking(false)
    }
  }

  async function refreshAfterReview() {
    if (run?.status === 'completed') await resumeCompletedRun(run)
  }

  async function confirmMachineResult(result: FinalEffectiveResult) {
    if (!reviewer.trim() || reviewBusyId) return
    setReviewBusyId(result.evaluation_result_id)
    setReviewError(null)
    try {
      await submitHumanReview(result.evaluation_result_id, {
        reviewer: reviewer.trim(),
        action: 'confirm',
      })
      await refreshAfterReview()
    } catch (error) {
      setReviewError(errorMessage(error))
    } finally {
      setReviewBusyId(null)
    }
  }

  async function correctMachineResult(result: FinalEffectiveResult) {
    if (
      !reviewer.trim()
      || !correctionDraft?.changeReason.trim()
      || correctionDraft.resultId !== result.evaluation_result_id
      || reviewBusyId
    ) return
    setReviewBusyId(result.evaluation_result_id)
    setReviewError(null)
    try {
      const finalResult: JudgeOutput = {
        ...result.machine_result,
        judgment: correctionDraft.judgment,
        primary_failure_mode: correctionDraft.primaryFailureMode,
        problem: correctionDraft.problem.trim() || null,
        severity: correctionDraft.severity,
        review_required: correctionDraft.reviewRequired,
      }
      await submitHumanReview(result.evaluation_result_id, {
        reviewer: reviewer.trim(),
        action: 'correct',
        final_result: finalResult,
        change_reason: correctionDraft.changeReason.trim(),
      })
      setCorrectionDraft(null)
      await refreshAfterReview()
    } catch (error) {
      setReviewError(errorMessage(error))
    } finally {
      setReviewBusyId(null)
    }
  }

  const canStart = Boolean(dataset?.conversation_count)
    && !working
    && !reviewLoading
    && pageStatus !== 'running'
    && run?.status !== 'completed'
  const actionLabel = run && ['partial_failure', 'failed', 'invalid'].includes(run.status)
    ? '重新开始质量复盘'
    : '开始质量复盘'
  const historyLoading = Boolean(selectedDatasetId && historyResult?.datasetId !== selectedDatasetId)
  const historyRuns = historyResult?.datasetId === selectedDatasetId ? historyResult.runs : []
  const historyError = historyResult?.datasetId === selectedDatasetId ? historyResult.error : null

  return (
    <section className="s01-page" aria-label="开始质量复盘">
      <div className="s01-workspace">
        <div className="s01-workspace-content">
          <div className={`s01-ready-banner s01-ready-banner--${pendingReviewResults.length ? 'review' : reviewLoading && run?.status === 'completed' ? 'loading' : pageStatus}`} role="status">
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
                <div className="s01-gate" key={gate.label}>
                  <span>{gate.label}</span>
                  <code className={gate.pass ? 's01-gate-chip s01-gate-chip--pass' : 's01-gate-chip'}>{gate.status}</code>
                </div>
              ))}
            </div>
          </section>

          {run?.status === 'completed' && (reviewLoading || currentReviewData) ? (
            <section className="s01-gates s01-review" aria-labelledby="s01-review-title">
              <div className="s01-gates-heading">
                <h2 id="s01-review-title">Human Review</h2>
                <code>{reviewLoading && !currentReviewData ? 'LOADING' : `待人工复核 ${pendingReviewResults.length} 条`}</code>
              </div>
              {reviewLoading && !currentReviewData ? <p className="s01-review-state" role="status">正在读取真实 Final Effective Results…</p> : null}
              {currentReviewData ? (
                <>
                  <label className="s01-reviewer-field">
                    <span>复核人</span>
                    <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} disabled={Boolean(reviewBusyId)} placeholder="输入复核人" />
                  </label>
                  {reviewError ? <p className="s01-review-error" role="alert">{reviewError}</p> : null}
                  {pendingReviewResults.length === 0 ? <p className="s01-review-complete">人工复核完成 · 待复核 0</p> : null}
                  <div className="s01-review-list">
                    {pendingReviewResults.map((result) => {
                      const conversation = currentReviewData.conversations.find((item) => item.id === result.conversation_id)
                      const userMessage = conversation?.messages.filter((item) => item.role === 'user').map((item) => item.content).join('\n') ?? '—'
                      const assistantAnswer = conversation?.messages.filter((item) => item.role === 'assistant').map((item) => item.content).join('\n') ?? '—'
                      const correcting = correctionDraft?.resultId === result.evaluation_result_id
                      return (
                        <article className="s01-review-card" key={result.evaluation_result_id}>
                          <header><strong>{result.case_id}</strong><code>{result.evaluation_result_id}</code></header>
                          <dl className="s01-review-copy"><div><dt>用户消息</dt><dd>{userMessage}</dd></div><div><dt>AI 回答</dt><dd>{assistantAnswer}</dd></div></dl>
                          <dl className="s01-review-machine">
                            <div><dt>机器判定</dt><dd>{result.machine_result.judgment}</dd></div>
                            <div><dt>失败模式</dt><dd>{result.machine_result.primary_failure_mode ?? '—'}</dd></div>
                            <div><dt>问题</dt><dd>{result.machine_result.problem ?? '—'}</dd></div>
                            <div><dt>严重程度</dt><dd>{result.machine_result.severity ?? '—'}</dd></div>
                          </dl>
                          <div className="s01-review-evidence"><strong>证据 / 判定理由</strong>{result.machine_result.evidence.length ? <ul>{result.machine_result.evidence.map((item, index) => <li key={`${result.evaluation_result_id}-${index}`}>{item.evidence_type}: {item.content}{item.source_ref ? ` (${item.source_ref})` : ''}</li>)}</ul> : <p>无结构化 evidence。</p>}<p>{result.machine_result.rationale}</p></div>
                          {correcting && correctionDraft ? (
                            <div className="s01-correction-form">
                              <div className="s01-correction-fields">
                                <label><span>判定</span><select value={correctionDraft.judgment} onChange={(event) => { const judgment = event.target.value as JudgeOutput['judgment']; setCorrectionDraft((current) => current ? { ...current, judgment, severity: judgment === 'failure' ? (current.severity ?? result.machine_result.severity ?? 'low') : null } : current) }}><option value="success">success</option><option value="warning">warning</option><option value="failure">failure</option><option value="uncertain">uncertain</option></select></label>
                                <label><span>主要失败模式</span><select value={correctionDraft.primaryFailureMode ?? ''} onChange={(event) => setCorrectionDraft((current) => current ? { ...current, primaryFailureMode: (event.target.value || null) as JudgeOutput['primary_failure_mode'] } : current)}><option value="">null</option>{failureModes.map((mode) => <option key={mode} value={mode}>{mode}</option>)}</select></label>
                                <label className="s01-correction-wide"><span>问题</span><textarea value={correctionDraft.problem} onChange={(event) => setCorrectionDraft((current) => current ? { ...current, problem: event.target.value } : current)} rows={3} /></label>
                                <label><span>严重程度</span><select value={correctionDraft.severity ?? ''} disabled={correctionDraft.judgment !== 'failure'} onChange={(event) => setCorrectionDraft((current) => current ? { ...current, severity: (event.target.value || null) as JudgeOutput['severity'] } : current)}><option value="">null</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option></select></label>
                                <label><span>需人工复核</span><select value={correctionDraft.reviewRequired === null ? 'null' : String(correctionDraft.reviewRequired)} onChange={(event) => setCorrectionDraft((current) => current ? { ...current, reviewRequired: event.target.value === 'null' ? null : event.target.value === 'true' } : current)}><option value="true">true</option><option value="false">false</option><option value="null">null</option></select></label>
                                <label className="s01-correction-wide"><span>修正理由</span><textarea value={correctionDraft.changeReason} onChange={(event) => setCorrectionDraft((current) => current ? { ...current, changeReason: event.target.value } : current)} rows={3} /></label>
                              </div>
                              <div><button type="button" onClick={() => { setCorrectionDraft(null); setReviewError(null) }} disabled={Boolean(reviewBusyId)}>取消</button><button type="button" onClick={() => void correctMachineResult(result)} disabled={!reviewer.trim() || !correctionDraft.changeReason.trim() || (correctionDraft.judgment === 'failure' && !correctionDraft.severity) || Boolean(reviewBusyId)}>提交人工修正</button></div>
                            </div>
                          ) : (
                            <div className="s01-review-actions"><button type="button" onClick={() => void confirmMachineResult(result)} disabled={!reviewer.trim() || Boolean(reviewBusyId)}>确认机器结论</button><button type="button" onClick={() => { setCorrectionDraft({ resultId: result.evaluation_result_id, judgment: result.machine_result.judgment, primaryFailureMode: result.machine_result.primary_failure_mode, problem: result.machine_result.problem ?? '', severity: result.machine_result.severity, reviewRequired: result.machine_result.review_required, changeReason: '' }); setReviewError(null) }} disabled={Boolean(reviewBusyId)}>修正结论</button></div>
                          )}
                        </article>
                      )
                    })}
                  </div>
                </>
              ) : null}
            </section>
          ) : null}

          <section className="s01-gates s01-history" aria-labelledby="s01-history-title">
            <div className="s01-gates-heading">
              <h2 id="s01-history-title">已完成复盘</h2>
              <code>{historyLoading ? 'LOADING' : `${historyRuns.length} RUNS`}</code>
            </div>
            {historyLoading ? <p className="s01-history-state" role="status">正在读取历史 Baseline Runs…</p> : null}
            {!historyLoading && historyError ? <p className="s01-history-state s01-history-state--error" role="alert">{historyError}</p> : null}
            {!historyLoading && !historyError && historyRuns.length === 0 ? <p className="s01-history-state">当前 Dataset 暂无已完成复盘。</p> : null}
            {!historyLoading && !historyError && historyRuns.length > 0 ? (
              <div className="s01-history-list">
                {historyRuns.map((historyRun) => (
                  <article className="s01-history-run" key={historyRun.id}>
                    <div><span>Run ID</span><code>{historyRun.id}</code></div>
                    <div><span>状态</span><strong>completed</strong></div>
                    <div><span>创建时间</span><time dateTime={historyRun.created_at}>{formatRunDate(historyRun.created_at)}</time></div>
                    <div><span>Judge model</span><code>{historyRun.judge_model || '—'}</code></div>
                    <Link className="s01-text-action s01-text-action--info" to={`/baseline?run_id=${encodeURIComponent(historyRun.id)}`}>
                      查看结果<MdOpenInNew aria-hidden="true" />
                    </Link>
                  </article>
                ))}
              </div>
            ) : null}
          </section>
        </div>
      </div>

      <footer className="s01-action-rail">
        <div className="s01-action-copy">
          <span>状态: {currentStatus.label}</span>
          <span>{run ? `Run ID: ${run.id}` : '启动后生成真实 Run ID；完成后进入 S03 基线分析。'}</span>
        </div>
        <button className="s01-primary-action" type="button" disabled={!canStart} onClick={() => void startBaseline()}>
          {pendingReviewResults.length > 0
            ? '完成待处理复核后继续'
            : working || pageStatus === 'running'
              ? '评测运行中'
              : actionLabel}<MdPlayArrow aria-hidden="true" />
        </button>
      </footer>
    </section>
  )
}

export default StartQualityReviewPage
