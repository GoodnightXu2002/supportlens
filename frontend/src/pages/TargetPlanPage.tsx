import { useEffect, useState } from 'react'
import { MdError } from 'react-icons/md'
import { useNavigate, useSearchParams } from 'react-router-dom'

import {
  ApiRequestError,
  completeProblemSetOptimizationTarget,
  getDatasetConversations,
  getDatasetDetail,
  getDatasetEvaluationRuns,
  getEvaluationRun,
  getOptimizationTargets,
  getProblems,
  type DatasetDetail,
  type DatasetConversation,
  type EvaluationRun,
  type OptimizationTarget,
  type OptimizationTargetCreateInput,
  type Problem,
} from '../api'
import {
  haveSameProblemIds,
  parseProblemIds,
  serializeProblemIds,
} from '../baselineTargetGate'
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
  frozen: '已冻结',
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

type EditableFieldProps = {
  label: string
  value: string
  onChange: (value: string) => void
  disabled: boolean
  multiline?: boolean
  placeholder?: string
}

function EditableField({
  label,
  value,
  onChange,
  disabled,
  multiline = false,
  placeholder,
}: EditableFieldProps) {
  return (
    <label className="s04-form-field">
      <span>{label}</span>
      {multiline ? (
        <textarea value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} placeholder={placeholder} rows={3} />
      ) : (
        <input value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} placeholder={placeholder} />
      )}
    </label>
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
  onFormChange: (field: keyof TargetForm, value: string) => void
  onActorChange: (value: string) => void
  onExportValidationCases: () => void
  onEnterValidation: () => void
}

