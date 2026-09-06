import { useEffect, useMemo, useState } from 'react'
import {
  MdCheckCircle,
  MdError,
  MdHistory,
  MdInfo,
  MdLightbulbOutline,
  MdLockOutline,
  MdPersonOutline,
  MdPsychology,
  MdRadioButtonUnchecked,
  MdRule,
  MdWarningAmber,
} from 'react-icons/md'
import { useNavigate, useSearchParams } from 'react-router-dom'

import {
  ApiRequestError,
  confirmOptimizationHypothesis,
  confirmOptimizationTarget,
  createOptimizationTarget,
  freezeOptimizationTarget,
  getDatasetDetail,
  getDatasetEvaluationRuns,
  getEvaluationRun,
  getOptimizationTargets,
  getProblems,
  patchOptimizationTarget,
  type DatasetDetail,
  type EvaluationRun,
  type OptimizationTarget,
  type OptimizationTargetCreateInput,
  type Problem,
} from '../api'
import './TargetPlanPage.css'

type TargetPlanState = 'pre-freeze' | 'frozen'

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
  policyVersion: string
}

type LoadedData = {
  run: EvaluationRun
  dataset: DatasetDetail
  problem: Problem
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
  policyVersion: '',
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
    policyVersion: target.policy_version ?? '',
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
    policy_version: form.policyVersion.trim() || null,
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

function readSnapshotValue(
  snapshot: Record<string, unknown>,
  key: string,
) {
  const value = snapshot[key]
  return typeof value === 'string' && value.trim() ? value : '未提供'
}

function ContextMetadata({ data }: { data: LoadedData }) {
  return (
    <dl className="s04-metadata s04-metadata--prefreeze">
      <div><dt>数据集</dt><dd>{data.dataset.name} {data.dataset.version}</dd></div>
      <div><dt>Evaluation Run</dt><dd title={data.run.id}>{shortId(data.run.id)} · {data.run.status}</dd></div>
      <div><dt>Target 状态</dt><dd>{data.target ? `${data.target.status} · V${data.target.version}` : '尚未创建'}</dd></div>
    </dl>
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
  dirty: boolean
  pendingAction: string | null
  actionError: string | null
  onFormChange: (field: keyof TargetForm, value: string) => void
  onActorChange: (value: string) => void
  onSave: () => void
  onConfirmTarget: () => void
  onConfirmHypothesis: () => void
  onFreeze: () => void
  onEnterValidation: () => void
}

function TargetPlanWorkspace({
  data,
  form,
  actor,
  dirty,
  pendingAction,
  actionError,
  onFormChange,
  onActorChange,
  onSave,
  onConfirmTarget,
  onConfirmHypothesis,
  onFreeze,
  onEnterValidation,
}: TargetPlanWorkspaceProps) {
  const { problem, target } = data
  const frozen = target?.status === 'frozen'
  const state: TargetPlanState = frozen ? 'frozen' : 'pre-freeze'
  const targetConfirmed = Boolean(target?.confirmed_by && target.confirmed_at)
  const hypothesisConfirmed = Boolean(target?.hypothesis_confirmed_by && target.hypothesis_confirmed_at)
  const requiredTargetFieldsComplete = [form.definition, form.inclusionCriteria, form.exclusionCriteria, form.expectedObservableChange].every((value) => value.trim())
  const freezeReady = Boolean(
    target
      && targetConfirmed
      && hypothesisConfirmed
      && target.target_case_ids.length > 0
      && target.regression_case_ids.length > 0
      && target.policy_version
      && !dirty,
  )
  const busy = pendingAction !== null
  const changeRecords = [
    { scope: '计划变更范围', status: target?.change_status ?? '未创建', detail: target?.change_surface ?? '尚未填写' },
    { scope: '计划变更内容', status: target?.change_status ?? '未创建', detail: target?.planned_change ?? '尚未填写' },
    { scope: 'Guardrails', status: target ? `${target.guardrails.length} 项` : '未创建', detail: target?.guardrails.join('；') || '未声明' },
  ]

  return (
    <section className={`s04-page s04-page--${state}`} aria-label={frozen ? '目标与计划已冻结状态' : '目标与计划冻结前状态'}>
      {frozen ? (
        <div className="s04-frozen-header-status" aria-label="当前状态">
          <span><MdLockOutline aria-hidden="true" />主要状态：验证计划已冻结</span>
          <span><MdInfo aria-hidden="true" />Target V{target.version}</span>
        </div>
      ) : (
        <><div className="s04-header-status" aria-label="当前状态"><span aria-hidden="true" />{target?.status === 'confirmed' ? '确认已完成' : '需要人工确认'}</div><MdLockOutline className="s04-candidate-lock" aria-hidden="true" /></>
      )}

      {frozen && <div className="s04-canvas s04-canvas--frozen-meta"><div className="s04-content"><ContextMetadata data={data} /></div></div>}

      <div className={frozen ? 's04-canvas s04-canvas--frozen' : 's04-canvas'}>
        <div className={frozen ? 's04-content s04-content--frozen' : 's04-content'}>
          {!frozen && <ContextMetadata data={data} />}
          {!frozen && (
            <header className="s04-state">
              <div className="s04-state__title"><span aria-hidden="true" /><h1>{target ? '验证计划待冻结' : '尚未创建 Optimization Target'}</h1></div>
              <dl><div><dt>结论属性:</dt><dd>非最终结论</dd></div><div><dt>当前阻断:</dt><dd>{freezeReady ? '无 · 可冻结验证计划' : '草稿保存及必要确认尚未完成'}</dd></div></dl>
            </header>
          )}

          <div className={frozen ? 's04-sections s04-sections--frozen' : 's04-sections'}>
            <section className={frozen ? 's04-targets s04-targets--frozen' : 's04-targets'} aria-label="目标确认">
              <div className="s04-target-column">
                <h2><MdPsychology aria-hidden="true" />选中 Problem</h2>
                <div className="s04-target-value">{problem.definition}</div>
                <div className="s04-target-tags" aria-label="Problem 信息">
                  <span>{problem.scenario}</span><span title={problem.problem_id}>P-{shortId(problem.problem_id)}</span><span>{problem.affected_case_count} 个受影响案例</span><span className="s04-target-tags__priority">{problem.rank === null ? '不可排名' : `Rank ${problem.rank}`}</span>
                </div>
                <p className="s04-source-note">来自当前 Baseline Run 的正式 Problem，Evidence {problem.evidence.length} 条。</p>
              </div>

              <div className={frozen ? 's04-target-column s04-target-column--frozen-human' : 's04-target-column s04-target-column--human'}>
                <div className="s04-section-heading"><h2><MdPersonOutline aria-hidden="true" />人工 Target Contract</h2><span className={targetConfirmed ? 's04-confirmation-status--complete' : undefined}>{targetConfirmed ? '已确认' : '待人工确认'}</span></div>
                {frozen ? (
                  <><MdCheckCircle className="s04-frozen-confirmed-icon" aria-label="已确认" /><p className="s04-frozen-confirmed-target">{target.definition}</p><div className="s04-frozen-confirmation-meta"><span>确认人：{target.confirmed_by}</span><span>确认时间：{formatDate(target.confirmed_at)}</span></div><dl className="s04-contract-readout"><div><dt>纳入标准</dt><dd>{target.inclusion_criteria}</dd></div><div><dt>排除标准</dt><dd>{target.exclusion_criteria}</dd></div><div><dt>预期可观察变化</dt><dd>{target.expected_observable_change}</dd></div></dl></>
                ) : (
                  <><div className="s04-form-grid"><EditableField label="Target definition" value={form.definition} onChange={(value) => onFormChange('definition', value)} disabled={busy} multiline /><EditableField label="Inclusion criteria" value={form.inclusionCriteria} onChange={(value) => onFormChange('inclusionCriteria', value)} disabled={busy} multiline /><EditableField label="Exclusion criteria" value={form.exclusionCriteria} onChange={(value) => onFormChange('exclusionCriteria', value)} disabled={busy} multiline /><EditableField label="Expected observable change" value={form.expectedObservableChange} onChange={(value) => onFormChange('expectedObservableChange', value)} disabled={busy} multiline /></div><button className="s04-outline-action" type="button" onClick={onConfirmTarget} disabled={!target || dirty || targetConfirmed || !actor.trim() || busy}>{targetConfirmed ? 'Target 已确认' : '确认 Target'}</button>{targetConfirmed && target ? <p className="s04-confirmation-meta">{target.confirmed_by} · {formatDate(target.confirmed_at)}</p> : null}</>
                )}
              </div>
            </section>

            <section className={frozen ? 's04-hypothesis s04-hypothesis--frozen' : 's04-hypothesis'} aria-labelledby="s04-hypothesis-title">
              <div className="s04-section-heading"><h2 id="s04-hypothesis-title"><MdLightbulbOutline aria-hidden="true" />优化假设与计划变更</h2><span className={hypothesisConfirmed ? 's04-confirmation-status--complete' : undefined}>{hypothesisConfirmed ? '已确认 · 不代表已证明根因' : '待确认 · 不代表已证明根因'}</span></div>
              {frozen ? (
                <><p>{target.hypothesis_statement}</p><dl className="s04-contract-readout s04-contract-readout--columns"><div><dt>Change surface</dt><dd>{target.change_surface}</dd></div><div><dt>Planned change</dt><dd>{target.planned_change}</dd></div><div><dt>Hypothesis evidence refs</dt><dd>{target.hypothesis_evidence_refs.join('；') || '未声明'}</dd></div><div><dt>Guardrails</dt><dd>{target.guardrails.join('；') || '未声明'}</dd></div></dl><p className="s04-confirmation-meta">假设确认：{target.hypothesis_confirmed_by} · {formatDate(target.hypothesis_confirmed_at)}</p></>
              ) : (
                <><div className="s04-form-grid s04-form-grid--two-columns"><EditableField label="Hypothesis statement" value={form.hypothesisStatement} onChange={(value) => onFormChange('hypothesisStatement', value)} disabled={busy} multiline /><EditableField label="Hypothesis evidence refs（每行一项）" value={form.hypothesisEvidenceRefs} onChange={(value) => onFormChange('hypothesisEvidenceRefs', value)} disabled={busy} multiline /><EditableField label="Change surface" value={form.changeSurface} onChange={(value) => onFormChange('changeSurface', value)} disabled={busy} /><EditableField label="Planned change" value={form.plannedChange} onChange={(value) => onFormChange('plannedChange', value)} disabled={busy} multiline /><EditableField label="Guardrails（每行一项）" value={form.guardrails} onChange={(value) => onFormChange('guardrails', value)} disabled={busy} multiline /></div><button className="s04-outline-action" type="button" onClick={onConfirmHypothesis} disabled={!target || dirty || !targetConfirmed || hypothesisConfirmed || !actor.trim() || busy}>{hypothesisConfirmed ? '优化假设已确认' : '确认优化假设'}</button>{hypothesisConfirmed && target ? <p className="s04-confirmation-meta">{target.hypothesis_confirmed_by} · {formatDate(target.hypothesis_confirmed_at)}</p> : null}</>
              )}
            </section>

            <section className={frozen ? 's04-changes s04-changes--frozen' : 's04-changes'} aria-labelledby="s04-changes-title">
              <h2 id="s04-changes-title"><MdHistory aria-hidden="true" />计划内容</h2>
              <div className={frozen ? 's04-table-frame s04-table-frame--frozen' : 's04-table-frame'}><table><thead><tr><th>范围</th><th>状态</th><th>真实内容</th></tr></thead><tbody>{changeRecords.map((record) => <tr key={record.scope}><td>{record.scope}</td><td>{record.status}</td><td>{record.detail}</td></tr>)}</tbody></table></div>
            </section>

            {frozen ? (
              <section className="s04-frozen-validation" aria-label="已冻结验证计划">
                <div className="s04-frozen-plan">
                  <header className="s04-frozen-plan__header"><div><h2><MdLockOutline aria-hidden="true" />验证计划</h2><span>原始冻结计划：只读</span></div><div><p><strong>VALIDATION-PLAN-V{target.version}</strong><span title={target.plan_hash ?? undefined}>计划哈希：{target.plan_hash}</span></p></div></header>
                  <p className="s04-frozen-plan__notice">Frozen Target 不可覆盖；本轮不提供创建新版本能力。</p>
                  <div className="s04-frozen-plan__body">
                    <div className="s04-frozen-count"><span>目标案例</span><strong>{target.target_case_ids.length} 个案例</strong></div><div className="s04-frozen-count"><span>回归案例</span><strong>{target.regression_case_ids.length} 个案例</strong></div><div className="s04-frozen-count"><span>Challenge 案例</span><strong>{target.challenge_case_ids.length} 个案例</strong></div>
                    <div className="s04-frozen-capabilities"><div><span>受保护能力</span></div><p>{target.protected_capabilities.length > 0 ? target.protected_capabilities.map((capability) => <span key={capability}>{capability}</span>) : <span>未声明</span>}</p></div>
                    <div className="s04-frozen-config"><span>技术配置</span><ul><li>Judge Contract：{readSnapshotValue(target.evaluation_config_snapshot, 'judge_contract_version')}</li><li>Judge Model：{readSnapshotValue(target.evaluation_config_snapshot, 'judge_model')}</li><li>策略：{target.policy_version}</li><li>基线快照 Problem：<code>{target.baseline_snapshot.problem_id}</code></li></ul></div>
                  </div>
                  <footer className="s04-frozen-plan__footer"><span>冻结人：{target.frozen_by}</span><span>{formatDate(target.frozen_at)}</span></footer>
                </div>
                <aside className="s04-frozen-integrity"><div><h3><MdRule aria-hidden="true" />实验完整性规则</h3><p>Baseline 与 Candidate 必须使用相同的生成机制和运行环境，仅允许声明的计划变更不同。</p><div className="s04-frozen-warning"><MdWarningAmber aria-hidden="true" /><p>本页只恢复真实 Frozen Target；Candidate 暴露与实际变更状态不在 S04 伪造。</p></div></div><footer><span>计划状态</span><strong><MdCheckCircle aria-hidden="true" />{target.status} · hash 已持久化</strong></footer></aside>
              </section>
            ) : (
              <section className="s04-validation" aria-label="验证计划草稿">
                <div className="s04-validation-plan"><h2><MdRule aria-hidden="true" />验证计划草稿</h2><dl className="s04-plan-grid"><div><dt>目标案例</dt><dd>{target ? `${target.target_case_ids.length} 个` : '创建后由系统派生'}</dd></div><div><dt>回归案例</dt><dd>{target ? `${target.regression_case_ids.length} 个` : '创建后由系统派生'}</dd></div><div><dt>Challenge 案例</dt><dd>{target ? `${target.challenge_case_ids.length} 个` : '创建后由系统派生'}</dd></div><div><dt>Baseline Frequency</dt><dd>{target ? `${target.baseline_metric.affected_core_cases}/${target.baseline_metric.core_denominator}` : '创建后快照'}</dd></div><div className="s04-plan-grid__wide"><EditableField label="受保护能力（每行一项）" value={form.protectedCapabilities} onChange={(value) => onFormChange('protectedCapabilities', value)} disabled={busy} multiline /></div><div><EditableField label="Policy version" value={form.policyVersion} onChange={(value) => onFormChange('policyVersion', value)} disabled={busy} placeholder="冻结前必填" /></div><div><dt>Failure Mode</dt><dd>{target?.failure_mode ?? '创建后由系统派生'}</dd></div><div className="s04-plan-grid__wide"><dt>基线快照</dt><dd className="s04-mono-value">{target?.baseline_snapshot.problem_id ?? '创建后由系统派生'}</dd></div><div className="s04-plan-grid__wide"><dt>计划哈希</dt><dd className="s04-plan-pending">冻结成功后由 Backend 生成</dd></div></dl></div>
                <div className="s04-integrity"><h3>实验完整性规则</h3><ul><li className={targetConfirmed ? 's04-integrity__complete' : 's04-integrity__warning'}>{targetConfirmed ? <MdCheckCircle aria-hidden="true" /> : <MdRadioButtonUnchecked aria-hidden="true" />}人工确认 Target：{targetConfirmed ? '已完成' : '未完成'}</li><li className={hypothesisConfirmed ? 's04-integrity__complete' : 's04-integrity__warning'}>{hypothesisConfirmed ? <MdCheckCircle aria-hidden="true" /> : <MdRadioButtonUnchecked aria-hidden="true" />}确认优化假设：{hypothesisConfirmed ? '已完成' : '未完成'}</li><li className={!dirty && target ? 's04-integrity__complete' : 's04-integrity__warning'}>{!dirty && target ? <MdCheckCircle aria-hidden="true" /> : <MdRadioButtonUnchecked aria-hidden="true" />}保存验证计划：{!dirty && target ? '已完成' : '待完成'}</li><li><MdRadioButtonUnchecked aria-hidden="true" />冻结验证计划：未完成</li></ul><p className="s04-lock-note"><MdLockOutline aria-hidden="true" />只有 Backend Freeze Gate 成功后，本页才进入只读 Frozen 状态。</p><p className="s04-warning-note"><MdWarningAmber aria-hidden="true" />修改已确认内容会按 Backend 规则清除相应确认，必须重新确认后再冻结。</p></div>
              </section>
            )}
          </div>
        </div>
      </div>

      {frozen ? (
        <footer className="s04-action-rail s04-action-rail--frozen"><div><strong>验证计划：已冻结</strong><span>真实 plan hash、冻结人和冻结时间已从 Backend 恢复。</span></div><button type="button" onClick={onEnterValidation}>进入候选版本验证</button></footer>
      ) : (
        <footer className="s04-action-rail"><p>{actionError ?? (dirty ? '存在尚未保存的草稿修改。' : '所有状态均来自 Backend。')}</p><div><button className={requiredTargetFieldsComplete && dirty ? 's04-freeze-action--ready' : undefined} type="button" onClick={onSave} disabled={!requiredTargetFieldsComplete || !dirty || busy}>{pendingAction === 'save' ? '保存中…' : target ? '保存草稿' : '创建 Target 草稿'}</button><button className={freezeReady && actor.trim() ? 's04-freeze-action--ready' : undefined} type="button" onClick={onFreeze} disabled={!freezeReady || !actor.trim() || busy}>{pendingAction === 'freeze' ? '冻结中…' : '冻结验证计划'}</button><button type="button" disabled>进入候选版本验证</button></div></footer>
      )}

      <div className={frozen ? 's04-analyst-dock s04-analyst-dock--frozen' : 's04-analyst-dock'}>
        <span className="s04-actor-icon"><MdPersonOutline aria-hidden="true" /></span>
        <div>{frozen ? <><strong>{target.frozen_by}</strong><span>Frozen actor</span></> : <label className="s04-actor-field"><span>操作人</span><input value={actor} onChange={(event) => onActorChange(event.target.value)} placeholder="输入真实 actor" disabled={busy} /></label>}</div>
      </div>
    </section>
  )
}

function TargetPlanPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const runId = searchParams.get('run_id')?.trim() ?? ''
  const problemId = searchParams.get('problem_id')?.trim() ?? ''
  const requestKey = `${runId}:${problemId}`
  const [loadResult, setLoadResult] = useState<{
    requestKey: string
    state: PageState
  }>(() => ({
    requestKey,
    state: runId && problemId ? { kind: 'loading' } : { kind: 'missing_parameters' },
  }))
  const [form, setForm] = useState<TargetForm>(emptyForm)
  const [actor, setActor] = useState('')
  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => {
    if (!runId || !problemId) return

    const controller = new AbortController()
    async function load() {
      try {
        const run = await getEvaluationRun(runId, controller.signal)
        const [dataset, problems, targets, runs] = await Promise.all([
          getDatasetDetail(run.dataset_id, controller.signal),
          getProblems(run.id, controller.signal),
          getOptimizationTargets(run.id, controller.signal),
          getDatasetEvaluationRuns(run.dataset_id, controller.signal),
        ])
        const problem = problems.find((item) => item.problem_id === problemId)
        if (!problem) {
          setLoadResult({ requestKey, state: { kind: 'problem_not_found' } })
          return
        }
        const target = targets.filter((item) => item.problem_id === problem.problem_id).sort((left, right) => right.version - left.version)[0] ?? null
        const candidateRunId = target
          ? runs.find((item) => item.run_type === 'candidate' && item.target_id === target.id)?.id ?? null
          : null
        setForm(target ? formFromTarget(target) : emptyForm)
        setLoadResult({
          requestKey,
          state: { kind: 'ready', data: { run, dataset, problem, target, candidateRunId } },
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
            message: error instanceof Error ? error.message : '无法加载 Target 与 Plan。',
          },
        })
      }
    }
    void load()
    return () => controller.abort()
  }, [problemId, requestKey, runId])

  const pageState: PageState = !runId || !problemId
    ? { kind: 'missing_parameters' }
    : loadResult.requestKey === requestKey
      ? loadResult.state
      : { kind: 'loading' }

  const target = pageState.kind === 'ready' ? pageState.data.target : null
  const dirty = useMemo(() => JSON.stringify(form) !== JSON.stringify(target ? formFromTarget(target) : emptyForm), [form, target])

  function updateLoadedTarget(nextTarget: OptimizationTarget) {
    setLoadResult((current) => current.requestKey === requestKey
      && current.state.kind === 'ready'
      ? {
          requestKey,
          state: {
            kind: 'ready',
            data: { ...current.state.data, target: nextTarget },
          },
        }
      : current)
    setForm(formFromTarget(nextTarget))
  }

  async function runAction(name: string, action: () => Promise<OptimizationTarget>) {
    setPendingAction(name)
    setActionError(null)
    try {
      updateLoadedTarget(await action())
    } catch (error) {
      const message = error instanceof Error ? error.message : '操作失败。'
      const code = error instanceof ApiRequestError ? ` (${error.code})` : ''
      setActionError(`${message}${code}`)
    } finally {
      setPendingAction(null)
    }
  }

  if (pageState.kind === 'missing_parameters') return <PageMessage title="缺少 Target 上下文" detail="请从 S03 使用 run_id 与 problem_id 进入目标与计划。" />
  if (pageState.kind === 'loading') return <PageMessage title="正在加载目标与计划" detail="正在读取真实 Problem 与 OptimizationTarget…" />
  if (pageState.kind === 'run_not_found') return <PageMessage title="Evaluation Run 不存在" detail={`未找到 run_id=${runId}。`} />
  if (pageState.kind === 'problem_not_found') return <PageMessage title="Problem 不存在" detail="该 Problem 不属于当前 Evaluation Run。" />
  if (pageState.kind === 'error') return <PageMessage title="目标与计划加载失败" detail={pageState.message} />

  const { data } = pageState
  return (
    <TargetPlanWorkspace
      data={data}
      form={form}
      actor={actor}
      dirty={dirty}
      pendingAction={pendingAction}
      actionError={actionError}
      onFormChange={(field, value) => { setForm((current) => ({ ...current, [field]: value })); setActionError(null) }}
      onActorChange={setActor}
      onSave={() => { const request = requestFromForm(form); void runAction('save', () => target ? patchOptimizationTarget(target.id, request) : createOptimizationTarget(runId, problemId, request)) }}
      onConfirmTarget={() => { if (target) void runAction('confirm-target', () => confirmOptimizationTarget(target.id, actor.trim())) }}
      onConfirmHypothesis={() => { if (target) void runAction('confirm-hypothesis', () => confirmOptimizationHypothesis(target.id, actor.trim())) }}
      onFreeze={() => { if (target) void runAction('freeze', () => freezeOptimizationTarget(target.id, actor.trim())) }}
      onEnterValidation={() => {
        if (!target) return
        const params = new URLSearchParams({ target_id: target.id })
        if (data.candidateRunId) params.set('candidate_run_id', data.candidateRunId)
        navigate(`/validation?${params.toString()}`)
      }}
    />
  )
}

export default TargetPlanPage
