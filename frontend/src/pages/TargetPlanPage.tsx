import { useEffect, useMemo, useState } from 'react'
import {
  MdCheckCircle,
  MdError,
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

const failureModeLabels: Record<OptimizationTarget['failure_mode'], string> = {
  incorrect_information: '信息错误',
  incomplete_unresolved: '回答不完整或问题未解决',
  intent_relevance_failure: '意图理解或相关性不足',
  improper_refusal: '不当拒答',
  policy_procedure_violation: '政策或流程违规',
  other: '其他问题',
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
      <div><dt>基线运行</dt><dd title={data.run.id}>{shortId(data.run.id)} · {evaluationRunStatusLabels[data.run.status]}</dd></div>
      <div><dt>目标状态</dt><dd>{data.target ? `${targetStatusLabels[data.target.status]} · V${data.target.version}` : '尚未创建'}</dd></div>
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
  const requiredHypothesisFieldsComplete = [form.hypothesisStatement, form.changeSurface, form.plannedChange].every((value) => value.trim())
  const formRequest = requestFromForm(form)
  const targetFieldsDirty = Boolean(target && (
    target.definition !== formRequest.definition
    || target.inclusion_criteria !== formRequest.inclusion_criteria
    || target.exclusion_criteria !== formRequest.exclusion_criteria
    || target.expected_observable_change !== formRequest.expected_observable_change
  ))
  const hypothesisFieldsDirty = Boolean(target && (
    target.hypothesis_statement !== formRequest.hypothesis_statement
    || JSON.stringify(target.hypothesis_evidence_refs) !== JSON.stringify(formRequest.hypothesis_evidence_refs)
    || target.change_surface !== formRequest.change_surface
    || target.planned_change !== formRequest.planned_change
    || JSON.stringify(target.guardrails) !== JSON.stringify(formRequest.guardrails)
  ))
  const targetConfirmationComplete = targetConfirmed && !targetFieldsDirty
  const hypothesisConfirmationComplete = hypothesisConfirmed && targetConfirmationComplete && !hypothesisFieldsDirty
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
  const targetConfirmationBlocker = !target
    ? '请先创建优化目标草稿。'
    : !requiredTargetFieldsComplete
      ? '请完整填写目标定义、纳入标准、排除标准和预期可观察变化。'
      : !actor.trim()
        ? '请先填写操作人。'
        : busy
          ? '请等待当前操作完成。'
          : null
  const hypothesisConfirmationBlocker = !target
    ? '请先创建优化目标草稿。'
    : !targetConfirmationComplete
      ? targetFieldsDirty ? '目标内容已修改，请先重新确认优化目标。' : '请先确认优化目标。'
      : !requiredHypothesisFieldsComplete
        ? '请完整填写假设说明、变更范围和计划变更。'
        : !actor.trim()
          ? '请先填写操作人。'
          : busy
            ? '请等待当前操作完成。'
            : null
  const freezeBlockers: string[] = []
  if (!target) freezeBlockers.push('请先创建优化目标草稿。')
  if (dirty) freezeBlockers.push('请先保存最新验证计划。')
  if (target && !targetConfirmed) freezeBlockers.push('请先确认优化目标。')
  if (target && !hypothesisConfirmed) freezeBlockers.push('请先确认优化假设。')
  if (target && target.target_case_ids.length === 0) freezeBlockers.push('当前问题没有可用的目标案例。')
  if (target && target.regression_case_ids.length === 0) freezeBlockers.push('当前数据集没有可用的回归案例。')
  if (!form.policyVersion.trim()) freezeBlockers.push('请填写验证规则。')
  if (!actor.trim()) freezeBlockers.push('请填写操作人。')
  const saveBlocker = !requiredTargetFieldsComplete
    ? '请完整填写优化目标的四个必填项。'
    : !dirty
      ? '当前草稿已保存。'
      : null
  const actionHint = actionError
    ?? (!target
      ? saveBlocker ?? freezeBlockers[0]
      : dirty && saveBlocker
        ? saveBlocker
        : freezeBlockers[0] ?? saveBlocker ?? '可以冻结验证计划。')

  return (
    <section className={`s04-page s04-page--${state}`} aria-label={frozen ? '目标与计划已冻结状态' : '目标与计划冻结前状态'}>
      {frozen ? (
        <div className="s04-frozen-header-status" aria-label="当前状态">
          <span><MdLockOutline aria-hidden="true" />主要状态：验证计划已冻结</span>
          <span><MdInfo aria-hidden="true" />目标 V{target.version}</span>
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
              <div className="s04-state__title"><span aria-hidden="true" /><h1>{target ? '验证计划待冻结' : '尚未创建优化目标'}</h1></div>
              <dl><div><dt>结论属性:</dt><dd>非最终结论</dd></div><div><dt>当前阻断:</dt><dd>{freezeReady && actor.trim() ? '无 · 可冻结验证计划' : freezeBlockers[0]}</dd></div></dl>
            </header>
          )}

          <div className={frozen ? 's04-sections s04-sections--frozen' : 's04-sections'}>
            <section className={frozen ? 's04-targets s04-targets--frozen' : 's04-targets'} aria-label="目标确认">
              <div className="s04-target-column">
                <h2><MdPsychology aria-hidden="true" />问题依据</h2>
                <div className="s04-target-value">{problem.definition}</div>
                <div className="s04-target-tags" aria-label="问题信息">
                  <span>{problem.scenario}</span><span title={problem.problem_id}>P-{shortId(problem.problem_id)}</span><span>{problem.affected_case_count} 个受影响案例</span><span className="s04-target-tags__priority">{problem.rank === null ? '不可排名' : `排名 ${problem.rank}`}</span>
                </div>
                <p className="s04-source-note">关联证据 {problem.evidence.length} 条</p>
              </div>

              <div className={frozen ? 's04-target-column s04-target-column--frozen-human' : 's04-target-column s04-target-column--human'}>
                <div className="s04-section-heading"><h2><MdPersonOutline aria-hidden="true" />优化目标</h2><span className={targetConfirmationComplete ? 's04-confirmation-status--complete' : undefined}>{targetConfirmationComplete ? '已确认' : targetConfirmed ? '内容已修改 · 待重新确认' : '待人工确认'}</span></div>
                {frozen ? (
                  <><MdCheckCircle className="s04-frozen-confirmed-icon" aria-label="已确认" /><p className="s04-frozen-confirmed-target">{target.definition}</p><div className="s04-frozen-confirmation-meta"><span>确认人：{target.confirmed_by}</span><span>确认时间：{formatDate(target.confirmed_at)}</span></div><dl className="s04-contract-readout"><div><dt>纳入标准</dt><dd>{target.inclusion_criteria}</dd></div><div><dt>排除标准</dt><dd>{target.exclusion_criteria}</dd></div><div><dt>预期可观察变化</dt><dd>{target.expected_observable_change}</dd></div></dl></>
                ) : (
                  <><div className="s04-form-grid"><EditableField label="目标定义" value={form.definition} onChange={(value) => onFormChange('definition', value)} disabled={busy} multiline /><EditableField label="纳入标准" value={form.inclusionCriteria} onChange={(value) => onFormChange('inclusionCriteria', value)} disabled={busy} multiline /><EditableField label="排除标准" value={form.exclusionCriteria} onChange={(value) => onFormChange('exclusionCriteria', value)} disabled={busy} multiline /><EditableField label="预期可观察变化" value={form.expectedObservableChange} onChange={(value) => onFormChange('expectedObservableChange', value)} disabled={busy} multiline /></div><button className="s04-outline-action" type="button" title={targetConfirmationBlocker ?? undefined} onClick={onConfirmTarget} disabled={targetConfirmationComplete || Boolean(targetConfirmationBlocker)}>{targetConfirmationComplete ? '优化目标已确认' : targetConfirmed ? '重新确认优化目标' : '确认优化目标'}</button>{targetConfirmationBlocker && !targetConfirmationComplete ? <p className="s04-confirmation-meta s04-confirmation-blocker">{targetConfirmationBlocker}</p> : null}{targetConfirmationComplete && target ? <p className="s04-confirmation-meta">确认人：{target.confirmed_by} · {formatDate(target.confirmed_at)}</p> : null}</>
                )}
              </div>
            </section>

            <section className={frozen ? 's04-hypothesis s04-hypothesis--frozen' : 's04-hypothesis'} aria-labelledby="s04-hypothesis-title">
              <div className="s04-section-heading"><h2 id="s04-hypothesis-title"><MdLightbulbOutline aria-hidden="true" />优化假设</h2><span className={hypothesisConfirmationComplete ? 's04-confirmation-status--complete' : undefined}>{hypothesisConfirmationComplete ? '已确认 · 不代表已证明根因' : hypothesisConfirmed ? '内容已修改 · 待重新确认' : '待确认 · 不代表已证明根因'}</span></div>
              {frozen ? (
                <><p>{target.hypothesis_statement}</p><dl className="s04-contract-readout"><div><dt>假设证据引用</dt><dd>{target.hypothesis_evidence_refs.join('；') || '未声明'}</dd></div></dl><h3 className="s04-subsection-heading">计划变更</h3><dl className="s04-contract-readout s04-contract-readout--columns"><div><dt>变更范围</dt><dd>{target.change_surface}</dd></div><div><dt>计划变更</dt><dd>{target.planned_change}</dd></div><div><dt>保护规则</dt><dd>{target.guardrails.join('；') || '未声明'}</dd></div></dl><p className="s04-confirmation-meta">确认人：{target.hypothesis_confirmed_by} · {formatDate(target.hypothesis_confirmed_at)}</p></>
              ) : (
                <><div className="s04-form-grid s04-form-grid--two-columns"><EditableField label="假设说明" value={form.hypothesisStatement} onChange={(value) => onFormChange('hypothesisStatement', value)} disabled={busy} multiline /><EditableField label="假设证据引用（每行一项）" value={form.hypothesisEvidenceRefs} onChange={(value) => onFormChange('hypothesisEvidenceRefs', value)} disabled={busy} multiline /></div><h3 className="s04-subsection-heading">计划变更</h3><div className="s04-form-grid s04-form-grid--two-columns"><EditableField label="变更范围" value={form.changeSurface} onChange={(value) => onFormChange('changeSurface', value)} disabled={busy} /><EditableField label="计划变更" value={form.plannedChange} onChange={(value) => onFormChange('plannedChange', value)} disabled={busy} multiline /><EditableField label="保护规则（每行一项）" value={form.guardrails} onChange={(value) => onFormChange('guardrails', value)} disabled={busy} multiline /></div><button className="s04-outline-action" type="button" title={hypothesisConfirmationBlocker ?? undefined} onClick={onConfirmHypothesis} disabled={hypothesisConfirmationComplete || Boolean(hypothesisConfirmationBlocker)}>{hypothesisConfirmationComplete ? '优化假设已确认' : hypothesisConfirmed ? '重新确认优化假设' : '确认优化假设'}</button>{hypothesisConfirmationBlocker && !hypothesisConfirmationComplete ? <p className="s04-confirmation-meta s04-confirmation-blocker">{hypothesisConfirmationBlocker}</p> : null}{hypothesisConfirmationComplete && target ? <p className="s04-confirmation-meta">确认人：{target.hypothesis_confirmed_by} · {formatDate(target.hypothesis_confirmed_at)}</p> : null}</>
              )}
            </section>

            {frozen ? (
              <section className="s04-frozen-validation" aria-label="已冻结验证计划">
                <div className="s04-frozen-plan">
                  <header className="s04-frozen-plan__header"><div><h2><MdLockOutline aria-hidden="true" />验证计划</h2><span>已冻结 · 只读</span></div><div><p><strong>验证计划 V{target.version}</strong><span title={target.plan_hash ?? undefined}>计划已锁定</span></p></div></header>
                  <p className="s04-frozen-plan__notice">冻结后计划不可修改。</p>
                  <div className="s04-frozen-plan__body">
                    <div className="s04-frozen-count"><span>目标案例</span><strong>{target.target_case_ids.length} 个案例</strong></div><div className="s04-frozen-count"><span>回归案例</span><strong>{target.regression_case_ids.length} 个案例</strong></div><div className="s04-frozen-count"><span>挑战案例</span><strong>{target.challenge_case_ids.length} 个案例</strong></div>
                    <div className="s04-frozen-capabilities"><div><span>需保护的现有能力（可选）</span></div><p>{target.protected_capabilities.length > 0 ? target.protected_capabilities.map((capability) => <span key={capability}>{capability}</span>) : <span>未声明</span>}</p></div>
                    <div className="s04-frozen-config"><span>技术详情</span><ul><li>评审规则版本：{readSnapshotValue(target.evaluation_config_snapshot, 'judge_contract_version')}</li><li>评审模型：{readSnapshotValue(target.evaluation_config_snapshot, 'judge_model')}</li><li>验证规则：{target.policy_version}</li><li>失败模式：{failureModeLabels[target.failure_mode]}</li><li>基线快照问题：<code>{target.baseline_snapshot.problem_id}</code></li><li>计划标识：<code>{target.plan_hash}</code></li></ul></div>
                  </div>
                  <footer className="s04-frozen-plan__footer"><span>确认人：{target.frozen_by}</span><span>{formatDate(target.frozen_at)}</span></footer>
                </div>
                <aside className="s04-frozen-integrity"><div><h3><MdRule aria-hidden="true" />冻结确认</h3><p>基线与候选版本必须使用相同的生成机制和运行环境，仅允许声明的计划变更不同。</p><div className="s04-frozen-warning"><MdWarningAmber aria-hidden="true" /><p>候选版本的实际变更将在下一步验证。</p></div></div><footer><span>计划状态</span><strong title={target.plan_hash ?? undefined}><MdCheckCircle aria-hidden="true" />计划已锁定</strong></footer></aside>
              </section>
            ) : (
              <section className="s04-validation" aria-label="验证计划草稿">
                <div className="s04-validation-plan"><h2><MdRule aria-hidden="true" />验证计划</h2><dl className="s04-plan-grid"><div><dt>目标案例</dt><dd>{target ? `${target.target_case_ids.length} 个` : '创建后由系统派生'}</dd></div><div><dt>回归案例</dt><dd>{target ? `${target.regression_case_ids.length} 个` : '创建后由系统派生'}</dd></div><div><dt>挑战案例</dt><dd>{target ? `${target.challenge_case_ids.length} 个` : '创建后由系统派生'}</dd></div><div><dt>基线频次</dt><dd>{target ? `${target.baseline_metric.affected_core_cases}/${target.baseline_metric.core_denominator}` : '创建后生成'}</dd></div><div className="s04-plan-grid__wide"><EditableField label="需保护的现有能力（可选）" value={form.protectedCapabilities} onChange={(value) => onFormChange('protectedCapabilities', value)} disabled={busy} multiline /></div><div><EditableField label="验证规则（冻结前必填）" value={form.policyVersion} onChange={(value) => onFormChange('policyVersion', value)} disabled={busy} placeholder="请输入验证规则" /></div><div><dt>失败模式</dt><dd>{target ? failureModeLabels[target.failure_mode] : '创建后生成'}</dd></div></dl></div>
                <div className="s04-integrity"><h3>冻结确认</h3><ul><li className={targetConfirmationComplete ? 's04-integrity__complete' : 's04-integrity__warning'}>{targetConfirmationComplete ? <MdCheckCircle aria-hidden="true" /> : <MdRadioButtonUnchecked aria-hidden="true" />}确认优化目标：{targetConfirmationComplete ? '已完成' : '未完成'}</li><li className={hypothesisConfirmationComplete ? 's04-integrity__complete' : 's04-integrity__warning'}>{hypothesisConfirmationComplete ? <MdCheckCircle aria-hidden="true" /> : <MdRadioButtonUnchecked aria-hidden="true" />}确认优化假设：{hypothesisConfirmationComplete ? '已完成' : '未完成'}</li><li className={!dirty && target ? 's04-integrity__complete' : 's04-integrity__warning'}>{!dirty && target ? <MdCheckCircle aria-hidden="true" /> : <MdRadioButtonUnchecked aria-hidden="true" />}保存验证计划：{!dirty && target ? '已完成' : '待完成'}</li><li><MdRadioButtonUnchecked aria-hidden="true" />冻结验证计划：未完成</li></ul><p className="s04-lock-note"><MdLockOutline aria-hidden="true" />完成必要确认并保存后，方可冻结验证计划。</p><p className="s04-warning-note"><MdWarningAmber aria-hidden="true" />修改已确认内容后，需要重新确认再冻结。</p></div>
              </section>
            )}
          </div>
        </div>
      </div>

      {frozen ? (
        <footer className="s04-action-rail s04-action-rail--frozen"><div><strong>验证计划：已冻结</strong><span>计划已锁定，冻结信息已保存。</span></div><button type="button" onClick={onEnterValidation}>进入候选版本验证</button></footer>
      ) : (
        <footer className="s04-action-rail"><p>{actionHint}</p><div><button className={requiredTargetFieldsComplete && dirty ? 's04-freeze-action--ready' : undefined} type="button" title={saveBlocker ?? undefined} onClick={onSave} disabled={!requiredTargetFieldsComplete || !dirty || busy}>{pendingAction === 'save' ? '保存中…' : target ? '保存草稿' : '创建优化目标草稿'}</button><button className={freezeReady && actor.trim() ? 's04-freeze-action--ready' : undefined} type="button" title={freezeBlockers[0]} onClick={onFreeze} disabled={!freezeReady || !actor.trim() || busy}>{pendingAction === 'freeze' ? '冻结中…' : '冻结验证计划'}</button><button type="button" disabled>进入候选版本验证</button></div></footer>
      )}

      <div className={frozen ? 's04-analyst-dock s04-analyst-dock--frozen' : 's04-analyst-dock'}>
        <span className="s04-actor-icon"><MdPersonOutline aria-hidden="true" /></span>
        <div>{frozen ? <><strong>{target.frozen_by}</strong><span>确认人</span></> : <label className="s04-actor-field"><span>操作人</span><input value={actor} onChange={(event) => onActorChange(event.target.value)} placeholder="请输入姓名" disabled={busy} /></label>}</div>
      </div>
    </section>
  )
}

function TargetPlanPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const runId = searchParams.get('run_id')?.trim() ?? ''
  const problemId = searchParams.get('problem_id')?.trim() ?? ''
  const workflowTargetId = searchParams.get('target_id')?.trim() ?? ''
  const workflowCandidateRunId = searchParams.get('candidate_run_id')?.trim() ?? ''
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
        if (workflowTargetId !== (target?.id ?? '') || workflowCandidateRunId !== (candidateRunId ?? '')) {
          const params = new URLSearchParams({ run_id: run.id, problem_id: problem.problem_id })
          if (target) params.set('target_id', target.id)
          if (candidateRunId) params.set('candidate_run_id', candidateRunId)
          setSearchParams(params, { replace: true })
        }
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
            message: error instanceof Error ? error.message : '无法加载目标与计划。',
          },
        })
      }
    }
    void load()
    return () => controller.abort()
  }, [problemId, requestKey, runId, setSearchParams, workflowCandidateRunId, workflowTargetId])

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
    const params = new URLSearchParams({
      run_id: runId,
      problem_id: problemId,
      target_id: nextTarget.id,
    })
    if (workflowCandidateRunId) params.set('candidate_run_id', workflowCandidateRunId)
    setSearchParams(params, { replace: true })
  }

  async function runAction(name: string, action: () => Promise<OptimizationTarget>) {
    setPendingAction(name)
    setActionError(null)
    try {
      updateLoadedTarget(await action())
    } catch (error) {
      const message = error instanceof Error ? error.message : '操作失败。'
      setActionError(message)
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
      dirty={dirty}
      pendingAction={pendingAction}
      actionError={actionError}
      onFormChange={(field, value) => { setForm((current) => ({ ...current, [field]: value })); setActionError(null) }}
      onActorChange={setActor}
      onSave={() => { const request = requestFromForm(form); void runAction('save', () => target ? patchOptimizationTarget(target.id, request) : createOptimizationTarget(runId, problemId, request)) }}
      onConfirmTarget={() => {
        if (!target) return
        void runAction('confirm-target', async () => {
          const savedTarget = dirty ? await patchOptimizationTarget(target.id, requestFromForm(form)) : target
          if (dirty) updateLoadedTarget(savedTarget)
          return confirmOptimizationTarget(savedTarget.id, actor.trim())
        })
      }}
      onConfirmHypothesis={() => {
        if (!target) return
        void runAction('confirm-hypothesis', async () => {
          const savedTarget = dirty ? await patchOptimizationTarget(target.id, requestFromForm(form)) : target
          if (dirty) updateLoadedTarget(savedTarget)
          return confirmOptimizationHypothesis(savedTarget.id, actor.trim())
        })
      }}
      onFreeze={() => { if (target) void runAction('freeze', () => freezeOptimizationTarget(target.id, actor.trim())) }}
      onEnterValidation={() => {
        if (!target) return
        const params = new URLSearchParams({
          target_id: target.id,
          run_id: data.run.id,
          problem_id: data.problem.problem_id,
        })
        if (data.candidateRunId) params.set('candidate_run_id', data.candidateRunId)
        navigate(`/validation?${params.toString()}`)
      }}
    />
  )
}

export default TargetPlanPage
