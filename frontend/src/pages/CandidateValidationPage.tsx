import { useEffect, useState } from 'react'
import { MdCheckCircle, MdError, MdVerified } from 'react-icons/md'
import { Link, useSearchParams } from 'react-router-dom'

import {
  API_BASE_URL,
  ApiRequestError,
  createCandidateComparisons,
  createValidationTask,
  getCandidateComparisons,
  getCandidateValidationSummary,
  getDatasetConversations,
  getDatasetDetail,
  getEvaluationRun,
  getFinalEffectiveResults,
  getOptimizationTarget,
  getValidationTask,
  startValidationTaskCandidateValidation,
  submitCandidateFinalDecision,
  type CandidateValidationSummary,
  type CaseComparison,
  type DatasetConversation,
  type DatasetDetail,
  type EvaluationRun,
  type FinalEffectiveResult,
  type JudgeOutput,
  type OptimizationTarget,
  type ValidationTaskReadResponse,
} from '../api'
import {
  blockerLabel,
  failureModeLabel,
  runStatusLabel,
  targetStatusLabel,
} from '../displayLabels'
import {
  buildLocalRunnerCommand,
  withValidationTaskId,
} from '../validationTaskHandoff'
import './CandidateValidationPage.css'

type BaseData = {
  target: OptimizationTarget
  baselineRun: EvaluationRun
  dataset: DatasetDetail
  conversations: DatasetConversation[]
}

type CandidateData = BaseData & {
  candidateRun: EvaluationRun
  baselineResults: FinalEffectiveResult[]
  candidateResults: FinalEffectiveResult[]
  comparisons: CaseComparison[]
  summary: CandidateValidationSummary
}

type PageState =
  | { kind: 'missing_target' }
  | { kind: 'loading' }
  | { kind: 'target_not_found' }
  | { kind: 'candidate_not_found' }
  | { kind: 'task_not_found' }
  | { kind: 'target_not_frozen'; target: OptimizationTarget }
  | { kind: 'error'; message: string }
  | { kind: 'runner_setup'; data: BaseData }
  | { kind: 'runner_task'; data: BaseData; task: ValidationTaskReadResponse }
  | { kind: 'candidate_status'; candidateRun: EvaluationRun }
  | { kind: 'ready'; data: CandidateData }

type ComparisonNodeProps = {
  accent?: boolean
  label: string
  aside?: string
  children: React.ReactNode
}

function ComparisonNode({ accent = false, label, aside, children }: ComparisonNodeProps) {
  return (
    <div className={accent ? 's05-node s05-node--candidate' : 's05-node'}>
      <div className="s05-node__content">
        <div className="s05-node__head">
          <span className="s05-node__label">{label}</span>
          {aside ? <span className="s05-node__aside">{aside}</span> : null}
        </div>
        {children}
      </div>
    </div>
  )
}

