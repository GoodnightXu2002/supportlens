import { useCallback, useEffect, useState } from 'react'
import {
  MdOpenInNew,
  MdPlayArrow,
} from 'react-icons/md'
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
import {
  datasetSourceLabel,
  evidenceTypeLabel,
  failureModeLabel,
  privacyStatusLabel,
  runStatusLabel,
  scenarioLabel,
} from '../displayLabels'
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

const judgmentLabels: Record<JudgeOutput['judgment'], string> = {
  success: '成功',
  warning: '警告',
  failure: '失败',
  uncertain: '不确定',
}

const severityLabels: Record<NonNullable<JudgeOutput['severity']>, string> = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '严重',
}

const statusCopy: Record<PageStatus, { label: string; detail: string }> = {
  loading: { label: '正在读取', detail: '正在读取真实数据集与评测运行。' },
  ready: { label: '已就绪', detail: '一切就绪，随时可以开始。' },
  running: { label: '运行中', detail: '后端正在执行基线评测运行。' },
  completed: { label: '已完成', detail: '正在进入基线分析。' },
  partial_failure: { label: '部分失败', detail: '部分案例执行失败，已保留成功结果。' },
  failed: { label: '失败', detail: '本次运行没有生成可用结果。' },
  invalid: { label: '无效', detail: '本次运行的输入或快照无效。' },
  error: { label: '读取失败', detail: '无法读取真实数据集或评测运行。' },
}

function errorMessage(error: unknown) {
  return error instanceof ApiRequestError
    ? error.message
    : '无法连接后端，请确认服务正在运行后重试。'
}

function formatScenarioDistribution(distribution: Record<string, number>) {
  const entries = Object.entries(distribution)
  return entries.length
    ? entries.map(([scenario, count]) => `${scenarioLabel(scenario)} ${count}`).join(' / ')
    : '未提供场景分类'
}

