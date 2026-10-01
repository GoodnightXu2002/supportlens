import { useCallback, useEffect, useRef, useState } from 'react'
import { MdError, MdExpandMore } from 'react-icons/md'
import { useNavigate, useSearchParams } from 'react-router-dom'

import {
  ApiRequestError,
  completeProblemSetOptimizationTarget,
  createProblemSetOptimizationTarget,
  generateOptimizationTargetSuggestions,
  getDatasetConversations,
  getDatasetDetail,
  getDatasetEvaluationRuns,
  getEvaluationRun,
  getOptimizationTargets,
  getProblems,
  type DatasetDetail,
  type DatasetConversation,
  type EvaluationRun,
  type OptimizationSuggestion,
  type OptimizationTarget,
  type OptimizationTargetCreateInput,
  type Problem,
} from '../api'
import {
  haveSameProblemIds,
  parseProblemIds,
  serializeProblemIds,
} from '../baselineTargetGate'
import { scenarioLabel } from '../displayLabels'
import { buildValidationCaseExport } from '../validationHandoff'
import './TargetPlanPage.css'

type TargetForm = {
  definition: string
  inclusionCriteria: string
  exclusionCriteria: string
  expectedObservableChange: string
  hypothesisStatement: string
  hypothesisEvidenceRefs: string
  changeSurface: string
  plannedChange: string
  guardrails: string
  protectedCapabilities: string
}

type LoadedData = {
  run: EvaluationRun
  dataset: DatasetDetail
  conversations: DatasetConversation[]
  problems: Problem[]
  target: OptimizationTarget | null
  candidateRunId: string | null
}

type SuggestionGenerationState = {
  targetId: string
  status: 'idle' | 'generating' | 'error'
  suggestions: OptimizationSuggestion[] | null
  error: string | null
}

const idleSuggestionGeneration: SuggestionGenerationState = {
  targetId: '',
  status: 'idle',
  suggestions: null,
  error: null,
}

type PageState =
  | { kind: 'missing_parameters' }
  | { kind: 'loading' }
  | { kind: 'run_not_found' }
  | { kind: 'problem_not_found' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; data: LoadedData }

const emptyForm: TargetForm = {
  definition: '',
  inclusionCriteria: '',
  exclusionCriteria: '',
  expectedObservableChange: '',
  hypothesisStatement: '',
  hypothesisEvidenceRefs: '',
  changeSurface: '',
  plannedChange: '',
  guardrails: '',
  protectedCapabilities: '',
}

const evaluationRunStatusLabels: Record<EvaluationRun['status'], string> = {
  pending: '待开始',
  running: '运行中',
  completed: '已完成',
  partial_failure: '部分失败',
  failed: '失败',
  invalid: '无效',
}

const targetStatusLabels: Record<OptimizationTarget['status'], string> = {
  draft: '草稿',
  confirmed: '已确认',
  frozen: '已确认锁定',
}

const severityLabels: Record<NonNullable<Problem['priority_severity']>, string> = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '严重',
}

function joinEntries(values: string[]) {
  return values.join('\n')
}

function splitEntries(value: string) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function formFromTarget(target: OptimizationTarget): TargetForm {
  return {
    definition: target.definition,
    inclusionCriteria: target.inclusion_criteria,
    exclusionCriteria: target.exclusion_criteria,
    expectedObservableChange: target.expected_observable_change,
    hypothesisStatement: target.hypothesis_statement ?? '',
    hypothesisEvidenceRefs: joinEntries(target.hypothesis_evidence_refs),
    changeSurface: target.change_surface ?? '',
    plannedChange: target.planned_change ?? '',
    guardrails: joinEntries(target.guardrails),
    protectedCapabilities: joinEntries(target.protected_capabilities),
  }
}

function requestFromForm(form: TargetForm): OptimizationTargetCreateInput {
  return {
    definition: form.definition.trim(),
    inclusion_criteria: form.inclusionCriteria.trim(),
    exclusion_criteria: form.exclusionCriteria.trim(),
    expected_observable_change: form.expectedObservableChange.trim(),
    hypothesis_statement: form.hypothesisStatement.trim() || null,
    hypothesis_evidence_refs: splitEntries(form.hypothesisEvidenceRefs),
    change_surface: form.changeSurface.trim() || null,
    planned_change: form.plannedChange.trim() || null,
    guardrails: splitEntries(form.guardrails),
    protected_capabilities: splitEntries(form.protectedCapabilities),
  }
}

