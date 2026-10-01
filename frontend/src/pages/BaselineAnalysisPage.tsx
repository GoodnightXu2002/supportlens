import { useEffect, useMemo, useState } from 'react'
import {
  MdAccountTree,
  MdCancel,
  MdCheckCircle,
  MdError,
  MdFilterList,
  MdGavel,
  MdMenuBook,
  MdPerson,
  MdSmartToy,
} from 'react-icons/md'
import { useNavigate, useSearchParams } from 'react-router-dom'

import {
  ApiRequestError,
  getDatasetConversations,
  getDatasetDetail,
  getDatasetEvaluationRuns,
  getEvaluationRun,
  getFinalEffectiveResults,
  getOptimizationTargets,
  getProblems,
  type DatasetConversation,
  type DatasetDetail,
  type EvaluationRun,
  type FinalEffectiveResult,
  type JudgeOutput,
  type OptimizationTarget,
  type Problem,
} from '../api'
import {
  getProblemSelectionBlocker,
  getRelatedActiveId,
  getSelectedCoreCases,
  getTargetEntryBlocker,
  haveSameProblemIds,
  resolveSelectedProblemIds,
  serializeProblemIds,
  type ProblemSelectionCase,
} from '../baselineTargetGate'
import {
  blockerLabel,
  datasetSourceLabel,
  evidenceTypeLabel,
  failureModeLabel,
  privacyStatusLabel,
  runSourceLabel,
  runStatusLabel,
  scenarioLabel,
} from '../displayLabels'
import './BaselineAnalysisPage.css'

type LoadedData = {
  run: EvaluationRun
  dataset: DatasetDetail
  conversations: DatasetConversation[]
  finalResults: FinalEffectiveResult[]
  problems: Problem[]
  targets: OptimizationTarget[]
  runs: EvaluationRun[]
}

type PageState =
  | { kind: 'missing_run_id' }
  | { kind: 'loading' }
  | { kind: 'run_not_found' }
  | { kind: 'aggregation_not_completed'; run: EvaluationRun }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; data: LoadedData }

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

const signalLabels = {
  high: '高',
  medium: '中',
  low: '低',
  strong: '强',
  moderate: '中',
  weak: '弱',
  unknown: '未知',
} as const

function signalLabel(value: keyof typeof signalLabels | null) {
  return value === null ? '待补充' : signalLabels[value]
}

function patternPlainText(value: keyof typeof signalLabels | null) {
  if (value === 'strong') return '在各案例中表现一致，定位相对容易'
  if (value === 'weak') return '在各案例中表现分散，需要多点修复'
  if (value === 'moderate') return '在各案例中表现有一定规律'
  return '在各案例中的表现规律待确认'
}

function confidencePlainText(value: keyof typeof signalLabels | null) {
  if (value === 'high') return '证据充分'
  if (value === 'moderate') return '证据较为充分'
  return '证据有待补充'
}