function formatDate(value: string | null) {
  if (!value) return '未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function displayValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '未提供'
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

function conversationMetadata(conversation: DatasetConversation, key: string) {
  const metadata = conversation.metadata
  return metadata && key in metadata ? metadata[key] : null
}

function messageContent(conversation: DatasetConversation, role: 'user' | 'assistant') {
  const content = conversation.messages
    .filter((message) => message.role === role)
    .map((message) => message.content)
  return content.length ? content.join('\n\n') : '未提供'
}

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

function JudgeBlock({ result }: { result: JudgeOutput }) {
  return (
    <div className="s05-judge">
      {result.problem ? <p className="s05-judge__problem">{result.problem}</p> : null}
      <p className="s05-judge__rationale">{result.rationale}</p>
    </div>
  )
}

function effectiveOutput(result: FinalEffectiveResult | undefined) {
  if (!result) return null
  return result.final_result ?? result.machine_result
}

function provenanceLine(result: FinalEffectiveResult | undefined) {
  if (!result) return '结果不存在'
  if (!result.human_decision) return '机器判定 · 无人工复核'
  const machine = result.machine_result
  const machineSeverity = machine.severity ? severityLabels[machine.severity] : '无'
  return `人工复核 · ${result.human_decision.reviewer} · ${formatDate(result.human_decision.reviewed_at)} · 机器原始判定 ${judgmentLabels[machine.judgment]} · 严重度 ${machineSeverity}`
}

function verdictColorClass(result: JudgeOutput | null) {
  return result ? `s05-judge__verdict--${result.judgment}` : undefined
}

function VerdictDeltaBar({ baseline, candidate, movement, targetWorse, regressionLevel }: {
  baseline: JudgeOutput | null
  candidate: JudgeOutput | null
  movement: CaseComparison['movement']
  targetWorse: boolean
  regressionLevel: CaseComparison['regression_level']
}) {
  const fields = [
    {
      label: '判定',
      from: baseline ? judgmentLabels[baseline.judgment] : '无',
      to: candidate ? judgmentLabels[candidate.judgment] : '无',
      fromClass: verdictColorClass(baseline),
      toClass: verdictColorClass(candidate),
    },
    {
      label: '严重度',
      from: baseline?.severity ? severityLabels[baseline.severity] : '无',
      to: candidate?.severity ? severityLabels[candidate.severity] : '无',
      fromClass: undefined,
      toClass: undefined,
    },
    {
      label: '失败模式',
      from: baseline?.primary_failure_mode ? failureModeLabel(baseline.primary_failure_mode) : '无',
      to: candidate?.primary_failure_mode ? failureModeLabel(candidate.primary_failure_mode) : '无',
      fromClass: undefined,
      toClass: undefined,
    },
  ]
  return (
    <div className="s05-verdict-delta" role="status">
      <strong className="s05-verdict-delta__movement"><span>案例变化</span>{statusText(movement)}</strong>
      {fields.map((field) => (
        <span className="s05-verdict-delta__field" key={field.label}>
          <span>{field.label}</span>
          {field.from === field.to
            ? <strong className={field.fromClass}>{field.from}</strong>
            : <strong className={`s05-verdict-delta__changed ${field.toClass ?? ''}`.trim()}>{field.from} → {field.to}</strong>}
        </span>
      ))}
      <span className="s05-verdict-delta__meta">目标变差 {statusText(targetWorse)} · 回归级别 {statusText(regressionLevel ?? 'none')}</span>
    </div>
  )
}

const statusTextLabels: Record<string, string> = {
  improved: '明确改善',
  partially_improved: '部分改善',
  not_improved: '未改善',
  regressed: '变差',
  inconclusive: '无法得出结论',
  stable: '无变化',
  resolved: '已解决',
  present: '仍存在',
  absent: '不存在',
  passed: '通过',
  failed: '未通过',
  verified: '已验证',
  not_applicable: '不适用',
  unsupported: '不支持',
  pending: '待开始',
  running: '运行中',
  completed: '已完成',
  partial_failure: '部分失败',
  invalid: '无效',
  submitted: '已提交',
  pending_review: '待人工复核',
  critical: '严重',
  major: '较大',
  minor: '轻微',
  ACCEPT: '接受',
  CONTINUE: '继续迭代',
  INCONCLUSIVE: '无法得出结论',
  accept: '接受',
  continue: '不采纳',
  true: '是',
  false: '否',
  none: '无',
}

function statusText(value: unknown) {
  const text = String(value)
  return statusTextLabels[text] ?? text
}

function PageMessage({ title, detail }: { title: string; detail: string }) {
  return (
    <section className="s05-page s05-page-message" role="status">
      <MdError aria-hidden="true" />
      <h1>{title}</h1>
      <p>{detail}</p>
    </section>
  )
}

type RunnerAccess = {
  taskId: string
  runnerToken: string
}

const runnerStatusLabels = {
  pending: '等待运行程序',
  running: '运行程序执行中',
  submitted: '回答已提交',
  failed: '执行失败',
}

function RunnerSubmission({
  data,
  task,
  runnerAccess,
  busy,
  validationBusy,
  error,
  onCreate,
  onStart,
}: {
  data: BaseData
  task: ValidationTaskReadResponse | null
  runnerAccess: RunnerAccess | null
  busy: boolean
  validationBusy: boolean
  error: string | null
  onCreate: () => void
  onStart: (label: string, summary: string) => void
}) {
  const [label, setLabel] = useState(`候选版本 V${data.target.version}`)
  const [summary, setSummary] = useState('')
  const [copyStatus, setCopyStatus] = useState<string | null>(null)
  const access = task && runnerAccess?.taskId === task.task_id ? runnerAccess : null
  const runnerCommand = access
    ? buildLocalRunnerCommand({
        baseUrl: API_BASE_URL,
        taskId: access.taskId,
        runnerToken: access.runnerToken,
      })
    : ''

  async function copyValue(value: string, label: string) {
    try {
      await navigator.clipboard.writeText(value)
      setCopyStatus(`${label}已复制。`)
    } catch {
      setCopyStatus(`${label}复制失败，请手动选择复制。`)
    }
  }

  return (
    <section className="s05-page">
      <div className="s05-canvas s05-submit">
        <header>
          <h1>候选版本验证</h1>
          <p>已冻结目标 V{data.target.version} · {data.dataset.name} {data.dataset.version}</p>
        </header>
        <dl className="s05-runner-scope" aria-label="冻结验证范围">
          <div><dt>本轮优化问题</dt><dd>{new Set(data.target.problem_ids).size || 1}</dd></div>
          <div><dt>目标案例</dt><dd>{data.target.target_case_ids.length}</dd></div>
          <div><dt>回归案例</dt><dd>{data.target.regression_case_ids.length}</dd></div>
          <div><dt>挑战案例</dt><dd>{data.target.challenge_case_ids.length}</dd></div>
        </dl>
        <label>
          <span>候选版本名称</span>
          <input value={label} maxLength={120} onChange={(event) => setLabel(event.target.value)} disabled={busy || validationBusy || Boolean(task?.candidate_run_id)} />
        </label>
        <label>
          <span>变更说明（可选）</span>
          <textarea value={summary} maxLength={1000} onChange={(event) => setSummary(event.target.value)} disabled={busy || validationBusy || Boolean(task?.candidate_run_id)} rows={3} />
        </label>
        {error && <p className="s05-form-error" role="alert">{error}</p>}
        {!task ? (
          <button type="button" onClick={onCreate} disabled={busy || !label.trim()}>
            {busy ? '正在创建验证任务…' : '创建验证任务'}
          </button>
        ) : (
          <section className="s05-runner-task" aria-label="本地运行任务" aria-live="polite">
            <header>
              <h2>本地运行程序</h2>
              <span className={`s05-runner-status s05-runner-status--${task.status}`}>
                {runnerStatusLabels[task.status]}
              </span>
            </header>
            <div className="s05-runner-value">
              <span>task_id</span>
              <code>{task.task_id}</code>
            </div>
            {task.status === 'submitted' ? (
              <>
                <p className="s05-runner-success"><MdCheckCircle aria-hidden="true" />候选版本回答已收集</p>
                <button className="s05-runner-copy" type="button" onClick={() => onStart(label.trim(), summary.trim())} disabled={validationBusy || !label.trim()}>
                  {validationBusy ? '正在评测…' : '开始评测'}
                </button>
              </>
            ) : task.status === 'failed' ? (
              <p className="s05-form-error">{task.failed_reason ?? '验证任务执行失败，后端未提供失败原因。'}</p>
            ) : access ? (
              <>
                <div className="s05-runner-value">
                  <span>一次性 Token</span>
                  <code>{access.runnerToken}</code>
                  <button type="button" onClick={() => { void copyValue(access.runnerToken, 'Token') }}>复制</button>
                </div>
                <p className="s05-submit-note">在 SupportLens/backend 目录执行；先替换命令中的三项 AGENT_* 本地配置。智能体 API 密钥仅保留在本机。</p>
                <pre className="s05-runner-command">{runnerCommand}</pre>
                <button className="s05-runner-copy" type="button" onClick={() => { void copyValue(runnerCommand, '运行命令') }}>复制运行命令</button>
              </>
            ) : (
              <p className="s05-submit-note">运行程序 Token 已按安全规则不再显示；页面将继续恢复并同步此任务的真实状态。</p>
            )}
            {copyStatus && <p className="s05-copy-status" role="status">{copyStatus}</p>}
          </section>
        )}
      </div>
    </section>
  )
}

function CandidateWorkspace({
  data,
  selectedCaseId,
  onSelectCase,
  decisionBusy,
  decisionError,
  onDecision,
}: {
  data: CandidateData
  selectedCaseId: string
  onSelectCase: (caseId: string) => void
  decisionBusy: boolean
  decisionError: string | null
  onDecision: (decision: 'accept' | 'continue', actor: string, reason: string, overrideReason: string) => void
}) {
  const { target, candidateRun, conversations, baselineResults, candidateResults, comparisons, summary } = data
  const targetCaseIds = new Set(target.target_case_ids)
  const targetComparisons = comparisons.filter((item) => targetCaseIds.has(item.case_id))
  const orderedComparisons = [
    ...targetComparisons,
    ...comparisons.filter((item) => !targetCaseIds.has(item.case_id)),
  ]
  const selectedComparison = orderedComparisons.find((item) => item.case_id === selectedCaseId) ?? orderedComparisons[0]
  const conversation = conversations.find((item) => item.id === selectedComparison?.conversation_id)
  const baselineResult = baselineResults.find((item) => item.evaluation_result_id === selectedComparison?.baseline_evaluation_result_id)
  const candidateResult = candidateResults.find((item) => item.evaluation_result_id === selectedComparison?.candidate_evaluation_result_id)
  const candidateResponse = candidateRun.candidate_responses_snapshot?.find((item) => item.conversation_id === selectedComparison?.conversation_id)
  const [actor, setActor] = useState('')
  const [reason, setReason] = useState('')
  const [overrideReason, setOverrideReason] = useState('')
  const problemStatusLabels = {
    improved: '明确改善',
    partially_improved: '部分改善',
    not_improved: '未改善',
    regressed: '变差',
    inconclusive: '无法得出结论',
  } as const
  const targetPlanHref = `/target-plan?${new URLSearchParams({
    run_id: target.baseline_run_id,
    problem_id: target.problem_id,
    problem_ids: (target.problem_ids.length ? target.problem_ids : [target.problem_id]).join(','),
    target_id: target.id,
  }).toString()}`
  const pendingReviewCount = candidateResults.filter((item) => item.status === 'pending_review').length
  const gates = [
    ['目标结果', summary.target_outcome],
    ['目标明确改善', `${summary.rule_outcomes.clear_improved_count}/${summary.rule_outcomes.target_case_count}`],
    ['目标变差', String(summary.rule_outcomes.target_worse_count)],
    ['严重回归', String(summary.regression_summary.critical)],
    ['较大回退', String(summary.regression_summary.major)],
    ['轻微回归', String(summary.regression_summary.minor)],
    ['新系统性问题', String(summary.new_systematic_problems.length)],
    ['待人工复核', String(pendingReviewCount)],
    ['完整性', summary.integrity_gate],
    ['兼容性', summary.compatibility_gate],
  ]

  if (!selectedComparison || !conversation || !baselineResult || !candidateResult) {
    return <PageMessage title="案例追溯链不完整" detail="无法按案例对比 ID 关联当前目标案例。" />
  }

  return (
    <section className="s05-page" aria-label="候选版本验证工作区">
      <div className="s05-canvas">
        <div className="s05-conclusion" role="status">
          <span className={`s05-conclusion__verdict s05-conclusion__verdict--${(candidateRun.final_decision ?? summary.recommended_verdict).toLowerCase()}`}>
            {candidateRun.final_decision
              ? `人工决策：${statusText(candidateRun.final_decision)}`
              : `机器建议：${statusText(summary.recommended_verdict)}`}
          </span>
          <p>
            目标 {summary.rule_outcomes.target_case_count} 个问题中 {summary.rule_outcomes.clear_improved_count} 个明确改善、{summary.rule_outcomes.target_worse_count} 个变差；其余 {comparisons.length - targetComparisons.length} 个非目标案例出现 {summary.regression_summary.critical + summary.regression_summary.major} 处较大回退（其中严重 {summary.regression_summary.critical} 处）。{candidateRun.reason ? `决策理由：${candidateRun.reason}` : ''}
          </p>
        </div>
        <div className="s05-metrics" role="list">
          <div className="s05-metric" role="listitem"><strong>{summary.rule_outcomes.target_case_count}</strong><span>目标问题</span></div>
          <div className="s05-metric" role="listitem"><strong className="s05-positive">{summary.rule_outcomes.clear_improved_count}</strong><span>明确改善</span></div>
          <div className="s05-metric" role="listitem"><strong className={summary.rule_outcomes.target_worse_count > 0 ? 's05-negative' : undefined}>{summary.rule_outcomes.target_worse_count}</strong><span>目标变差</span></div>
          <div className="s05-metric" role="listitem"><strong className={summary.regression_summary.major > 0 ? 's05-negative' : undefined}>{summary.regression_summary.major}</strong><span>较大回退</span></div>
          <div className="s05-metric" role="listitem"><strong className={summary.regression_summary.critical > 0 ? 's05-negative' : undefined}>{summary.regression_summary.critical}</strong><span>严重回退</span></div>
          <div className="s05-metric" role="listitem"><strong className={pendingReviewCount > 0 ? 's05-neutral' : undefined}>{pendingReviewCount}</strong><span>待人工复核</span></div>
        </div>

        <section className="s05-details" aria-label="目标对照明细">
          <h2>目标问题逐个对照（{summary.problem_results.length || 1} 个）</h2>
          {summary.problem_results.length ? (
            <ul className="s05-problem-results">
              {summary.problem_results.map((problem) => (
                <li key={problem.problem_id}>
                  <span title={problem.definition}>{problem.definition}</span>
                  <strong className={problem.status === 'regressed' ? 's05-negative' : problem.status === 'improved' ? 's05-positive' : problem.status === 'inconclusive' ? 's05-neutral' : undefined}>{problemStatusLabels[problem.status]}</strong>
                </li>
              ))}
            </ul>
          ) : (
            <p className="s05-legacy-problem-result">历史单问题结果：{statusText(summary.target_outcome)}</p>
          )}
          <p className="s05-detail-note">
            另有轻微回退 {summary.regression_summary.minor}、新系统性问题 {summary.new_systematic_problems.length}、其他问题 {summary.other_problems.length}。回归指候选版本把基线原本答对的案例改错。
          </p>
        </section>

        {candidateRun.final_decision ? (
          <div className="s05-decision-line" role="status">
            <span>机器建议 <strong>{statusText(summary.recommended_verdict)}</strong></span>
            <span>完整性 <strong>{statusText(summary.integrity_gate)}</strong> · 兼容性 <strong>{statusText(summary.compatibility_gate)}</strong></span>
            {summary.blockers.length ? <span>阻断项：{summary.blockers.map(blockerLabel).join('、')}</span> : null}
          </div>
        ) : (
          <section className="s05-decision" aria-label="候选版本决策">
            <article className="s05-recommendation"><span className="s05-eyebrow">系统建议 · {summary.policy_version}</span><h2>{statusText(summary.recommended_verdict)}</h2><dl>{gates.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{statusText(value)}</dd></div>)}</dl><p>{summary.blockers.length ? `阻断项：${summary.blockers.map(blockerLabel).join('、')}` : '所有机器阻断项已通过；等待人工决策。'}</p></article>
            <article className="s05-human-decision"><header><span className="s05-eyebrow">人工最终决策</span></header><label><span>决策人</span><input value={actor} onChange={(event) => setActor(event.target.value)} disabled={decisionBusy} /></label><textarea aria-label="决策理由" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="必须填写决策理由。" disabled={decisionBusy} /><textarea aria-label="改判理由" value={overrideReason} onChange={(event) => setOverrideReason(event.target.value)} placeholder="与机器建议不一致时必填 override_reason。" disabled={decisionBusy} />{decisionError && <p className="s05-form-error">{decisionError}</p>}</article>
          </section>
        )}

        <section className="s05-case-tabs" aria-label="评测案例选择"><strong>评测案例（{orderedComparisons.length}）：</strong><div>{orderedComparisons.map((item) => <button className={[
                  's05-case-tab',
                  item.case_id === selectedComparison.case_id ? 's05-case-tab--active' : '',
                  item.movement === 'improved' ? 's05-case-tab--improved' : '',
                  item.movement === 'regressed' ? 's05-case-tab--regressed' : '',
                ].filter(Boolean).join(' ')} key={item.id} type="button" aria-pressed={item.case_id === selectedComparison.case_id} title={`${statusText(item.movement)}${item.regression_level ? ` · ${statusText(item.regression_level)}` : ''}`} onClick={() => onSelectCase(item.case_id)}>{item.case_id}</button>)}</div></section>

        <section className="s05-comparison" aria-labelledby="s05-comparison-title">
          <header className="s05-comparison-header"><h2 id="s05-comparison-title"><span>案例 ID：</span>{selectedComparison.case_id}<em title={selectedComparison.conversation_id}>conversation_id：{selectedComparison.conversation_id.slice(0, 8)}…</em></h2></header>
          <div className="s05-comparison-body">
            <VerdictDeltaBar
              baseline={effectiveOutput(baselineResult)}
              candidate={effectiveOutput(candidateResult)}
              movement={selectedComparison.movement}
              targetWorse={selectedComparison.target_worse}
              regressionLevel={selectedComparison.regression_level}
            />
            <ComparisonNode label="用户提问"><p>{messageContent(conversation, 'user')}</p></ComparisonNode>
            <div className="s05-version-columns">
              <div className="s05-version-column">
                <ComparisonNode label="客服回复 · 基线"><p>{messageContent(conversation, 'assistant')}</p></ComparisonNode>
                <ComparisonNode label="评测判定 · 基线" aside={provenanceLine(baselineResult)}>
                  {effectiveOutput(baselineResult) ? <JudgeBlock result={effectiveOutput(baselineResult)!} /> : <p>{statusText(baselineResult?.status)}</p>}
                </ComparisonNode>
              </div>
              <div className="s05-version-column s05-version-column--candidate">
                <ComparisonNode accent label="客服回复 · 候选版本"><p>{candidateResponse?.assistant_content ?? '候选版本回复不存在'}</p></ComparisonNode>
                <ComparisonNode accent label="评测判定 · 候选版本" aside={provenanceLine(candidateResult)}>
                  {effectiveOutput(candidateResult) ? <JudgeBlock result={effectiveOutput(candidateResult)!} /> : <p>候选判定不存在</p>}
                </ComparisonNode>
              </div>
            </div>
            <div className="s05-shared-evidence"><ComparisonNode label="业务上下文"><pre>{displayValue(conversationMetadata(conversation, 'business_context'))}</pre></ComparisonNode><ComparisonNode label="参考依据"><pre>{displayValue(conversationMetadata(conversation, 'reference_evidence'))}</pre></ComparisonNode></div>
          </div>
        </section>

      </div>

      <footer className="s05-action-rail">
        <em title={target.plan_hash ?? undefined}>PLAN V{target.version} · {target.plan_hash ? `${target.plan_hash.slice(0, 8)}…` : '—'} · 结论仅适用于当前已冻结目标与数据集</em>
        <div className="s05-action-area">
          {candidateRun.final_decision === 'continue' ? (
            <div className="s05-action-complete s05-action-complete--continue" role="status">
              <strong>当前候选版本不采纳</strong>
              <Link to={targetPlanHref}>返回上一步</Link>
            </div>
          ) : candidateRun.final_decision === 'accept' ? (
            <div className="s05-action-complete s05-action-complete--accept" role="status">
              <strong>候选版本已接受</strong>
            </div>
          ) : (
            <>
              <button type="button" onClick={() => onDecision('continue', actor, reason, overrideReason)} disabled={decisionBusy || !actor.trim() || !reason.trim()}>继续迭代</button>
              <button type="button" onClick={() => onDecision('accept', actor, reason, overrideReason)} disabled={decisionBusy || summary.recommended_verdict !== 'ACCEPT' || !actor.trim() || !reason.trim()}><MdVerified aria-hidden="true" />接受候选版本</button>
            </>
          )}
        </div>
      </footer>
    </section>
  )
}

function CandidateValidationPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const targetId = searchParams.get('target_id')?.trim() ?? ''
  const candidateRunId = searchParams.get('candidate_run_id')?.trim() ?? ''
  const validationTaskId = searchParams.get('validation_task_id')?.trim() ?? ''
  const workflowRunId = searchParams.get('run_id')?.trim() ?? ''
  const workflowProblemId = searchParams.get('problem_id')?.trim() ?? ''
  const workflowProblemIds = searchParams.get('problem_ids')?.trim() ?? ''
  const requestKey = `${targetId}:${candidateRunId}:${validationTaskId}`
  const [loadResult, setLoadResult] = useState<{ requestKey: string; state: PageState }>(() => ({ requestKey, state: targetId ? { kind: 'loading' } : { kind: 'missing_target' } }))
  const [selectedCaseId, setSelectedCaseId] = useState('')
  const [taskCreationBusy, setTaskCreationBusy] = useState(false)
  const [candidateValidationBusy, setCandidateValidationBusy] = useState(false)
  const [taskError, setTaskError] = useState<string | null>(null)
  const [runnerAccess, setRunnerAccess] = useState<RunnerAccess | null>(null)
  const [decisionBusy, setDecisionBusy] = useState(false)
  const [decisionError, setDecisionError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    if (!targetId) return
    const controller = new AbortController()
    async function load() {
      try {
        const target = await getOptimizationTarget(targetId, controller.signal)
        const targetProblemIds = target.problem_ids.length ? target.problem_ids : [target.problem_id]
        const problemIdsParam = targetProblemIds.join(',')
        if (
          workflowRunId !== target.baseline_run_id
          || workflowProblemId !== target.problem_id
          || workflowProblemIds !== problemIdsParam
        ) {
          const params = new URLSearchParams({
            target_id: target.id,
            run_id: target.baseline_run_id,
            problem_id: target.problem_id,
            problem_ids: problemIdsParam,
          })
          if (candidateRunId) params.set('candidate_run_id', candidateRunId)
          if (validationTaskId) params.set('validation_task_id', validationTaskId)
          setSearchParams(params, { replace: true })
        }
        if (target.status !== 'frozen') {
          setLoadResult({ requestKey, state: { kind: 'target_not_frozen', target } })
          return
        }
        const baselineRun = await getEvaluationRun(target.baseline_run_id, controller.signal)
        const [dataset, conversations] = await Promise.all([getDatasetDetail(baselineRun.dataset_id, controller.signal), getDatasetConversations(baselineRun.dataset_id, controller.signal)])
        const base = { target, baselineRun, dataset, conversations }
        if (!candidateRunId) {
          if (!validationTaskId) {
            setLoadResult({ requestKey, state: { kind: 'runner_setup', data: base } })
            return
          }
          const task = await getValidationTask(validationTaskId, controller.signal)
          if (task.target_id !== target.id) {
            setLoadResult({ requestKey, state: { kind: 'task_not_found' } })
            return
          }
          if (task.candidate_run_id) {
            const params = new URLSearchParams({
              target_id: target.id,
              run_id: target.baseline_run_id,
              problem_id: target.problem_id,
              problem_ids: problemIdsParam,
              validation_task_id: task.task_id,
              candidate_run_id: task.candidate_run_id,
            })
            setSearchParams(params, { replace: true })
            return
          }
          setLoadResult({ requestKey, state: { kind: 'runner_task', data: base, task } })
          return
        }
        const candidateRun = await getEvaluationRun(candidateRunId, controller.signal)
        if (candidateRun.run_type !== 'candidate' || candidateRun.target_id !== target.id) {
          setLoadResult({ requestKey, state: { kind: 'candidate_not_found' } })
          return
        }
        if (candidateRun.status !== 'completed') {
          setLoadResult({ requestKey, state: { kind: 'candidate_status', candidateRun } })
          return
        }
        const [baselineResults, candidateResults, existingComparisons] = await Promise.all([getFinalEffectiveResults(baselineRun.id, controller.signal), getFinalEffectiveResults(candidateRun.id, controller.signal), getCandidateComparisons(candidateRun.id, controller.signal)])
        const comparisons = existingComparisons.length ? existingComparisons : await createCandidateComparisons(candidateRun.id)
        const summary = await getCandidateValidationSummary(candidateRun.id, controller.signal)
        setLoadResult({ requestKey, state: { kind: 'ready', data: { ...base, candidateRun, baselineResults, candidateResults, comparisons, summary } } })
      } catch (error) {
        if (controller.signal.aborted) return
        if (error instanceof ApiRequestError && error.code === 'optimization_target_not_found') {
          setLoadResult({ requestKey, state: { kind: 'target_not_found' } })
          return
        }
        if (error instanceof ApiRequestError && error.code === 'evaluation_run_not_found' && candidateRunId) {
          setLoadResult({ requestKey, state: { kind: 'candidate_not_found' } })
          return
        }
        if (error instanceof ApiRequestError && error.code === 'validation_task_not_found' && validationTaskId) {
          setLoadResult({ requestKey, state: { kind: 'task_not_found' } })
          return
        }
        setLoadResult({ requestKey, state: { kind: 'error', message: error instanceof Error ? error.message : '无法加载候选版本验证。' } })
      }
    }
    void load()
    return () => controller.abort()
  }, [candidateRunId, reloadKey, requestKey, setSearchParams, targetId, validationTaskId, workflowProblemId, workflowProblemIds, workflowRunId])

  const pageState: PageState = !targetId ? { kind: 'missing_target' } : loadResult.requestKey === requestKey ? loadResult.state : { kind: 'loading' }
  const pollingCandidateId = pageState.kind === 'candidate_status' ? pageState.candidateRun.id : ''
  const pollingCandidateStatus = pageState.kind === 'candidate_status' ? pageState.candidateRun.status : ''
  const pollingTaskId = pageState.kind === 'runner_task' ? pageState.task.task_id : ''
  const pollingTaskStatus = pageState.kind === 'runner_task' ? pageState.task.status : ''

  useEffect(() => {
    if (!pollingCandidateId || !['pending', 'running'].includes(pollingCandidateStatus)) return
    const timer = window.setTimeout(() => setReloadKey((current) => current + 1), 1500)
    return () => window.clearTimeout(timer)
  }, [pollingCandidateId, pollingCandidateStatus])

  useEffect(() => {
    if (!pollingTaskId || !['pending', 'running'].includes(pollingTaskStatus)) return
    const controller = new AbortController()
    let requestPending = false
    const timer = window.setInterval(() => {
      if (requestPending) return
      requestPending = true
      void getValidationTask(pollingTaskId, controller.signal)
        .then((task) => {
          setTaskError(null)
          setLoadResult((current) => (
            current.requestKey === requestKey && current.state.kind === 'runner_task'
              ? { requestKey, state: { ...current.state, task } }
              : current
          ))
        })
        .catch((error) => {
          if (!controller.signal.aborted) {
            setTaskError(error instanceof Error ? error.message : '验证任务状态同步失败。')
          }
        })
        .finally(() => { requestPending = false })
    }, 1500)
    return () => {
      window.clearInterval(timer)
      controller.abort()
    }
  }, [pollingTaskId, pollingTaskStatus, requestKey])

  async function createRunnerTask() {
    if (pageState.kind !== 'runner_setup' || taskCreationBusy) return
    setTaskCreationBusy(true)
    setTaskError(null)
    try {
      const created = await createValidationTask(pageState.data.target.id)
      if (created.optimization_target_id !== pageState.data.target.id) {
        throw new Error('后端返回的验证任务不属于当前已冻结目标。')
      }
      setRunnerAccess({ taskId: created.task_id, runnerToken: created.runner_token })
      setSearchParams(withValidationTaskId(searchParams.toString(), created.task_id), { replace: true })
    } catch (error) {
      setTaskError(error instanceof Error ? error.message : '验证任务创建失败。')
    } finally {
      setTaskCreationBusy(false)
    }
  }

  async function startCandidateValidation(label: string, summary: string) {
    if (
      pageState.kind !== 'runner_task'
      || pageState.task.status !== 'submitted'
      || candidateValidationBusy
    ) return
    setCandidateValidationBusy(true)
    setTaskError(null)
    try {
      const candidateRun = await startValidationTaskCandidateValidation(
        pageState.task.task_id,
        {
          candidate_label: label,
          change_summary: summary || null,
        },
      )
      const params = new URLSearchParams(searchParams.toString())
      params.set('candidate_run_id', candidateRun.id)
      params.set('validation_task_id', pageState.task.task_id)
      setSearchParams(params, { replace: true })
    } catch (error) {
      const code = error instanceof ApiRequestError ? ` (${error.code})` : ''
      setTaskError(`${error instanceof Error ? error.message : '候选版本验证启动失败。'}${code}`)
    } finally {
      setCandidateValidationBusy(false)
    }
  }

  async function submitDecision(decision: 'accept' | 'continue', actor: string, reason: string, overrideReason: string) {
    if (pageState.kind !== 'ready') return
    setDecisionBusy(true)
    setDecisionError(null)
    try {
      const candidateRun = await submitCandidateFinalDecision(pageState.data.candidateRun.id, { final_decision: decision, decided_by: actor.trim(), reason: reason.trim(), override_reason: overrideReason.trim() || null })
      setLoadResult((current) => current.requestKey === requestKey && current.state.kind === 'ready' ? { requestKey, state: { kind: 'ready', data: { ...current.state.data, candidateRun } } } : current)
    } catch (error) {
      const code = error instanceof ApiRequestError ? ` (${error.code})` : ''
      setDecisionError(`${error instanceof Error ? error.message : '人工决策保存失败。'}${code}`)
    } finally {
      setDecisionBusy(false)
    }
  }

  if (pageState.kind === 'missing_target') return <PageMessage title="缺少已冻结目标" detail="请从目标与计划页面使用 target_id 进入候选版本验证。" />
  if (pageState.kind === 'loading') return <PageMessage title="正在加载候选版本验证" detail="正在读取已冻结目标与真实运行数据…" />
  if (pageState.kind === 'target_not_found') return <PageMessage title="优化目标不存在" detail={`未找到 target_id=${targetId}。`} />
  if (pageState.kind === 'candidate_not_found') return <PageMessage title="候选版本运行不存在" detail="candidate_run_id 不存在或不属于当前已冻结目标。" />
  if (pageState.kind === 'task_not_found') return <PageMessage title="验证任务不存在" detail="validation_task_id 不存在或不属于当前已冻结目标。" />
  if (pageState.kind === 'target_not_frozen') return <PageMessage title="目标尚未冻结" detail={`当前状态为 ${targetStatusLabel(pageState.target.status)}，必须先在目标与计划页面冻结。`} />
  if (pageState.kind === 'error') return <PageMessage title="候选版本验证加载失败" detail={pageState.message} />
  if (pageState.kind === 'candidate_status') return <PageMessage title={`候选版本运行${runStatusLabel(pageState.candidateRun.status)}`} detail={`运行 ${pageState.candidateRun.id} 已从后端恢复。`} />
  if (pageState.kind === 'runner_setup') return <RunnerSubmission key={pageState.data.target.id} data={pageState.data} task={null} runnerAccess={runnerAccess} busy={taskCreationBusy} validationBusy={candidateValidationBusy} error={taskError} onCreate={() => { void createRunnerTask() }} onStart={(label, summary) => { void startCandidateValidation(label, summary) }} />
  if (pageState.kind === 'runner_task') return <RunnerSubmission key={pageState.data.target.id} data={pageState.data} task={pageState.task} runnerAccess={runnerAccess} busy={taskCreationBusy} validationBusy={candidateValidationBusy} error={taskError} onCreate={() => { void createRunnerTask() }} onStart={(label, summary) => { void startCandidateValidation(label, summary) }} />
  return <CandidateWorkspace data={pageState.data} selectedCaseId={selectedCaseId} onSelectCase={setSelectedCaseId} decisionBusy={decisionBusy} decisionError={decisionError} onDecision={(decision, actor, reason, overrideReason) => { void submitDecision(decision, actor, reason, overrideReason) }} />
}

export default CandidateValidationPage