function defaultTargetInput(problems: Problem[]): OptimizationTargetCreateInput {
  return {
    definition: `改善本轮 ${problems.length} 个问题：\n${problems.map((problem) => problem.definition).join('\n')}`,
    inclusion_criteria: '所选问题涉及的核心案例去重并集。',
    exclusion_criteria: '其余核心案例不计入目标案例，并作为回归案例。',
    expected_observable_change: '减少所选问题在目标案例中的出现，并保持回归案例表现。',
  }
}

function shortId(value: string) {
  return value.slice(0, 8).toUpperCase()
}

function formatDate(value: string | null) {
  if (!value) return '未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function conversationCaseSet(conversation: DatasetConversation) {
  const metadata = conversation.metadata?.metadata
  return metadata && typeof metadata === 'object' && 'case_set' in metadata
    ? metadata.case_set
    : undefined
}

function validationScope(problems: Problem[], conversations: DatasetConversation[]) {
  const affectedCaseIds = new Set(problems.flatMap((problem) => problem.affected_case_ids))
  return {
    targetCaseIds: conversations
      .filter((item) => conversationCaseSet(item) === 'core' && affectedCaseIds.has(item.external_id))
      .map((item) => item.external_id),
    regressionCaseIds: conversations
      .filter((item) => conversationCaseSet(item) === 'core' && !affectedCaseIds.has(item.external_id))
      .map((item) => item.external_id),
    challengeCaseIds: conversations
      .filter((item) => conversationCaseSet(item) === 'challenge')
      .map((item) => item.external_id),
  }
}

function ContextMetadata({ data, form }: { data: LoadedData; form: TargetForm }) {
  const target = data.target
  const targetEdited = target && target.status !== 'frozen' && (
    form.definition.trim() !== target.definition.trim()
    || form.expectedObservableChange.trim() !== target.expected_observable_change.trim()
  )
  return (
    <div className="s04-metadata-strip">
      <dl className="s04-metadata">
        <div><dt>数据集</dt><dd title={`${data.dataset.name} ${data.dataset.version}`}>{data.dataset.name} {data.dataset.version}</dd></div>
        <div><dt>基线运行</dt><dd title={data.run.id}>{shortId(data.run.id)} · {evaluationRunStatusLabels[data.run.status]}</dd></div>
        <div><dt>目标状态</dt><dd>{targetEdited ? '已修改 · 待提交确认' : target ? `${targetStatusLabels[target.status]} · V${target.version}` : '尚未创建'}</dd></div>
      </dl>
    </div>
  )
}

function PageMessage({ title, detail }: { title: string; detail: string }) {
  return (
    <section className="s04-page s04-page-message" role="status">
      <MdError aria-hidden="true" /><h1>{title}</h1><p>{detail}</p>
    </section>
  )
}

type TargetPlanWorkspaceProps = {
  data: LoadedData
  form: TargetForm
  actor: string
  pendingAction: string | null
  actionError: string | null
  suggestionGeneration: SuggestionGenerationState
  onActorChange: (value: string) => void
  onExportValidationCases: () => void
  onEnterValidation: () => void
  onRetrySuggestions: () => void
}