function formatRunTimestamp(value: string) {
  const date = new Date(value)
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
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
      detail: '正在读取真实最终生效结果。',
    }
  } else if (run?.status === 'completed' && currentReviewData) {
    currentStatus = pendingReviewResults.length > 0
      ? {
          label: `待人工复核 ${pendingReviewResults.length} 条`,
          detail: '完成全部真实人工复核后才会生成问题并进入 S03。',
        }
      : {
          label: '人工复核完成 · 待复核 0',
          detail: '正在继续问题聚合并进入 S03。',
        }
  }
  const runError = run?.error_message ?? message

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
      <div className="s01-layout">
        <div className="s01-main">
          <div className={`s01-ready-banner s01-ready-banner--${pendingReviewResults.length ? 'review' : reviewLoading && run?.status === 'completed' ? 'loading' : pageStatus}`} role="status">
            <span className="s01-status-dot" aria-hidden="true" />
            <div className="s01-ready-copy">
              <strong>{currentStatus.label}</strong>
              <span>{runError ?? currentStatus.detail}</span>
            </div>
          </div>

          <section className="s01-history" aria-labelledby="s01-history-title">
            <div className="s01-history-heading">
              <h2 id="s01-history-title">已完成复盘</h2>
              <code>{historyLoading ? '读取中' : `${historyRuns.length} 条运行`}</code>
            </div>
            {historyLoading ? <p className="s01-history-state" role="status">正在读取历史基线运行…</p> : null}
            {!historyLoading && historyError ? <p className="s01-history-state s01-history-state--error" role="alert">{historyError}</p> : null}
            {!historyLoading && !historyError && historyRuns.length === 0 ? <p className="s01-history-state">当前数据集暂无已完成复盘，可在右侧启动第一次评测。</p> : null}
            {!historyLoading && !historyError && historyRuns.length > 0 ? (
              <div className="s01-history-list">
                {historyRuns.map((historyRun) => (
                  <article className="s01-history-run" key={historyRun.id}>
                    <code className="s01-history-run__id" title={historyRun.id}>{historyRun.id.slice(0, 8).toUpperCase()}</code>
                    <span className="s01-history-run__status">
                      <span className="s01-status-dot" aria-hidden="true" />
                      {runStatusLabel(historyRun.status)}
                    </span>
                    <time dateTime={historyRun.created_at}>{formatRunTimestamp(historyRun.created_at)}</time>
                    <code className="s01-history-run__model" title={historyRun.judge_model ?? undefined}>{historyRun.judge_model || '判定模型 —'}</code>
                    <Link className="s01-text-action s01-text-action--info" to={`/baseline?run_id=${encodeURIComponent(historyRun.id)}`}>
                      查看结果<MdOpenInNew aria-hidden="true" />
                    </Link>
                  </article>
                ))}
              </div>
            ) : null}
          </section>

          <section className="s01-context" aria-label="评测数据集">
            <article className="s01-context-row">
              <div className="s01-context-content">
                <div className="s01-context-topline">
                  <div>
                    <h3>数据集</h3>
                    <code className="s01-code-chip">
                      {dataset ? `${dataset.name} ${dataset.version}` : '未选择数据集'}
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
                        {datasets.length === 0 ? <option value="">无可用数据集</option> : null}
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
                  <p><strong>数据集快照:</strong> <code className="s01-inline-code" title={dataset?.dataset_id ?? undefined}>{dataset?.dataset_id ? `${dataset.dataset_id.slice(0, 8)}…` : '—'}</code></p>
                </div>
              </div>
            </article>
          </section>

          <section className="s01-loop" aria-label="评测闭环">
            <div className="s01-loop-heading">
              <h2>评测闭环</h2>
              <span>从真实会话到可验证的优化</span>
            </div>
            <ol className="s01-loop-steps">
              {[
                { id: '01', name: '数据导入', desc: '导入真实会话，形成可复用的评测数据集' },
                { id: '02', name: '基线评测', desc: '逐会话自动评测，保留完整证据' },
                { id: '03', name: '问题定位', desc: '失败聚合归因，排出优化优先级' },
                { id: '04', name: '目标冻结', desc: '生成优化建议，确认并冻结验证范围' },
                { id: '05', name: '候选验证', desc: '候选版本在同一范围内回归评测' },
                { id: '06', name: '人工决策', desc: '对比改善与回归，由人做最终判断' },
              ].map((step) => (
                <li className="s01-loop-step" key={step.id}>
                  <span className="s01-loop-step-id">{step.id}</span>
                  <strong>{step.name}</strong>
                  <p>{step.desc}</p>
                </li>
              ))}
            </ol>
          </section>

          {run?.status === 'completed' && (reviewLoading || currentReviewData) ? (
            <section className="s01-gates s01-review" aria-labelledby="s01-review-title">
              <div className="s01-gates-heading">
                <h2 id="s01-review-title">人工复核</h2>
                <code>{reviewLoading && !currentReviewData ? '读取中' : `待人工复核 ${pendingReviewResults.length} 条`}</code>
              </div>
              {reviewLoading && !currentReviewData ? <p className="s01-review-state" role="status">正在读取真实最终生效结果…</p> : null}
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
                            <div><dt>机器判定</dt><dd>{judgmentLabels[result.machine_result.judgment]}</dd></div>
                            <div><dt>失败模式</dt><dd>{result.machine_result.primary_failure_mode ? failureModeLabel(result.machine_result.primary_failure_mode) : '—'}</dd></div>
                            <div><dt>问题</dt><dd>{result.machine_result.problem ?? '—'}</dd></div>
                            <div><dt>严重程度</dt><dd>{result.machine_result.severity ? severityLabels[result.machine_result.severity] : '—'}</dd></div>
                          </dl>
                          <div className="s01-review-evidence"><strong>证据 / 判定理由</strong>{result.machine_result.evidence.length ? <ul>{result.machine_result.evidence.map((item, index) => <li key={`${result.evaluation_result_id}-${index}`}>{evidenceTypeLabel(item.evidence_type)}: {item.content}{item.source_ref ? ` (${item.source_ref})` : ''}</li>)}</ul> : <p>无结构化证据。</p>}<p>{result.machine_result.rationale}</p></div>
                          {correcting && correctionDraft ? (
                            <div className="s01-correction-form">
                              <div className="s01-correction-fields">
                                <label><span>判定</span><select value={correctionDraft.judgment} onChange={(event) => { const judgment = event.target.value as JudgeOutput['judgment']; setCorrectionDraft((current) => current ? { ...current, judgment, severity: judgment === 'failure' ? (current.severity ?? result.machine_result.severity ?? 'low') : null } : current) }}><option value="success">成功</option><option value="warning">警告</option><option value="failure">失败</option><option value="uncertain">不确定</option></select></label>
                                <label><span>主要失败模式</span><select value={correctionDraft.primaryFailureMode ?? ''} onChange={(event) => setCorrectionDraft((current) => current ? { ...current, primaryFailureMode: (event.target.value || null) as JudgeOutput['primary_failure_mode'] } : current)}><option value="">无</option>{failureModes.map((mode) => <option key={mode} value={mode}>{failureModeLabel(mode)}</option>)}</select></label>
                                <label className="s01-correction-wide"><span>问题</span><textarea value={correctionDraft.problem} onChange={(event) => setCorrectionDraft((current) => current ? { ...current, problem: event.target.value } : current)} rows={3} /></label>
                                <label><span>严重程度</span><select value={correctionDraft.severity ?? ''} disabled={correctionDraft.judgment !== 'failure'} onChange={(event) => setCorrectionDraft((current) => current ? { ...current, severity: (event.target.value || null) as JudgeOutput['severity'] } : current)}><option value="">无</option><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="critical">严重</option></select></label>
                                <label><span>需人工复核</span><select value={correctionDraft.reviewRequired === null ? 'null' : String(correctionDraft.reviewRequired)} onChange={(event) => setCorrectionDraft((current) => current ? { ...current, reviewRequired: event.target.value === 'null' ? null : event.target.value === 'true' } : current)}><option value="true">是</option><option value="false">否</option><option value="null">未指定</option></select></label>
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
        </div>

        <aside className="s01-side" aria-label="启动新评测">
          <div className="s01-side-card">
            <h2>启动新评测</h2>
            <p className="s01-side-dataset" title={dataset ? `${dataset.name} ${dataset.version}` : undefined}>
              {dataset ? `${dataset.name} ${dataset.version}` : '未选择数据集'}
            </p>
            <dl className="s01-side-summary">
              <div><dt>案例</dt><dd>{dataset ? `${dataset.conversation_count} 个` : '—'}</dd></div>
              <div><dt>场景</dt><dd>{dataset ? formatScenarioDistribution(dataset.scenario_distribution) : '—'}</dd></div>
              <div><dt>数据</dt><dd>{dataset ? `${privacyStatusLabel(dataset.privacy_status)} · ${datasetSourceLabel(dataset.source)}` : '—'}</dd></div>
              <div><dt>快照</dt><dd><code className="s01-inline-code" title={dataset?.dataset_id ?? undefined}>{dataset?.dataset_id ? `${dataset.dataset_id.slice(0, 8)}…` : '—'}</code></dd></div>
            </dl>
            <ul className="s01-side-gates">
              <li className={dataset ? 's01-side-gate s01-side-gate--pass' : 's01-side-gate'}>{dataset ? '✓' : '○'} 数据集已加载</li>
              <li className={dataset && dataset.conversation_count > 0 ? 's01-side-gate s01-side-gate--pass' : 's01-side-gate'}>{dataset && dataset.conversation_count > 0 ? '✓' : '○'} 案例数大于 0</li>
            </ul>
            <button
              className="s01-primary-action s01-primary-action--full"
              type="button"
              disabled={!canStart}
              onClick={() => void startBaseline()}
            >
              {pendingReviewResults.length > 0
                ? '完成待处理复核后继续'
                : working || pageStatus === 'running'
                  ? '评测运行中'
                  : actionLabel}<MdPlayArrow aria-hidden="true" />
            </button>
            <p className="s01-side-note">
              {run ? `运行 ${run.id.slice(0, 8).toUpperCase()} · ` : ''}回答集：所选数据集会话。判定模型与运行来源在启动时由后端固化；评测完成后进入基线分析。
            </p>
          </div>
        </aside>
      </div>
    </section>
  )
}

export default StartQualityReviewPage
