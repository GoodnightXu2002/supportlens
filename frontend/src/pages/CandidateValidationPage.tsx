import { useEffect, useState } from 'react'
import {
  MdAnalytics,
  MdArrowForward,
  MdChatBubble,
  MdCheckCircle,
  MdError,
  MdFactCheck,
  MdForum,
  MdMenuBook,
  MdPerson,
  MdSmartToy,
  MdVerified,
} from 'react-icons/md'
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
  type JudgeEvidence,
  type JudgeOutput,
  type OptimizationTarget,
  type ValidationTaskReadResponse,
} from '../api'
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
  icon: React.ReactNode
  label: string
  children: React.ReactNode
}

function ComparisonNode({ accent = false, icon, label, children }: ComparisonNodeProps) {
  return (
    <div className={accent ? 's05-node s05-node--candidate' : 's05-node'}>
      <span className="s05-node__icon" aria-hidden="true">{icon}</span>
      <div className="s05-node__content">
        <span className="s05-node__label">{label}</span>
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

function judgeSummary(result: JudgeOutput) {
  return [
    `judgment: ${result.judgment}`,
    `primary_failure_mode: ${result.primary_failure_mode ?? 'null'}`,
    `severity: ${result.severity ?? 'null'}`,
    `problem: ${result.problem ?? 'null'}`,
    `review_required: ${String(result.review_required)}`,
    `rationale: ${result.rationale}`,
  ].join('\n')
}

function evidenceText(evidence: JudgeEvidence[] | null) {
  if (!evidence?.length) return '无可用证据'
  return evidence
    .map((item) => `${item.evidence_type} · ${item.source_ref ?? '无 source_ref'}\n${item.content}`)
    .join('\n\n')
}

function resultReview(result: FinalEffectiveResult | undefined) {
  if (!result) return '结果不存在'
  if (!result.human_decision) return 'Machine Final · 无人工复核'
  return [
    `reviewer: ${result.human_decision.reviewer}`,
    `reviewed_at: ${formatDate(result.human_decision.reviewed_at)}`,
    `change_reason: ${result.human_decision.change_reason ?? '确认原结果，无修正理由'}`,
  ].join('\n')
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
  pending: 'pending · 等待 Runner',
  running: 'running · Runner 执行中',
  submitted: 'submitted · 回答已提交',
  failed: 'failed · 执行失败',
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
  const [label, setLabel] = useState(`Candidate V${data.target.version}`)
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
          <p>Frozen Target V{data.target.version} · {data.dataset.name} {data.dataset.version}</p>
        </header>
        <dl className="s05-runner-scope" aria-label="冻结验证范围">
          <div><dt>本轮优化问题</dt><dd>{new Set(data.target.problem_ids).size || 1}</dd></div>
          <div><dt>Target</dt><dd>{data.target.target_case_ids.length}</dd></div>
          <div><dt>Regression</dt><dd>{data.target.regression_case_ids.length}</dd></div>
          <div><dt>Challenge</dt><dd>{data.target.challenge_case_ids.length}</dd></div>
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
          <section className="s05-runner-task" aria-label="Local Runner 任务" aria-live="polite">
            <header>
              <h2>Local Runner</h2>
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
              <p className="s05-form-error">{task.failed_reason ?? '验证任务执行失败，Backend 未提供失败原因。'}</p>
            ) : access ? (
              <>
                <div className="s05-runner-value">
                  <span>一次性 token</span>
                  <code>{access.runnerToken}</code>
                  <button type="button" onClick={() => { void copyValue(access.runnerToken, 'Token') }}>复制</button>
                </div>
                <p className="s05-submit-note">在 SupportLens/backend 目录执行；先替换命令中的三项 AGENT_* 本地配置。Agent API Key 仅保留在本机。</p>
                <pre className="s05-runner-command">{runnerCommand}</pre>
                <button className="s05-runner-copy" type="button" onClick={() => { void copyValue(runnerCommand, 'Runner 命令') }}>复制 Runner 命令</button>
              </>
            ) : (
              <p className="s05-submit-note">Runner token 已按安全规则不再显示；页面将继续恢复并同步此任务的真实状态。</p>
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
  const { target, baselineRun, candidateRun, dataset, conversations, baselineResults, candidateResults, comparisons, summary } = data
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
  const movements = ['improved', 'partially_improved', 'stable', 'regressed', 'inconclusive'] as const
  const movementCounts = Object.fromEntries(movements.map((movement) => [movement, targetComparisons.filter((item) => item.movement === movement).length]))
  const problemStatusLabels = {
    improved: 'Improved',
    partially_improved: 'Partially Improved',
    not_improved: 'Not Improved',
    regressed: 'Regressed',
    inconclusive: 'Inconclusive',
  } as const
  const targetPlanHref = `/target-plan?${new URLSearchParams({
    run_id: target.baseline_run_id,
    problem_id: target.problem_id,
    problem_ids: (target.problem_ids.length ? target.problem_ids : [target.problem_id]).join(','),
    target_id: target.id,
  }).toString()}`
  const pendingReviewCount = candidateResults.filter((item) => item.status === 'pending_review').length
  const manifest = candidateRun.candidate_manifest_snapshot ?? {}
  const lineage = [
    `TARGET-V${target.version} · ${target.id}`,
    `PLAN-HASH · ${target.plan_hash}`,
    `BASELINE-RUN · ${baselineRun.id}`,
    `CANDIDATE-RUN · ${candidateRun.id}`,
    `RESPONSE-SET-HASH · ${candidateRun.response_set_hash}`,
    `JUDGE-CONTRACT · ${candidateRun.judge_contract_version}`,
    `DECISION-POLICY · ${summary.policy_version}`,
  ]
  const gates = [
    ['Target outcome', summary.target_outcome],
    ['Target clear improved', `${summary.rule_outcomes.clear_improved_count}/${summary.rule_outcomes.target_case_count}`],
    ['Target worse', String(summary.rule_outcomes.target_worse_count)],
    ['Critical regression', String(summary.regression_summary.critical)],
    ['Major regression', String(summary.regression_summary.major)],
    ['Minor regression', String(summary.regression_summary.minor)],
    ['New systematic problem', String(summary.new_systematic_problems.length)],
    ['Pending review', String(pendingReviewCount)],
    ['Integrity', summary.integrity_gate],
    ['Compatibility', summary.compatibility_gate],
  ]

  if (!selectedComparison || !conversation || !baselineResult || !candidateResult) {
    return <PageMessage title="Case traceability 不完整" detail="无法按 comparison IDs 关联当前 Target Case。" />
  }

  return (
    <section className="s05-page" aria-label="候选版本验证工作区">
      <div className="s05-canvas">
        <section className="s05-metadata" aria-label="候选版本验证上下文">
          <div><span>数据集</span><strong>{dataset.name} {dataset.version}</strong></div>
          <div><span>基线版本</span><strong title={baselineRun.id}>{baselineRun.id}</strong></div>
          <div><span>候选版本</span><strong title={candidateRun.id}>{candidateRun.candidate_label} · {candidateRun.id}</strong></div>
          <div><span>结论范围</span><strong>当前 Frozen Validation Plan</strong></div>
        </section>

        <section className="s05-status" aria-label="实验状态与追溯链">
          <div className="s05-status-chips"><span>运行：{candidateRun.status}</span><span>阻断：{summary.blockers.length || 'none'}</span><span>实验完整性：{summary.integrity_gate}</span><span>人工最终决策：{candidateRun.final_decision ?? 'not available'}</span></div>
          <div className="s05-status-details">
            <div className="s05-lineage"><h2>实验追溯链</h2>{lineage.map((item) => <code key={item}>{item}</code>)}</div>
            <div className="s05-gates"><h2>状态门槛</h2><div><span>实际变更：{displayValue(manifest.actual_change_status)}</span><span>生成一致性：{displayValue(manifest.generation_parity_status)}</span><span>评测配置兼容性：{summary.compatibility_gate}</span><span>受保护能力：{summary.protected_capability_gate}</span><span>Final Results：{candidateResults.filter((item) => item.status === 'final').length}/{candidateResults.length}</span><span>Comparison：{comparisons.length}</span></div><p>仅展示 Backend 已保存的 Candidate manifest、Final Effective Results、Comparison 与 Validation Summary。</p></div>
          </div>
        </section>

        <section className="s05-outcomes" aria-label="目标与回归结果">
          <article className="s05-outcome-card"><MdCheckCircle className="s05-outcome-icon" aria-hidden="true" /><div><h2>Problem-level（{summary.problem_results.length || 1}）</h2>{summary.problem_results.length ? <ul className="s05-problem-results">{summary.problem_results.map((problem) => <li key={problem.problem_id}><span title={problem.definition}>{problem.definition}</span><strong>{problemStatusLabels[problem.status]}</strong></li>)}</ul> : <p className="s05-legacy-problem-result">历史单 Problem 结果：{summary.target_outcome}</p>}<dl><div><dt>目标案例</dt><dd>{targetComparisons.length}</dd></div><div><dt>明确改善</dt><dd className="s05-positive">{movementCounts.improved}</dd></div><div><dt>部分改善</dt><dd>{movementCounts.partially_improved}</dd></div><div><dt>目标变差</dt><dd>{summary.rule_outcomes.target_worse_count}</dd></div><div><dt>无法得出结论</dt><dd>{movementCounts.inconclusive}</dd></div><div><dt>剩余目标 High/Critical</dt><dd>{summary.rule_outcomes.remaining_target_high_critical}</dd></div></dl></div></article>
          <article className="s05-outcome-card s05-regression-card"><MdVerified className="s05-outcome-icon" aria-hidden="true" /><div><h2>Version-level · 回归检查 ({comparisons.length - targetComparisons.length} 个非目标案例)</h2><div className="s05-regression-grid"><dl><div><dt>严重回归 CRITICAL</dt><dd>{summary.regression_summary.critical}</dd></div><div><dt>重大回归 MAJOR</dt><dd>{summary.regression_summary.major}</dd></div></dl><dl><div className="s05-minor-regression"><dt>轻微回归 MINOR</dt><dd>{summary.regression_summary.minor}</dd></div></dl><dl><div><dt>新系统性问题</dt><dd>{summary.new_systematic_problems.length}</dd></div><div><dt>Other Problems</dt><dd>{summary.other_problems.length}</dd></div><div><dt>剩余必需人工复核</dt><dd>{pendingReviewCount}</dd></div></dl></div><p>Regression 与 New Systematic Problem 均直接来自 Backend Validation Summary。</p></div></article>
        </section>

        <section className="s05-case-tabs" aria-label="评测案例选择"><strong>评测案例（{orderedComparisons.length}）：</strong><div>{orderedComparisons.map((item) => <button className={item.case_id === selectedComparison.case_id ? 's05-case-tab s05-case-tab--active' : 's05-case-tab'} key={item.id} type="button" aria-pressed={item.case_id === selectedComparison.case_id} title={`${item.movement}${item.regression_level ? ` · ${item.regression_level}` : ''}`} onClick={() => onSelectCase(item.case_id)}>{item.case_id}</button>)}</div></section>

        <section className="s05-comparison" aria-labelledby="s05-comparison-title">
          <header className="s05-comparison-header"><h2 id="s05-comparison-title"><span>案例 ID：</span>{selectedComparison.case_id}<em>conversation_id：{selectedComparison.conversation_id}</em></h2><div><span><i />Baseline</span><span><i />Candidate</span></div></header>
          <div className="s05-comparison-body">
            <ComparisonNode icon={<MdChatBubble />} label="会话 / 用户消息"><p>{messageContent(conversation, 'user')}</p></ComparisonNode>
            <div className="s05-version-columns">
              <div className="s05-version-column"><ComparisonNode icon={<MdForum />} label="回复"><p>{messageContent(conversation, 'assistant')}</p></ComparisonNode><ComparisonNode icon={<MdSmartToy />} label="Machine JudgeOutput"><pre className="s05-node-box">{judgeSummary(baselineResult.machine_result)}</pre></ComparisonNode><ComparisonNode icon={<MdPerson />} label="人工复核"><pre>{resultReview(baselineResult)}</pre></ComparisonNode><ComparisonNode icon={<MdVerified />} label="最终生效结果"><pre className="s05-node-box s05-effective-result">{baselineResult.final_result ? judgeSummary(baselineResult.final_result) : baselineResult.status}</pre></ComparisonNode><ComparisonNode icon={<MdAnalytics />} label="回复证据"><pre>{evidenceText(selectedComparison.evidence_snapshot.baseline)}</pre></ComparisonNode></div>
              <div className="s05-movement"><span><MdArrowForward aria-hidden="true" /></span><strong>案例变化：{selectedComparison.movement}</strong><dl><div><dt>Target status</dt><dd>{selectedComparison.target_problem_status}</dd></div><div><dt>Target worse</dt><dd>{String(selectedComparison.target_worse)}</dd></div><div><dt>Regression</dt><dd>{selectedComparison.regression_level ?? 'none'}</dd></div></dl></div>
              <div className="s05-version-column s05-version-column--candidate"><ComparisonNode accent icon={<MdForum />} label="回复"><p>{candidateResponse?.assistant_content ?? 'Candidate response 不存在'}</p></ComparisonNode><ComparisonNode accent icon={<MdSmartToy />} label="Machine JudgeOutput"><pre className="s05-node-box">{judgeSummary(candidateResult.machine_result)}</pre></ComparisonNode><ComparisonNode accent icon={<MdPerson />} label="人工复核"><pre>{resultReview(candidateResult)}</pre></ComparisonNode><ComparisonNode accent icon={<MdVerified />} label="最终生效结果"><pre className="s05-node-box s05-effective-result s05-effective-result--candidate">{candidateResult.final_result ? judgeSummary(candidateResult.final_result) : candidateResult.status}</pre></ComparisonNode><ComparisonNode accent icon={<MdAnalytics />} label="回复证据"><pre>{evidenceText(selectedComparison.evidence_snapshot.candidate)}</pre></ComparisonNode></div>
            </div>
            <div className="s05-shared-evidence"><ComparisonNode icon={<MdFactCheck />} label="业务上下文"><pre>{displayValue(conversationMetadata(conversation, 'business_context'))}</pre></ComparisonNode><ComparisonNode icon={<MdMenuBook />} label="参考依据"><pre>{displayValue(conversationMetadata(conversation, 'reference_evidence'))}</pre></ComparisonNode></div>
          </div>
        </section>

        <section className="s05-decision" aria-label="候选版本决策">
          <article className="s05-recommendation"><span className="s05-eyebrow">Version-level · 系统建议 · {summary.policy_version}</span><h2>{summary.recommended_verdict}</h2><dl>{gates.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><p><span aria-hidden="true" />{summary.blockers.length ? `Blockers: ${summary.blockers.join(', ')}` : '所有 machine blockers 已通过；仍等待独立 Human Decision。'}</p></article>
          <article className="s05-human-decision"><header><span className="s05-eyebrow">人工最终决策</span><div><MdPerson aria-hidden="true" /><span>{candidateRun.decided_by ?? '尚未决定'}</span></div></header>{candidateRun.final_decision ? <dl><div><dt>决策</dt><dd>{candidateRun.final_decision}</dd></div><div><dt>决定时间</dt><dd>{formatDate(candidateRun.decided_at)}</dd></div><div><dt>理由</dt><dd>{candidateRun.reason}</dd></div><div><dt>Override reason</dt><dd>{candidateRun.override_reason ?? '未改判机器建议'}</dd></div></dl> : <><label><span>决策人</span><input value={actor} onChange={(event) => setActor(event.target.value)} disabled={decisionBusy} /></label><textarea aria-label="决策理由" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="必须填写决策理由。" disabled={decisionBusy} /><textarea aria-label="改判理由" value={overrideReason} onChange={(event) => setOverrideReason(event.target.value)} placeholder="与 Machine recommendation 不一致时必填 override_reason。" disabled={decisionBusy} />{decisionError && <p className="s05-form-error">{decisionError}</p>}</>}</article>
        </section>
        <section className="s05-claim-boundary" aria-label="结论边界"><strong>Case pairing：same dataset / conversation_id / case_id。</strong><em>结论仅适用于当前 Frozen Target、数据集、Judge 配置与 response set。</em><span>Human Decision 与 Machine recommendation 独立保存，不代表上线或部署。</span></section>
      </div>

      <footer className="s05-action-rail">
        <em>PLAN V{target.version} · {target.plan_hash}</em>
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
      <div className="s05-analyst-dock"><MdPerson aria-hidden="true" /><strong>{candidateRun.decided_by ?? 'Human Decision'}</strong></div>
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
        setLoadResult({ requestKey, state: { kind: 'error', message: error instanceof Error ? error.message : '无法加载 Candidate Validation。' } })
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
        throw new Error('Backend 返回的 Validation Task 不属于当前 Frozen Target。')
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
      setTaskError(`${error instanceof Error ? error.message : 'Candidate Validation 启动失败。'}${code}`)
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
      setDecisionError(`${error instanceof Error ? error.message : 'Human Decision 保存失败。'}${code}`)
    } finally {
      setDecisionBusy(false)
    }
  }

  if (pageState.kind === 'missing_target') return <PageMessage title="缺少 Frozen Target" detail="请从 S04 使用 target_id 进入 Candidate Validation。" />
  if (pageState.kind === 'loading') return <PageMessage title="正在加载 Candidate Validation" detail="正在读取 Frozen Target 与真实运行数据…" />
  if (pageState.kind === 'target_not_found') return <PageMessage title="OptimizationTarget 不存在" detail={`未找到 target_id=${targetId}。`} />
  if (pageState.kind === 'candidate_not_found') return <PageMessage title="Candidate Run 不存在" detail="candidate_run_id 不存在或不属于当前 Frozen Target。" />
  if (pageState.kind === 'task_not_found') return <PageMessage title="Validation Task 不存在" detail="validation_task_id 不存在或不属于当前 Frozen Target。" />
  if (pageState.kind === 'target_not_frozen') return <PageMessage title="Target 尚未冻结" detail={`当前状态为 ${pageState.target.status}，必须先在 S04 Freeze。`} />
  if (pageState.kind === 'error') return <PageMessage title="Candidate Validation 加载失败" detail={pageState.message} />
  if (pageState.kind === 'candidate_status') return <PageMessage title={`Candidate Run ${pageState.candidateRun.status}`} detail={`Run ${pageState.candidateRun.id} 已从 Backend 恢复。`} />
  if (pageState.kind === 'runner_setup') return <RunnerSubmission key={pageState.data.target.id} data={pageState.data} task={null} runnerAccess={runnerAccess} busy={taskCreationBusy} validationBusy={candidateValidationBusy} error={taskError} onCreate={() => { void createRunnerTask() }} onStart={(label, summary) => { void startCandidateValidation(label, summary) }} />
  if (pageState.kind === 'runner_task') return <RunnerSubmission key={pageState.data.target.id} data={pageState.data} task={pageState.task} runnerAccess={runnerAccess} busy={taskCreationBusy} validationBusy={candidateValidationBusy} error={taskError} onCreate={() => { void createRunnerTask() }} onStart={(label, summary) => { void startCandidateValidation(label, summary) }} />
  return <CandidateWorkspace data={pageState.data} selectedCaseId={selectedCaseId} onSelectCase={setSelectedCaseId} decisionBusy={decisionBusy} decisionError={decisionError} onDecision={(decision, actor, reason, overrideReason) => { void submitDecision(decision, actor, reason, overrideReason) }} />
}

export default CandidateValidationPage