function shortId(value: string) {
  return value.slice(0, 8).toUpperCase()
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function metadataRecord(conversation: DatasetConversation | undefined) {
  return conversation?.metadata && typeof conversation.metadata === 'object'
    ? conversation.metadata
    : {}
}

function caseSet(conversation: DatasetConversation | undefined) {
  const metadata = conversation?.metadata?.metadata
  return metadata && typeof metadata === 'object' && 'case_set' in metadata
    ? metadata.case_set
    : undefined
}

function formatMetadata(value: unknown) {
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return null
  try {
    return JSON.stringify(value)
  } catch {
    return null
  }
}

function caseSummary(conversation: DatasetConversation | undefined) {
  return (
    conversation?.messages.find((message) => message.role === 'user')?.content
    ?? '未提供用户消息'
  )
}

function PageMessage({ title, detail }: { title: string; detail: string }) {
  return (
    <section className="s03-page s03-state" role="status">
      <MdError aria-hidden="true" />
      <h1>{title}</h1>
      <p>{detail}</p>
    </section>
  )
}

function sortProblems(problems: Problem[]) {
  return [...problems].sort((left, right) => {
    if (left.rank !== null && right.rank === null) return -1
    if (left.rank === null && right.rank !== null) return 1
    if (left.rank !== null && right.rank !== null && left.rank !== right.rank) {
      return left.rank - right.rank
    }
    return left.definition.localeCompare(right.definition, 'zh-CN')
  })
}

function BaselineAnalysisPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const runId = searchParams.get('run_id')?.trim() ?? ''
  const [loadResult, setLoadResult] = useState<{
    runId: string
    state: PageState
  }>(() =>
    ({
      runId,
      state: runId ? { kind: 'loading' } : { kind: 'missing_run_id' },
    }),
  )
  const [activeProblemId, setActiveProblemId] = useState<string | null>(null)
  const [activeCaseId, setActiveCaseId] = useState<string | null>(null)
  const pageState: PageState = !runId
    ? { kind: 'missing_run_id' }
    : loadResult.runId === runId
      ? loadResult.state
      : { kind: 'loading' }

  useEffect(() => {
    if (!runId) return

    const controller = new AbortController()

    async function load() {
      try {
        const run = await getEvaluationRun(runId, controller.signal)
        if (!run.problem_aggregation_completed_at) {
          setLoadResult({
            runId,
            state: { kind: 'aggregation_not_completed', run },
          })
          return
        }

        const [dataset, conversations, finalResults, problems, targets, runs] = await Promise.all([
          getDatasetDetail(run.dataset_id, controller.signal),
          getDatasetConversations(run.dataset_id, controller.signal),
          getFinalEffectiveResults(run.id, controller.signal),
          getProblems(run.id, controller.signal),
          getOptimizationTargets(run.id, controller.signal),
          getDatasetEvaluationRuns(run.dataset_id, controller.signal),
        ])
        setLoadResult({
          runId,
          state: {
            kind: 'ready',
            data: { run, dataset, conversations, finalResults, problems, targets, runs },
          },
        })
      } catch (error) {
        if (controller.signal.aborted) return
        if (
          error instanceof ApiRequestError
          && (error.status === 404 || error.code === 'evaluation_run_not_found')
        ) {
          setLoadResult({ runId, state: { kind: 'run_not_found' } })
          return
        }
        setLoadResult({
          runId,
          state: {
            kind: 'error',
            message: error instanceof Error ? error.message : '无法加载基线分析数据。',
          },
        })
      }
    }

    void load()
    return () => controller.abort()
  }, [runId])

  const data = pageState.kind === 'ready' ? pageState.data : null
  const problems = useMemo(
    () => sortProblems(data?.problems ?? []),
    [data?.problems],
  )
  const finalResultById = useMemo(
    () => new Map(
      data?.finalResults.map((result) => [result.evaluation_result_id, result])
      ?? [],
    ),
    [data?.finalResults],
  )
  const conversationById = useMemo(
    () => new Map(
      data?.conversations.map((conversation) => [conversation.id, conversation])
      ?? [],
    ),
    [data?.conversations],
  )
  const selectionCasesByProblemId = useMemo(() => new Map(
    problems.map((problem) => [
      problem.problem_id,
      problem.affected_evaluation_result_ids.flatMap((resultId): ProblemSelectionCase[] => {
        const result = finalResultById.get(resultId)
        const conversation = result ? conversationById.get(result.conversation_id) : undefined
        return result?.final_result ? [{
          resultId: result.evaluation_result_id,
          caseId: result.case_id,
          caseSet: caseSet(conversation),
          judgment: result.final_result.judgment,
          primaryFailureMode: result.final_result.primary_failure_mode,
        }] : []
      }),
    ]),
  ), [conversationById, finalResultById, problems])
  const selectableProblemIds = useMemo(() => problems
    .filter((problem) => !getProblemSelectionBlocker(
      selectionCasesByProblemId.get(problem.problem_id) ?? [],
    ))
    .map((problem) => problem.problem_id), [problems, selectionCasesByProblemId])
  const selectedProblemIds = resolveSelectedProblemIds(
    searchParams.get('problem_ids'),
    searchParams.get('problem_id'),
    selectableProblemIds,
  )
  const selectedCoreCases = getSelectedCoreCases(
    selectedProblemIds,
    selectionCasesByProblemId,
  )
  const selectedCoreCaseByResultId = new Map(
    selectedCoreCases.map((item) => [item.resultId, item]),
  )
  const affectedResults = selectedCoreCases
    .map((item) => finalResultById.get(item.resultId))
    .filter((result): result is FinalEffectiveResult => result !== undefined)
  const requestedProblemId = [activeProblemId, searchParams.get('problem_id')]
    .find((problemId) => problems.some((problem) => problem.problem_id === problemId))
  const requestedProblemCaseIds = new Set(
    selectedCoreCases
      .filter((item) => item.problemIds.includes(requestedProblemId ?? ''))
      .map((item) => item.resultId),
  )
  const requestedCase = affectedResults.find(
    (result) => result.evaluation_result_id === activeCaseId,
  )
  const selectedResult = (
    requestedCase && (
      !requestedProblemId || requestedProblemCaseIds.has(requestedCase.evaluation_result_id)
    )
      ? requestedCase
      : requestedProblemId
        ? affectedResults.find((result) => requestedProblemCaseIds.has(result.evaluation_result_id))
        : affectedResults[0]
  )
  const selectedResultProblemIds = selectedResult
    ? selectedCoreCaseByResultId.get(selectedResult.evaluation_result_id)?.problemIds ?? []
    : []
  const selectedProblem = (
    problems.find((problem) => problem.problem_id === requestedProblemId)
    ?? problems.find((problem) => problem.problem_id === selectedResultProblemIds[0])
    ?? problems[0]
  )
  const selectedTarget = selectedProblemIds.length
    ? data?.targets
      .filter((target) => haveSameProblemIds(target.problem_ids, selectedProblemIds))
      .sort((left, right) => right.version - left.version)[0] ?? null
    : null
  const selectedCandidateRun = selectedTarget
    ? data?.runs.find((run) => run.run_type === 'candidate' && run.target_id === selectedTarget.id) ?? null
    : null
  const workflowSearchParams = (() => {
    if (!data || !selectedProblem) return null
    const params = new URLSearchParams({
      run_id: data.run.id,
      problem_id: selectedProblem.problem_id,
      problem_ids: serializeProblemIds(selectedProblemIds),
    })
    if (selectedTarget) {
      params.set('target_id', selectedTarget.id)
      if (selectedCandidateRun) params.set('candidate_run_id', selectedCandidateRun.id)
    }
    return params
  })()
  const workflowSearch = workflowSearchParams?.toString() ?? ''
  const currentSearch = searchParams.toString()

  useEffect(() => {
    if (workflowSearch && workflowSearch !== currentSearch) {
      setSearchParams(workflowSearch, { replace: true })
    }
  }, [currentSearch, setSearchParams, workflowSearch])
  const selectedConversation = selectedResult
    ? conversationById.get(selectedResult.conversation_id)
    : undefined
  const selectedEvidence = selectedResult
    ? (selectedCoreCaseByResultId.get(selectedResult.evaluation_result_id)?.problemIds ?? [])
      .flatMap((problemId) => problems.find((problem) => problem.problem_id === problemId)
        ?.evidence.filter(
          (item) => item.evaluation_result_id === selectedResult.evaluation_result_id,
        ) ?? [])
    : []

  if (pageState.kind === 'missing_run_id') {
    return (
      <PageMessage
        title="缺少评测运行"
        detail="请使用 /baseline?run_id=<evaluation_run_id> 打开基线分析。"
      />
    )
  }
  if (pageState.kind === 'loading') {
    return <PageMessage title="正在加载基线分析" detail="正在读取真实评测数据…" />
  }
  if (pageState.kind === 'run_not_found') {
    return (
      <PageMessage
        title="评测运行不存在"
        detail={`未找到 run_id=${runId} 对应的评测运行。`}
      />
    )
  }
  if (pageState.kind === 'aggregation_not_completed') {
    return (
      <PageMessage
        title="问题聚合尚未完成"
        detail={`运行 ${shortId(pageState.run.id)} 当前不能展示正式问题数据。`}
      />
    )
  }
  if (pageState.kind === 'error') {
    return <PageMessage title="基线分析加载失败" detail={pageState.message} />
  }
  if (!data) return null

  const pendingReviewCount = data.finalResults.filter(
    (result) => result.status === 'pending_review',
  ).length
  const metadata = metadataRecord(selectedConversation)
  const businessContext = formatMetadata(metadata.business_context)
  const referenceEvidence = formatMetadata(metadata.reference_evidence)
  const userMessages = selectedConversation?.messages.filter(
    (message) => message.role === 'user',
  ) ?? []
  const assistantMessages = selectedConversation?.messages.filter(
    (message) => message.role === 'assistant',
  ) ?? []
  const factEvidence = selectedEvidence.filter(
    (item) => item.evidence_type === 'case_fact',
  )
  const referenceItems = selectedEvidence.filter(
    (item) => item.evidence_type === 'reference',
  )
  const isHumanCorrection = selectedResult?.human_decision
    ? JSON.stringify(selectedResult.human_decision.original_result)
      !== JSON.stringify(selectedResult.human_decision.final_result)
    : false
  const selectedProblems = selectedProblemIds
    .map((problemId) => problems.find((problem) => problem.problem_id === problemId))
    .filter((problem): problem is Problem => problem !== undefined)
  const targetEntryBlocker = selectedProblems.length === 0
    ? '请至少选择 1 个可优化问题。'
    : selectedProblems.map((problem) => getTargetEntryBlocker({
      hasExistingTarget: Boolean(selectedTarget),
      runType: data.run.run_type,
      runStatus: data.run.status,
      pendingReviewCount,
      problem,
      affectedFinalResults: problem.affected_evaluation_result_ids
        .map((resultId) => finalResultById.get(resultId)),
    })).find((blocker) => blocker !== null) ?? null
  const activateProblem = (problemId: string) => {
    const relatedCaseIds = selectedCoreCases
      .filter((item) => item.problemIds.includes(problemId))
      .map((item) => item.resultId)
    const currentCaseId = selectedResult?.evaluation_result_id
    setActiveProblemId(problemId)
    setActiveCaseId(getRelatedActiveId(currentCaseId, relatedCaseIds))
  }
  const activateCase = (resultId: string) => {
    const relatedProblemIds = selectedCoreCaseByResultId.get(resultId)?.problemIds ?? []
    const currentProblemId = selectedProblem?.problem_id
    setActiveCaseId(resultId)
    setActiveProblemId(getRelatedActiveId(currentProblemId, relatedProblemIds))
  }

  return (
    <section className="s03-page" aria-label="基线分析工作区">
      <div className="s03-review-strip">
        <div className="s03-review-strip__content">
          <div className="s03-review-state">
            <span
              className={pendingReviewCount === 0
                ? 's03-review-state__dot s03-review-state__dot--success'
                : 's03-review-state__dot'}
              aria-hidden="true"
            />
            <div>
              <h1>{pendingReviewCount === 0 ? '人工复核已清空' : '需要人工复核 - 非最终结论'}</h1>
              <p>{pendingReviewCount === 0 ? '复核已完成' : `待复核：${pendingReviewCount}`}</p>
            </div>
          </div>

          <span className="s03-review-strip__divider" aria-hidden="true" />

          <dl className="s03-metadata">
            <div>
              <dt>数据集</dt>
              <dd className="s03-metadata__two-lines" title={`${data.dataset.name} ${data.dataset.version}`}>
                {data.dataset.name} {data.dataset.version}
              </dd>
            </div>
            <div>
              <dt>评测运行</dt>
              <dd title={`${data.run.id} · ${runSourceLabel(data.run.run_source)} · ${data.run.created_at}`}>
                {shortId(data.run.id)} · {runStatusLabel(data.run.status)}
              </dd>
            </div>
            <div>
              <dt>数据类型</dt>
              <dd>{privacyStatusLabel(data.dataset.privacy_status)} · {datasetSourceLabel(data.dataset.source)}</dd>
            </div>
            <div className="s03-metadata__type">
              <dt>判定配置</dt>
              <dd title={data.run.judge_model}>{data.run.judge_contract_version}</dd>
            </div>
            <div>
              <dt>声明范围</dt>
              <dd className="s03-metadata__two-lines" title={data.dataset.representativeness_statement ?? undefined}>
                {data.dataset.representativeness_statement ?? '未提供代表性声明'}
              </dd>
            </div>
          </dl>
        </div>

      </div>

      <div className="s03-workspace">
        <section className="s03-pane s03-problems" aria-labelledby="s03-problems-title">
          <header className="s03-pane-header">
            <div className="s03-problem-heading">
              <h2 id="s03-problems-title">问题聚类（{problems.length}）</h2>
              <p aria-live="polite">
                已选择 {selectedProblemIds.length} 个问题 · 影响 {selectedCoreCases.length} 个核心案例
                {selectedProblemIds.length === 0 ? <strong> · 至少选择 1 个</strong> : null}
              </p>
            </div>
            <button className="s03-icon-button" type="button" aria-label="筛选问题聚类" disabled>
              <MdFilterList aria-hidden="true" />
            </button>
          </header>

          <div className="s03-pane-scroll s03-problem-list">
            {problems.length === 0 ? (
              <p className="s03-empty-message">问题聚合已完成，本次运行没有可展示的问题。</p>
            ) : problems.map((problem) => {
              const isActive = problem.problem_id === selectedProblem?.problem_id
              const selectionBlocker = getProblemSelectionBlocker(
                selectionCasesByProblemId.get(problem.problem_id) ?? [],
              )
              const isSelected = selectedProblemIds.includes(problem.problem_id)
              const frequencyPercent = problem.frequency.denominator === 0
                ? null
                : (problem.frequency.numerator / problem.frequency.denominator) * 100
              const frequencyPer100 = frequencyPercent === null
                ? null
                : Math.round(frequencyPercent)
              return (
                <article
                  className={isActive
                    ? 's03-problem-card s03-problem-card--active'
                    : 's03-problem-card'}
                  key={problem.problem_id}
                  onClick={() => activateProblem(problem.problem_id)}
                >
                  <div className="s03-problem-card__topline">
                    <span
                      className={isActive ? 's03-code-label s03-code-label--strong' : 's03-code-label'}
                      title={problem.problem_id}
                    >
                      {scenarioLabel(problem.scenario)} · P-{shortId(problem.problem_id)}
                    </span>
                    <div className="s03-problem-card__controls">
                      <span className={isActive ? 's03-count-badge s03-count-badge--active' : 's03-count-badge'}>
                        {problem.affected_case_count} 个案例
                      </span>
                      <label
                        className="s03-problem-selector"
                        title={selectionBlocker ?? '纳入本轮优化'}
                        onClick={(event) => event.stopPropagation()}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          disabled={Boolean(selectionBlocker)}
                          aria-label={`${isSelected ? '移出' : '纳入'}本轮优化：${problem.definition}`}
                          onChange={() => {
                            const nextProblemIds = isSelected
                              ? selectedProblemIds.filter((problemId) => problemId !== problem.problem_id)
                              : [...selectedProblemIds, problem.problem_id]
                            const params = new URLSearchParams({
                              run_id: runId,
                              problem_id: selectedProblem?.problem_id ?? problem.problem_id,
                              problem_ids: serializeProblemIds(nextProblemIds),
                            })
                            setSearchParams(params)
                          }}
                        />
                        <span>{selectionBlocker ? '不可选' : '本轮'}</span>
                      </label>
                    </div>
                  </div>
                  <h3>{problem.definition}</h3>
                  {isActive ? (
                    <>
                      <dl className="s03-priority-grid">
                        <div><dt><span className="s03-dot s03-dot--critical" aria-hidden="true" />严重程度：</dt><dd>{problem.priority_severity ? severityLabels[problem.priority_severity] : '不可用'}</dd></div>
                        <div><dt><span className="s03-dot s03-dot--critical" aria-hidden="true" />业务影响：</dt><dd>{signalLabel(problem.business_impact)}</dd></div>
                        <div className="s03-priority-grid__frequency"><dt><span className="s03-dot s03-dot--secondary" aria-hidden="true" />频率：</dt><dd>{problem.frequency.numerator}/{problem.frequency.denominator}{frequencyPercent === null ? '' : ` (${frequencyPercent.toFixed(1)}%)`}{frequencyPer100 !== null && frequencyPer100 > 0 ? ` · 约每 100 个案例中出现 ${frequencyPer100} 例` : ''}</dd></div>
                        <div><dt><span className="s03-dot s03-dot--info" aria-hidden="true" />模式一致性：</dt><dd>{signalLabel(problem.pattern_consistency)}</dd></div>
                        <div className="s03-priority-grid__wide"><dt><span className="s03-dot s03-dot--info" aria-hidden="true" />证据置信度：</dt><dd>{signalLabel(problem.evidence_confidence)}</dd></div>
                      </dl>
                      <p className="s03-profile-detail">
                        该问题{patternPlainText(problem.pattern_consistency)}，{confidencePlainText(problem.evidence_confidence)}。
                      </p>
                      <p className="s03-profile-detail">
                        严重程度分布：低 {problem.severity_distribution.low} / 中 {problem.severity_distribution.medium} / 高 {problem.severity_distribution.high} / 严重 {problem.severity_distribution.critical}
                      </p>
                      <p className="s03-ranking-detail">
                        {problem.rank !== null
                          ? `密集排名 ${problem.rank}${problem.equal_review_priority ? ' · 复核优先级相同' : ''}`
                          : `暂无法排序${problem.ranking_blockers.length > 0 ? `：${problem.ranking_blockers.map(blockerLabel).join('、')}` : ''}`}
                      </p>
                    </>
                  ) : (
                    <p className="s03-severity">
                      <span className="s03-dot s03-dot--warning" aria-hidden="true" />
                      严重程度：{problem.priority_severity ? severityLabels[problem.priority_severity] : '不可用'}
                    </p>
                  )}
                </article>
              )
            })}
          </div>
        </section>

        <section className="s03-pane s03-cases" aria-labelledby="s03-cases-title">
          <header className="s03-pane-header s03-cases-header">
            <h2 id="s03-cases-title">本轮核心案例（{affectedResults.length}）</h2>
          </header>

          <div className="s03-pane-scroll s03-case-list">
            {affectedResults.length > 0 ? (
              <>
                <div className="s03-case-grid s03-case-table-head" aria-hidden="true">
                  <span>案例 ID</span><span>意图摘要 / 关联问题</span>
                </div>
                <div className="s03-case-rows">
                  {affectedResults.map((result) => {
                    const conversation = conversationById.get(result.conversation_id)
                    const relatedProblems = (
                      selectedCoreCaseByResultId.get(result.evaluation_result_id)?.problemIds ?? []
                    ).flatMap((problemId) => {
                      const problem = problems.find((item) => item.problem_id === problemId)
                      return problem ? [problem] : []
                    })
                    const isSelectedCase = result.evaluation_result_id === selectedResult?.evaluation_result_id
                    const isRelatedToActiveProblem = relatedProblems.some(
                      (problem) => problem.problem_id === selectedProblem?.problem_id,
                    )
                    return (
                      <article
                        className={[
                          's03-case-grid s03-case-row',
                          isSelectedCase ? 's03-case-row--selected' : '',
                          isRelatedToActiveProblem ? 's03-case-row--related' : '',
                        ].filter(Boolean).join(' ')}
                        key={result.evaluation_result_id}
                        onClick={() => activateCase(result.evaluation_result_id)}
                      >
                        <span className="s03-case-id">
                          {isSelectedCase ? <span className="s03-case-id__rail" aria-hidden="true" /> : null}
                          {result.case_id}
                        </span>
                        <span className="s03-case-detail">
                          <span className="s03-case-summary" title={caseSummary(conversation)}>{caseSummary(conversation)}</span>
                          <span className="s03-case-problems">
                            {relatedProblems.map((problem) => (
                              <span key={problem.problem_id} title={problem.definition}>
                                {scenarioLabel(problem.scenario)} · P-{shortId(problem.problem_id)}
                              </span>
                            ))}
                          </span>
                        </span>
                      </article>
                    )
                  })}
                </div>
              </>
            ) : (
              <p className="s03-empty-message">选择至少一个可优化问题后查看本轮核心案例。</p>
            )}
          </div>
        </section>

        <section className="s03-pane s03-evidence" aria-labelledby="s03-evidence-title">
          <header className="s03-pane-header s03-evidence-header">
            <h2 id="s03-evidence-title">证据链 {selectedResult ? <span>{selectedResult.case_id}</span> : null}</h2>
            <MdAccountTree aria-hidden="true" />
          </header>

          <div className="s03-pane-scroll s03-evidence-ledger">
            {!selectedResult || !selectedConversation ? (
              <p className="s03-empty-message">选择一个本轮核心案例后查看证据链。</p>
            ) : (
              <>
                <div className="s03-evidence-line" aria-hidden="true" />

                <article className="s03-evidence-node">
                  <span className="s03-node-marker"><span /></span>
                  <div className="s03-node-content">
                    <h3>节点 1 / 用户消息</h3>
                    {userMessages.map((message, index) => (
                      <blockquote key={`${selectedConversation.id}-user-${index}`}>{message.content}</blockquote>
                    ))}
                  </div>
                </article>

                <article className="s03-evidence-node">
                  <span className="s03-node-marker"><span /></span>
                  <div className="s03-node-content">
                    <h3>节点 2 / 当前客服回复</h3>
                    {assistantMessages.map((message, index) => (
                      <blockquote key={`${selectedConversation.id}-assistant-${index}`}>{message.content}</blockquote>
                    ))}
                  </div>
                </article>

                <article className="s03-evidence-node">
                  <span className="s03-node-marker s03-node-marker--icon"><MdSmartToy aria-hidden="true" /></span>
                  <div className="s03-node-content">
                    <h3 className="s03-node-title--italic">节点 3 / AI 评测判定</h3>
                    <div className="s03-ai-judgment">
                      <div className="s03-ai-judgment__status">
                        <span className={`s03-ai-judgment__verdict s03-ai-judgment__verdict--${selectedResult.machine_result.judgment}`}>
                          判定：{judgmentLabels[selectedResult.machine_result.judgment]}
                        </span>
                        <span>{selectedResult.machine_result.primary_failure_mode ? failureModeLabel(selectedResult.machine_result.primary_failure_mode) : '无主要失败模式'}</span>
                      </div>
                      <p>问题：{selectedResult.machine_result.problem ?? '无'}</p>
                      <p>
                        严重程度：{selectedResult.machine_result.severity ? severityLabels[selectedResult.machine_result.severity] : '不可用'}
                        {' · '}需人工复核：{selectedResult.machine_result.review_required === null ? '不可用' : selectedResult.machine_result.review_required ? '是' : '否'}
                      </p>
                      {selectedResult.machine_result.secondary_flags.length > 0 ? (
                        <p>次要标记：{selectedResult.machine_result.secondary_flags.map(failureModeLabel).join('、')}</p>
                      ) : null}
                      {selectedResult.machine_result.uncertainty ? (
                        <p>不确定性：{selectedResult.machine_result.uncertainty}</p>
                      ) : null}
                      <p>{selectedResult.machine_result.rationale}</p>
                      {selectedResult.machine_result.evidence.length > 0 ? (
                        <ul>{selectedResult.machine_result.evidence.map((item, index) => <li key={`${selectedResult.evaluation_result_id}-machine-${index}`}>{evidenceTypeLabel(item.evidence_type)}: {item.content}{item.source_ref ? ` (${item.source_ref})` : ''}</li>)}</ul>
                      ) : null}
                    </div>
                  </div>
                </article>

                <article className="s03-evidence-node">
                  <span className="s03-node-marker"><span className="s03-node-marker__fact" /></span>
                  <div className="s03-node-content">
                    <h3>节点 4 / 业务上下文与事实</h3>
                    {businessContext ? <p className="s03-context-copy">{businessContext}</p> : null}
                    {factEvidence.length > 0 ? (
                      <ul>{factEvidence.map((item, index) => <li key={`${item.evaluation_result_id}-fact-${index}`}>{item.content}</li>)}</ul>
                    ) : <p className="s03-evidence-empty">最终生效结果未提供案例事实证据。</p>}
                  </div>
                </article>

                <article className="s03-evidence-node">
                  <span className="s03-node-marker s03-node-marker--icon"><MdMenuBook aria-hidden="true" /></span>
                  <div className="s03-node-content">
                    <h3>节点 5 / 参考依据</h3>
                    {referenceEvidence ? <p className="s03-reference">{referenceEvidence}</p> : null}
                    {referenceItems.length > 0 ? (
                      <ul>{referenceItems.map((item, index) => <li key={`${item.evaluation_result_id}-reference-${index}`}>{item.content}{item.source_ref ? ` (${item.source_ref})` : ''}</li>)}</ul>
                    ) : null}
                    {!referenceEvidence && referenceItems.length === 0 ? <p className="s03-evidence-empty">未提供可追溯的参考证据。</p> : null}
                  </div>
                </article>

                <article className="s03-evidence-node">
                  <span className="s03-node-marker s03-node-marker--human"><MdPerson aria-hidden="true" /></span>
                  <div className="s03-node-content">
                    <h3 className="s03-node-title--strong">节点 6 / 人工复核</h3>
                    <div className="s03-human-review">
                      {selectedResult.human_decision ? (
                        <>
                          <p className="s03-human-review__decision">
                            {isHumanCorrection ? <MdCancel aria-hidden="true" /> : <MdCheckCircle aria-hidden="true" />}
                            {isHumanCorrection ? '已修正机器判定' : '已确认机器判定'}
                          </p>
                          <div><span>复核人 / 时间</span><p>{selectedResult.human_decision.reviewer} · {formatDate(selectedResult.human_decision.reviewed_at)}</p></div>
                          <div><span>复核理由</span><p>{selectedResult.human_decision.change_reason ?? '结论未修改，无修正理由。'}</p></div>
                        </>
                      ) : (
                        <p className={selectedResult.status === 'pending_review'
                          ? 's03-human-review__decision s03-human-review__decision--pending'
                          : 's03-human-review__decision s03-human-review__decision--neutral'}>
                          {selectedResult.status === 'pending_review' ? '等待人工复核' : '机器最终结论 / 无人工复核'}
                        </p>
                      )}
                    </div>
                  </div>
                </article>

                <article className="s03-evidence-node">
                  <span className={`s03-node-marker s03-node-marker--final${selectedResult.final_result ? ` s03-node-marker--final-${selectedResult.final_result.judgment}` : ''}`}><MdGavel aria-hidden="true" /></span>
                  <div className="s03-node-content">
                    <h3>节点 7 / 最终生效结果</h3>
                    <div className={`s03-final-result${selectedResult.final_result ? ` s03-final-result--${selectedResult.final_result.judgment}` : ''}`}>
                      <div><span>最终判定</span><strong>{selectedResult.final_result ? judgmentLabels[selectedResult.final_result.judgment] : '待人工复核'}</strong></div>
                      <div><span>记录状态</span><em>{selectedResult.status === 'final' ? (selectedResult.source === 'human' ? '人工最终结论' : '机器最终结论') : '待人工复核'}</em></div>
                      {selectedResult.final_result ? (
                        <p>
                          问题：{selectedResult.final_result.problem ?? '无'}<br />
                          严重程度：{selectedResult.final_result.severity ? severityLabels[selectedResult.final_result.severity] : '不可用'} · {selectedResult.final_result.primary_failure_mode ? failureModeLabel(selectedResult.final_result.primary_failure_mode) : '无主要失败模式'}
                        </p>
                      ) : null}
                      <p>{selectedResult.final_result?.rationale ?? '人工复核完成前不存在最终生效结果。'}</p>
                      {selectedResult.final_result?.evidence.length ? (
                        <ul>{selectedResult.final_result.evidence.map((item, index) => <li key={`${selectedResult.evaluation_result_id}-final-${index}`}>{evidenceTypeLabel(item.evidence_type)}: {item.content}{item.source_ref ? ` (${item.source_ref})` : ''}</li>)}</ul>
                      ) : null}
                    </div>
                  </div>
                </article>
              </>
            )}
          </div>
        </section>
      </div>

      <footer className="s03-bottom-bar">
        <div className="s03-analyst"><strong title={data.run.id}>运行 {shortId(data.run.id)}</strong></div>
        <div className="s03-bottom-actions">
          <span className={targetEntryBlocker ? undefined : 's03-bottom-actions__info'}>
            {targetEntryBlocker ?? `${data.finalResults.length} 条最终生效结果`}
          </span>
          <button
            type="button"
            disabled={Boolean(targetEntryBlocker)}
            onClick={() => {
              if (!workflowSearchParams) return
              navigate(`/target-plan?${workflowSearchParams.toString()}`)
            }}
          >
            进入目标与计划
          </button>
        </div>
      </footer>
    </section>
  )
}

export default BaselineAnalysisPage