function TargetPlanWorkspace({ data, form, actor, pendingAction, actionError,
  suggestionGeneration, onActorChange, onExportValidationCases, onEnterValidation, onRetrySuggestions,
}: TargetPlanWorkspaceProps) {
  const { problems, target } = data
  const frozen = target?.status === 'frozen'
  const busy = pendingAction !== null
  const [expandedPairs, setExpandedPairs] = useState<Set<string>>(new Set())
  const scope = validationScope(problems, data.conversations)
  const targetCaseCount = target?.target_case_ids.length ?? scope.targetCaseIds.length
  const regressionCaseCount = target?.regression_case_ids.length ?? scope.regressionCaseIds.length
  const challengeCaseCount = target?.challenge_case_ids.length ?? scope.challengeCaseIds.length
  const missingCases = targetCaseCount === 0
  const requiredFields = [form.definition, form.inclusionCriteria, form.exclusionCriteria, form.expectedObservableChange]
  const canEnter = frozen || (requiredFields.every((value) => value.trim()) && actor.trim() && !missingCases)
  const generatedSuggestions = target && suggestionGeneration.targetId === target.id
    && suggestionGeneration.status !== 'error'
    ? suggestionGeneration.suggestions
    : null
  const suggestions = target?.optimization_suggestions ?? generatedSuggestions
  const suggestionByProblemId = new Map(
    (suggestions ?? []).map((item) => [item.problem_id, item.suggestion]),
  )
  const suggestionStatusForTarget = target
    && suggestionGeneration.targetId === target.id
    ? suggestionGeneration.status
    : 'idle'
  return (
    <section className="s04-page">
      <ContextMetadata data={data} form={form} />

      <div className="s04-plan-scroll">
        <section className="s04-scope" aria-label="验证范围">
          <div className="s04-scope-line">
            <div className="s04-scope-stat"><span className="s04-scope-label">目标案例</span><strong>{targetCaseCount}</strong></div>
            <div className="s04-scope-stat"><span className="s04-scope-label">回归案例</span><strong>{regressionCaseCount}</strong></div>
            <div className="s04-scope-stat"><span className="s04-scope-label">挑战案例</span><strong>{challengeCaseCount}</strong></div>
            <p className="s04-scope-criteria" title={form.inclusionCriteria}><span>纳入</span>{form.inclusionCriteria}</p>
            <p className="s04-scope-criteria" title={form.exclusionCriteria}><span>排除</span>{form.exclusionCriteria}</p>
          </div>
          {missingCases && <p className="s04-alert" role="alert">所选问题缺少目标案例。</p>}
        </section>

        <section className="s04-pairs" aria-labelledby="s04-pairs-title">
          <header className="s04-pairs-header">
            <h2 id="s04-pairs-title">优化问题 → 系统建议（{problems.length} 对）</h2>
            {suggestionStatusForTarget === 'generating' ? <span className="s04-generating" role="status">正在生成系统优化建议…</span> : null}
          </header>
          {suggestionStatusForTarget === 'error' ? (
            <div className="s04-generation-error" role="alert">
              <span>{suggestionGeneration.error}</span>
              <button type="button" onClick={onRetrySuggestions}>重新生成</button>
            </div>
          ) : null}
          <ol className="s04-pair-list">
            {problems.map((problem, index) => {
              const suggestionText = suggestionByProblemId.get(problem.problem_id)
              const isOpen = expandedPairs.has(problem.problem_id)
              const pending = suggestionStatusForTarget === 'generating'
              const suggestionSlot = pending
                ? '正在生成…'
                : suggestionText
                  ? suggestionText
                  : target?.status === 'frozen'
                    ? '该历史目标未生成系统优化建议'
                    : '暂无优化建议。'
              const togglePair = () => {
                setExpandedPairs((current) => {
                  const next = new Set(current)
                  if (next.has(problem.problem_id)) next.delete(problem.problem_id)
                  else next.add(problem.problem_id)
                  return next
                })
              }
              return (
                <li className={isOpen ? 's04-pair-row s04-pair-row--open' : 's04-pair-row'} key={problem.problem_id}>
                  <button type="button" className="s04-pair-toggle" aria-expanded={isOpen} onClick={togglePair}>
                    <span className="s04-pair-meta">
                      <span className="s04-pair-num">{String(index + 1).padStart(2, '0')}</span>
                      <span className="s04-pair-scenario">{scenarioLabel(problem.scenario)}</span>
                      {problem.priority_severity ? (
                        <span className={`s04-severity s04-severity--${problem.priority_severity}`}>严重度 {severityLabels[problem.priority_severity]}</span>
                      ) : (
                        <span className="s04-severity">严重度 待补充</span>
                      )}
                      <MdExpandMore aria-hidden="true" className="s04-pair-chevron" />
                      <span className="s04-pair-pid" title={problem.problem_id}>P-{shortId(problem.problem_id)}</span>
                    </span>
                    <span className="s04-pair-summary s04-pair-summary--problem">{problem.definition}</span>
                    <span className="s04-pair-summary s04-pair-summary--suggestion">{suggestionSlot}</span>
                  </button>
                  {isOpen && (
                    <div className="s04-pair-body">
                      <div className="s04-pair-block">
                        <span>问题</span>
                        <p>{problem.definition}</p>
                      </div>
                      <div className="s04-pair-block">
                        <span>建议</span>
                        <p className={pending ? 's04-pair-pending' : undefined}>{suggestionSlot}</p>
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ol>
          {frozen && (
            <div className="s04-freeze-block">
              <p className="s04-freeze-record">确认人：{target.confirmed_by} · {formatDate(target.confirmed_at)}<br />锁定人：{target.frozen_by} · {formatDate(target.frozen_at)} · V{target.version}</p>
              <button className="s04-outline-action" type="button" onClick={onExportValidationCases} disabled={busy}>{pendingAction === 'export' ? '正在导出…' : '导出验证案例 JSON'}</button>
            </div>
          )}
        </section>
      </div>

      <footer className="s04-action-rail">
        <p role={actionError ? 'alert' : 'status'}>{actionError ?? (frozen ? '验证计划已确认锁定，可继续进入候选版本验证。' : '确认时自动保存目标并锁定版本级验证计划。')}</p>
        <div className="s04-rail-fields">
          {frozen ? (
            <span className="s04-rail-operator">操作人 {target.frozen_by ?? '—'}</span>
          ) : (
            <label className="s04-rail-field"><span>操作人（必填）</span><input value={actor} onChange={(event) => onActorChange(event.target.value)} disabled={busy} /></label>
          )}
          <button type="button" onClick={onEnterValidation} disabled={busy || !canEnter}>{pendingAction === 'complete' ? '正在保存并锁定…' : frozen ? '进入候选版本验证' : '确认并锁定验证计划'}</button>
        </div>
      </footer>
    </section>
  )
}

function TargetPlanPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const runId = searchParams.get('run_id')?.trim() ?? ''
  const problemId = searchParams.get('problem_id')?.trim() ?? ''
  const problemIds = parseProblemIds(searchParams.get('problem_ids') ?? problemId)
  const problemIdsParam = serializeProblemIds(problemIds)
  const activeProblemId = problemId || problemIds[0] || ''
  const workflowTargetId = searchParams.get('target_id')?.trim() ?? ''
  const workflowCandidateRunId = searchParams.get('candidate_run_id')?.trim() ?? ''
  const workflowValidationTaskId = searchParams.get('validation_task_id')?.trim() ?? ''
  const requestKey = `${runId}:${problemIdsParam}`
  const [loadResult, setLoadResult] = useState<{
    requestKey: string
    state: PageState
  }>(() => ({
    requestKey,
    state: runId && problemIdsParam ? { kind: 'loading' } : { kind: 'missing_parameters' },
  }))
  const [form, setForm] = useState<TargetForm>(emptyForm)
  const [actor, setActor] = useState('')
  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [suggestionGeneration, setSuggestionGeneration] = useState<SuggestionGenerationState>(idleSuggestionGeneration)
  const attemptedSuggestionTargetIdsRef = useRef<Set<string>>(new Set())
  const draftTargetCreationRef = useRef<Map<string, Promise<OptimizationTarget>>>(new Map())

  function ensureDraftTarget(
    creationKey: string,
    runId: string,
    requestedProblemIds: string[],
    selectedProblems: Problem[],
  ): Promise<OptimizationTarget> {
    const inFlight = draftTargetCreationRef.current.get(creationKey)
    if (inFlight) return inFlight
    const creation = createProblemSetOptimizationTarget(
      runId,
      requestedProblemIds,
      { target: defaultTargetInput(selectedProblems) },
    )
      .catch(async (error) => {
        if (error instanceof ApiRequestError && error.code === 'optimization_target_already_exists') {
          const targets = await getOptimizationTargets(runId)
          const existingTarget = targets
            .filter((item) => haveSameProblemIds(item.problem_ids, requestedProblemIds))
            .sort((left, right) => right.version - left.version)[0] ?? null
          if (existingTarget) return existingTarget
        }
        throw error
      })
      .finally(() => { draftTargetCreationRef.current.delete(creationKey) })
    draftTargetCreationRef.current.set(creationKey, creation)
    return creation
  }

  useEffect(() => {
    if (!runId || !problemIdsParam) return

    const controller = new AbortController()
    async function load() {
      try {
        const run = await getEvaluationRun(runId, controller.signal)
        const [dataset, conversations, problems, targets, runs] = await Promise.all([
          getDatasetDetail(run.dataset_id, controller.signal),
          getDatasetConversations(run.dataset_id, controller.signal),
          getProblems(run.id, controller.signal),
          getOptimizationTargets(run.id, controller.signal),
          getDatasetEvaluationRuns(run.dataset_id, controller.signal),
        ])
        const requestedProblemIds = parseProblemIds(problemIdsParam)
        const selectedProblems = requestedProblemIds
          .map((selectedProblemId) => problems.find(
            (problem) => problem.problem_id === selectedProblemId,
          ))
          .filter((problem): problem is Problem => problem !== undefined)
        if (selectedProblems.length !== requestedProblemIds.length) {
          setLoadResult({ requestKey, state: { kind: 'problem_not_found' } })
          return
        }
        const activeProblem = problems.find(
          (problem) => problem.problem_id === activeProblemId,
        ) ?? selectedProblems[0]
        let target: OptimizationTarget | null = targets
          .filter((item) => haveSameProblemIds(item.problem_ids, requestedProblemIds))
          .sort((left, right) => right.version - left.version)[0] ?? null
        if (target === null) {
          const draft = await ensureDraftTarget(
            requestKey,
            run.id,
            requestedProblemIds,
            selectedProblems,
          )
          if (controller.signal.aborted) return
          target = draft
        }
        const candidateRunId = target
          ? runs.find((item) => item.run_type === 'candidate' && item.target_id === target.id)?.id ?? null
          : null
        if (workflowTargetId !== (target?.id ?? '') || workflowCandidateRunId !== (candidateRunId ?? '')) {
          const params = new URLSearchParams({
            run_id: run.id,
            problem_id: activeProblem.problem_id,
            problem_ids: problemIdsParam,
          })
          if (target) params.set('target_id', target.id)
          if (candidateRunId) params.set('candidate_run_id', candidateRunId)
          if (workflowValidationTaskId && workflowTargetId === target?.id) {
            params.set('validation_task_id', workflowValidationTaskId)
          }
          setSearchParams(params, { replace: true })
        }
        if (target) {
          setForm(formFromTarget(target))
        } else {
          const defaultInput = defaultTargetInput(selectedProblems)
          setForm({
            ...emptyForm,
            definition: defaultInput.definition,
            inclusionCriteria: defaultInput.inclusion_criteria,
            exclusionCriteria: defaultInput.exclusion_criteria,
            expectedObservableChange: defaultInput.expected_observable_change,
          })
        }
        setActor(target?.confirmed_by ?? '')
        setLoadResult({
          requestKey,
          state: {
            kind: 'ready',
            data: {
              run,
              dataset,
              conversations,
              problems: selectedProblems,
              target,
              candidateRunId,
            },
          },
        })
      } catch (error) {
        if (controller.signal.aborted) return
        if (error instanceof ApiRequestError && (error.status === 404 || error.code === 'evaluation_run_not_found')) {
          setLoadResult({ requestKey, state: { kind: 'run_not_found' } })
          return
        }
        setLoadResult({
          requestKey,
          state: {
            kind: 'error',
            message: error instanceof Error ? error.message : '无法加载目标与计划。',
          },
        })
      }
    }
    void load()
    return () => controller.abort()
  }, [activeProblemId, problemIdsParam, requestKey, runId, setSearchParams, workflowCandidateRunId, workflowTargetId, workflowValidationTaskId])

  const pageState: PageState = !runId || !problemIdsParam
    ? { kind: 'missing_parameters' }
    : loadResult.requestKey === requestKey
      ? loadResult.state
      : { kind: 'loading' }

  const target = pageState.kind === 'ready' ? pageState.data.target : null
  const readyData = pageState.kind === 'ready' ? pageState.data : null

  const requestSuggestions = useCallback((readyTarget: OptimizationTarget) => {
    const targetId = readyTarget.id
    attemptedSuggestionTargetIdsRef.current.add(targetId)
    setSuggestionGeneration({ targetId, status: 'generating', suggestions: null, error: null })
    void generateOptimizationTargetSuggestions(targetId)
      .then((response) => {
        setSuggestionGeneration({ targetId, status: 'idle', suggestions: response.suggestions, error: null })
      })
      .catch((error) => {
        setSuggestionGeneration({
          targetId,
          status: 'error',
          suggestions: null,
          error: error instanceof Error ? error.message : '生成系统优化建议失败。',
        })
      })
  }, [])

  useEffect(() => {
    const readyTarget = readyData?.target
    if (!readyTarget || readyTarget.status === 'frozen') return
    if (readyTarget.optimization_suggestions?.length) return
    if (attemptedSuggestionTargetIdsRef.current.has(readyTarget.id)) return
    requestSuggestions(readyTarget)
  }, [readyData, requestSuggestions])

  async function enterValidation() {
    if (pageState.kind !== 'ready' || pendingAction) return
    setPendingAction('complete')
    setActionError(null)
    try {
      const frozen = target?.status === 'frozen' ? target : await completeProblemSetOptimizationTarget(
        runId, parseProblemIds(problemIdsParam), { actor: actor.trim(), target: requestFromForm(form) },
      )
      if (frozen.status !== 'frozen' || !frozen.plan_hash || !frozen.frozen_at) {
        throw new Error('验证计划尚未完成锁定，请重试。')
      }
      const params = new URLSearchParams({
        target_id: frozen.id,
        run_id: runId,
        problem_id: activeProblemId,
        problem_ids: problemIdsParam,
      })
      if (pageState.data.candidateRunId) params.set('candidate_run_id', pageState.data.candidateRunId)
      if (workflowValidationTaskId && workflowTargetId === frozen.id) {
        params.set('validation_task_id', workflowValidationTaskId)
      }
      navigate('/validation?' + params.toString())
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '操作失败。')
    } finally {
      setPendingAction(null)
    }
  }

  async function exportValidationCases() {
    if (pageState.kind !== 'ready' || pageState.data.target?.status !== 'frozen') return
    const { conversations, target: frozenTarget } = pageState.data
    setPendingAction('export')
    setActionError(null)
    try {
      const cases = buildValidationCaseExport(frozenTarget, conversations)
      const url = URL.createObjectURL(new Blob([JSON.stringify(cases, null, 2)], { type: 'application/json' }))
      const link = document.createElement('a')
      link.href = url
      link.download = `validation-cases-${shortId(frozenTarget.id)}.json`
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '验证案例导出失败。')
    } finally {
      setPendingAction(null)
    }
  }

  if (pageState.kind === 'missing_parameters') return <PageMessage title="缺少目标上下文" detail="请从基线分析进入目标与计划。" />
  if (pageState.kind === 'loading') return <PageMessage title="正在加载目标与计划" detail="正在读取问题与优化目标…" />
  if (pageState.kind === 'run_not_found') return <PageMessage title="基线运行不存在" detail={`未找到运行 ${runId}。`} />
  if (pageState.kind === 'problem_not_found') return <PageMessage title="问题不存在" detail="该问题不属于当前基线运行。" />
  if (pageState.kind === 'error') return <PageMessage title="目标与计划加载失败" detail={pageState.message} />

  const { data } = pageState
  return (
    <TargetPlanWorkspace
      data={data}
      form={form}
      actor={actor}
      pendingAction={pendingAction}
      actionError={actionError}
      suggestionGeneration={suggestionGeneration}
      onActorChange={setActor}
      onExportValidationCases={() => { void exportValidationCases() }}
      onEnterValidation={() => { void enterValidation() }}
      onRetrySuggestions={() => {
        if (pageState.kind !== 'ready') return
        const readyTarget = pageState.data.target
        if (!readyTarget || readyTarget.status === 'frozen') return
        requestSuggestions(readyTarget)
      }}
    />
  )
}

export default TargetPlanPage