function TargetPlanWorkspace({ data, form, actor, pendingAction, actionError,
  onFormChange, onActorChange, onExportValidationCases, onEnterValidation,
}: TargetPlanWorkspaceProps) {
  const { problems, target } = data
  const frozen = target?.status === 'frozen'
  const busy = pendingAction !== null
  const scope = validationScope(problems, data.conversations)
  const targetCaseCount = target?.target_case_ids.length ?? scope.targetCaseIds.length
  const regressionCaseCount = target?.regression_case_ids.length ?? scope.regressionCaseIds.length
  const challengeCaseCount = target?.challenge_case_ids.length ?? scope.challengeCaseIds.length
  const missingCases = targetCaseCount === 0
  const requiredFields = [form.definition, form.inclusionCriteria, form.exclusionCriteria, form.expectedObservableChange]
  const canEnter = frozen || (requiredFields.every((value) => value.trim()) && actor.trim() && !missingCases)
  const notes: [keyof TargetForm, string][] = [
    ['hypothesisStatement', '优化假设'], ['plannedChange', '计划变更'],
    ['changeSurface', '变更范围'], ['hypothesisEvidenceRefs', '证据引用（每行一项）'],
    ['guardrails', '保护规则（每行一项）'], ['protectedCapabilities', '需保护的现有能力（每行一项）'],
  ]
  return (
    <section className="s04-page">
      <ContextMetadata data={data} form={form} />

      <div className="s04-workspace">
        <section className="s04-pane" aria-labelledby="s04-evidence-title">
          <header className="s04-pane-header"><h2 id="s04-evidence-title">证据</h2></header>
          <div className="s04-pane-scroll">
            <section className="s04-section" aria-labelledby="s04-problem-title">
              <h2 id="s04-problem-title">本轮优化问题：{problems.length} 个</h2>
              <ul className="s04-problem-list">
                {problems.map((problem) => (
                  <li className="s04-problem-card" key={problem.problem_id}>
                    <span className="s04-code-label" title={problem.problem_id}>
                      {problem.scenario} · P-{shortId(problem.problem_id)}
                    </span>
                    <p>{problem.definition}</p>
                  </li>
                ))}
              </ul>
            </section>

            <section className="s04-section" aria-labelledby="s04-scope-title">
              <h2 id="s04-scope-title">验证范围</h2>
              <dl className="s04-plan-grid">
                <div><dt>目标案例</dt><dd className="s04-scope-count">{targetCaseCount} 个</dd><dd className="s04-scope-desc">所选问题涉及的核心案例去重并集</dd></div>
                <div><dt>回归案例</dt><dd className="s04-scope-count">{regressionCaseCount} 个</dd><dd className="s04-scope-desc">其余核心案例，用于检查现有表现</dd></div>
                <div><dt>挑战案例</dt><dd className="s04-scope-count">{challengeCaseCount} 个</dd><dd className="s04-scope-desc">数据集中的全部挑战案例</dd></div>
              </dl>
              <div className="s04-criteria">
                <div><span>纳入标准</span><p>{form.inclusionCriteria}</p></div>
                <div><span>排除标准</span><p>{form.exclusionCriteria}</p></div>
              </div>
              {missingCases && <p className="s04-alert" role="alert">所选问题缺少目标案例。</p>}
              {frozen && (
                <>
                  <p className="s04-freeze-record">确认人：{target.confirmed_by} · {formatDate(target.confirmed_at)}<br />冻结人：{target.frozen_by} · {formatDate(target.frozen_at)} · V{target.version}</p>
                  <button className="s04-outline-action" type="button" onClick={onExportValidationCases} disabled={busy}>{pendingAction === 'export' ? '正在导出…' : '导出验证案例 JSON'}</button>
                </>
              )}
            </section>
          </div>
        </section>

        <section className="s04-pane" aria-labelledby="s04-decision-title">
          <header className="s04-pane-header"><h2 id="s04-decision-title">确认优化目标</h2></header>
          <div className="s04-pane-scroll">
            <section className="s04-section" aria-labelledby="s04-target-title">
              <h2 id="s04-target-title">本轮优化目标</h2>
              <p className="s04-source-note">{frozen ? '目标和验证范围已冻结，可继续验证。' : '系统已建议优化目标，可直接使用或修改。'}</p>
              {frozen ? (
                <>
                  <div className="s04-evidence-field"><span>目标定义</span><p>{form.definition}</p></div>
                  <div className="s04-evidence-field"><span>预期可观察变化</span><p>{form.expectedObservableChange}</p></div>
                </>
              ) : (
                <>
                  <EditableField label="目标定义" value={form.definition} onChange={(value) => onFormChange('definition', value)} disabled={busy} multiline />
                  <EditableField label="预期可观察变化" value={form.expectedObservableChange} onChange={(value) => onFormChange('expectedObservableChange', value)} disabled={busy} multiline />
                </>
              )}
            </section>
            <details className="s04-notes">
              <summary>可选优化备注</summary>
              <div className="s04-form-grid s04-form-grid--two-columns">
                {notes.map(([field, label]) => <EditableField key={field} label={label + '（可选）'} value={form[field]} onChange={(value) => onFormChange(field, value)} disabled={busy || frozen} multiline />)}
              </div>
            </details>
            {frozen ? (
              <div className="s04-evidence-field s04-evidence-field--actor"><span>操作人（必填）</span><p>{target.frozen_by ?? ''}</p></div>
            ) : (
              <div className="s04-actor-field">
                <EditableField label="操作人（必填）" value={actor} onChange={onActorChange} disabled={busy} />
              </div>
            )}
          </div>
        </section>
      </div>

      <footer className="s04-action-rail">
        <p role={actionError ? 'alert' : 'status'}>{actionError ?? (frozen ? '验证计划已冻结，可继续进入候选版本验证。' : '确认时自动保存目标并冻结版本级验证计划。')}</p>
        <button type="button" onClick={onEnterValidation} disabled={busy || !canEnter}>{pendingAction === 'complete' ? '正在保存并冻结…' : frozen ? '进入候选版本验证' : '确认并冻结验证计划'}</button>
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
        const target = targets
          .filter((item) => haveSameProblemIds(item.problem_ids, requestedProblemIds))
          .sort((left, right) => right.version - left.version)[0] ?? null
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
        setForm(target ? formFromTarget(target) : {
          ...emptyForm,
          definition: `改善本轮 ${selectedProblems.length} 个问题：\n${selectedProblems.map((problem) => problem.definition).join('\n')}`,
          inclusionCriteria: '所选 Problems 涉及的核心案例去重并集。',
          exclusionCriteria: '其余核心案例不计入目标案例，并作为回归案例。',
          expectedObservableChange: '减少所选问题在目标案例中的出现，并保持回归案例表现。',
        })
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

  async function enterValidation() {
    if (pageState.kind !== 'ready' || pendingAction) return
    setPendingAction('complete')
    setActionError(null)
    try {
      const frozen = target?.status === 'frozen' ? target : await completeProblemSetOptimizationTarget(
        runId, parseProblemIds(problemIdsParam), { actor: actor.trim(), target: requestFromForm(form) },
      )
      if (frozen.status !== 'frozen' || !frozen.plan_hash || !frozen.frozen_at) {
        throw new Error('验证计划尚未完成冻结，请重试。')
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
      onFormChange={(field, value) => { setForm((current) => ({ ...current, [field]: value })); setActionError(null) }}
      onActorChange={setActor}
      onExportValidationCases={() => { void exportValidationCases() }}
      onEnterValidation={() => { void enterValidation() }}
    />
  )
}

export default TargetPlanPage
