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
import { useSearchParams } from 'react-router-dom'

import {
  ApiRequestError,
  createCandidateComparisons,
  createCandidateRun,
  executeCandidateRun,
  getCandidateComparisons,
  getCandidateValidationSummary,
  getDatasetConversations,
  getDatasetDetail,
  getEvaluationRun,
  getFinalEffectiveResults,
  getOptimizationTarget,
  submitCandidateFinalDecision,
  type CandidateResponseInput,
  type CandidateValidationSummary,
  type CaseComparison,
  type DatasetConversation,
  type DatasetDetail,
  type EvaluationRun,
  type FinalEffectiveResult,
  type JudgeEvidence,
  type JudgeOutput,
  type OptimizationTarget,
} from '../api'
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
  | { kind: 'target_not_frozen'; target: OptimizationTarget }
  | { kind: 'error'; message: string }
  | { kind: 'no_candidate'; data: BaseData }
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

function CandidateSubmission({
  data,
  busy,
  error,
  onSubmit,
}: {
  data: BaseData
  busy: boolean
  error: string | null
  onSubmit: (label: string, summary: string, responses: CandidateResponseInput[]) => void
}) {
  const [label, setLabel] = useState('')
  const [summary, setSummary] = useState('')
  const [responsesJson, setResponsesJson] = useState('[]')
  const [parseError, setParseError] = useState<string | null>(null)

  function submit() {
    setParseError(null)
    try {
      const parsed: unknown = JSON.parse(responsesJson)
      if (!Array.isArray(parsed) || parsed.length === 0) {
        throw new Error('Candidate responses 必须是非空 JSON 数组。')
      }
      const responses = parsed.map((item) => {
        if (!item || typeof item !== 'object') throw new Error('每条 response 必须是对象。')
        const value = item as Record<string, unknown>
        if (![value.conversation_id, value.case_id, value.assistant_content].every((field) => typeof field === 'string' && field.trim())) {
          throw new Error('每条 response 必须包含非空 conversation_id、case_id、assistant_content。')
        }
        return {
          conversation_id: value.conversation_id as string,
          case_id: value.case_id as string,
          assistant_content: value.assistant_content as string,
        }
      })
      onSubmit(label, summary, responses)
    } catch (submissionError) {
      setParseError(submissionError instanceof Error ? submissionError.message : 'Candidate responses JSON 无效。')
    }
  }

  const scopeCount = data.target.target_case_ids.length + data.target.regression_case_ids.length + data.target.challenge_case_ids.length
  return (
    <section className="s05-page">
      <div className="s05-canvas s05-submit">
        <header>
          <span className="s05-eyebrow">FROZEN TARGET V{data.target.version}</span>
          <h1>提交 Candidate Responses</h1>
          <p>数据集：{data.dataset.name} {data.dataset.version} · 冻结范围 {scopeCount} Cases</p>
        </header>
        <label><span>Candidate label</span><input value={label} onChange={(event) => setLabel(event.target.value)} disabled={busy} /></label>
        <label><span>Change summary</span><textarea value={summary} onChange={(event) => setSummary(event.target.value)} disabled={busy} rows={3} /></label>
        <label><span>Candidate responses JSON</span><textarea className="s05-json-input" value={responsesJson} onChange={(event) => setResponsesJson(event.target.value)} disabled={busy} rows={16} spellCheck={false} /></label>
        <p className="s05-submit-note">每条仅允许 conversation_id / case_id / assistant_content；Backend 校验完整 Frozen scope 与 Case pairing。</p>
        {(parseError || error) && <p className="s05-form-error">{parseError ?? error}</p>}
        <button type="button" onClick={submit} disabled={busy || !label.trim() || !summary.trim()}>{busy ? '正在执行 Candidate Validation…' : '创建并执行 Candidate Validation'}</button>
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
          <article className="s05-outcome-card"><MdCheckCircle className="s05-outcome-icon" aria-hidden="true" /><div><h2>目标改善 ({target.id})</h2><dl><div><dt>Target outcome</dt><dd>{summary.target_outcome}</dd></div><div><dt>目标案例</dt><dd>{targetComparisons.length}</dd></div><div><dt>明确改善</dt><dd className="s05-positive">{movementCounts.improved}</dd></div><div><dt>部分改善</dt><dd>{movementCounts.partially_improved}</dd></div><div><dt>目标变差</dt><dd>{summary.rule_outcomes.target_worse_count}</dd></div><div><dt>无法得出结论</dt><dd>{movementCounts.inconclusive}</dd></div><div><dt>剩余目标 High/Critical</dt><dd>{summary.rule_outcomes.remaining_target_high_critical}</dd></div></dl></div></article>
          <article className="s05-outcome-card s05-regression-card"><MdVerified className="s05-outcome-icon" aria-hidden="true" /><div><h2>回归检查 ({comparisons.length - targetComparisons.length} 个非目标案例)</h2><div className="s05-regression-grid"><dl><div><dt>严重回归 CRITICAL</dt><dd>{summary.regression_summary.critical}</dd></div><div><dt>重大回归 MAJOR</dt><dd>{summary.regression_summary.major}</dd></div></dl><dl><div className="s05-minor-regression"><dt>轻微回归 MINOR</dt><dd>{summary.regression_summary.minor}</dd></div></dl><dl><div><dt>新系统性问题</dt><dd>{summary.new_systematic_problems.length}</dd></div><div><dt>Other Problems</dt><dd>{summary.other_problems.length}</dd></div><div><dt>剩余必需人工复核</dt><dd>{pendingReviewCount}</dd></div></dl></div><p>Regression 与 New Systematic Problem 均直接来自 Backend Validation Summary。</p></div></article>
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
          <article className="s05-recommendation"><span className="s05-eyebrow">系统建议 · {summary.policy_version}</span><h2>{summary.recommended_verdict}</h2><dl>{gates.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><p><span aria-hidden="true" />{summary.blockers.length ? `Blockers: ${summary.blockers.join(', ')}` : '所有 machine blockers 已通过；仍等待独立 Human Decision。'}</p></article>
          <article className="s05-human-decision"><header><span className="s05-eyebrow">人工最终决策</span><div><MdPerson aria-hidden="true" /><span>{candidateRun.decided_by ?? '尚未决定'}</span></div></header>{candidateRun.final_decision ? <dl><div><dt>决策</dt><dd>{candidateRun.final_decision}</dd></div><div><dt>决定时间</dt><dd>{formatDate(candidateRun.decided_at)}</dd></div><div><dt>理由</dt><dd>{candidateRun.reason}</dd></div><div><dt>Override reason</dt><dd>{candidateRun.override_reason ?? '未改判机器建议'}</dd></div></dl> : <><label><span>决策人</span><input value={actor} onChange={(event) => setActor(event.target.value)} disabled={decisionBusy} /></label><textarea aria-label="决策理由" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="必须填写决策理由。" disabled={decisionBusy} /><textarea aria-label="改判理由" value={overrideReason} onChange={(event) => setOverrideReason(event.target.value)} placeholder="与 Machine recommendation 不一致时必填 override_reason。" disabled={decisionBusy} />{decisionError && <p className="s05-form-error">{decisionError}</p>}</>}</article>
        </section>
        <section className="s05-claim-boundary" aria-label="结论边界"><strong>Case pairing：same dataset / conversation_id / case_id。</strong><em>结论仅适用于当前 Frozen Target、数据集、Judge 配置与 response set。</em><span>Human Decision 与 Machine recommendation 独立保存，不代表上线或部署。</span></section>
      </div>

      <footer className="s05-action-rail"><em>PLAN V{target.version} · {target.plan_hash}</em><div><button type="button" onClick={() => onDecision('continue', actor, reason, overrideReason)} disabled={decisionBusy || Boolean(candidateRun.final_decision) || !actor.trim() || !reason.trim()}>继续迭代</button><button type="button" onClick={() => onDecision('accept', actor, reason, overrideReason)} disabled={decisionBusy || Boolean(candidateRun.final_decision) || summary.recommended_verdict !== 'ACCEPT' || !actor.trim() || !reason.trim()}><MdVerified aria-hidden="true" />接受候选版本</button></div></footer>
      <div className="s05-analyst-dock"><MdPerson aria-hidden="true" /><strong>{candidateRun.decided_by ?? 'Human Decision'}</strong></div>
    </section>
  )
}

function CandidateValidationPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const targetId = searchParams.get('target_id')?.trim() ?? ''
  const candidateRunId = searchParams.get('candidate_run_id')?.trim() ?? ''
  const requestKey = `${targetId}:${candidateRunId}`
  const [loadResult, setLoadResult] = useState<{ requestKey: string; state: PageState }>(() => ({ requestKey, state: targetId ? { kind: 'loading' } : { kind: 'missing_target' } }))
  const [selectedCaseId, setSelectedCaseId] = useState('')
  const [submissionBusy, setSubmissionBusy] = useState(false)
  const [submissionError, setSubmissionError] = useState<string | null>(null)
  const [decisionBusy, setDecisionBusy] = useState(false)
  const [decisionError, setDecisionError] = useState<string | null>(null)

  useEffect(() => {
    if (!targetId) return
    const controller = new AbortController()
    async function load() {
      try {
        const target = await getOptimizationTarget(targetId, controller.signal)
        if (target.status !== 'frozen') {
          setLoadResult({ requestKey, state: { kind: 'target_not_frozen', target } })
          return
        }
        const baselineRun = await getEvaluationRun(target.baseline_run_id, controller.signal)
        const [dataset, conversations] = await Promise.all([getDatasetDetail(baselineRun.dataset_id, controller.signal), getDatasetConversations(baselineRun.dataset_id, controller.signal)])
        const base = { target, baselineRun, dataset, conversations }
        if (!candidateRunId) {
          setLoadResult({ requestKey, state: { kind: 'no_candidate', data: base } })
          return
        }
        const candidateRun = await getEvaluationRun(candidateRunId, controller.signal)
        if (candidateRun.run_type !== 'candidate' || candidateRun.target_id !== target.id) {
          setLoadResult({ requestKey, state: { kind: 'candidate_not_found' } })
          return
        }
        const [baselineResults, candidateResults, comparisons, summary] = await Promise.all([getFinalEffectiveResults(baselineRun.id, controller.signal), getFinalEffectiveResults(candidateRun.id, controller.signal), getCandidateComparisons(candidateRun.id, controller.signal), getCandidateValidationSummary(candidateRun.id, controller.signal)])
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
        setLoadResult({ requestKey, state: { kind: 'error', message: error instanceof Error ? error.message : '无法加载 Candidate Validation。' } })
      }
    }
    void load()
    return () => controller.abort()
  }, [candidateRunId, requestKey, targetId])

  const pageState: PageState = !targetId ? { kind: 'missing_target' } : loadResult.requestKey === requestKey ? loadResult.state : { kind: 'loading' }

  async function submitCandidate(label: string, summary: string, responses: CandidateResponseInput[]) {
    if (pageState.kind !== 'no_candidate' || !pageState.data.target.plan_hash) return
    setSubmissionBusy(true)
    setSubmissionError(null)
    let createdId = ''
    try {
      const candidate = await createCandidateRun({ baseline_run_id: pageState.data.baselineRun.id, target_id: pageState.data.target.id, plan_hash: pageState.data.target.plan_hash, candidate_label: label.trim(), candidate_change_summary: summary.trim(), source: 's05_manual_submission', actual_change_summary: summary.trim(), actual_change_status: 'verified', generation_parity_status: 'verified', candidate_first_exposure_at: new Date().toISOString(), responses })
      createdId = candidate.id
      const executed = await executeCandidateRun(candidate.id)
      if (executed.status !== 'completed') throw new Error(`Candidate Run 结束于 ${executed.status}，尚不能生成 Comparison。`)
      await createCandidateComparisons(candidate.id)
      setSearchParams({ target_id: targetId, candidate_run_id: candidate.id })
    } catch (error) {
      setSubmissionError(`${error instanceof Error ? error.message : 'Candidate Validation 执行失败。'}${createdId ? ` Candidate Run: ${createdId}` : ''}`)
    } finally {
      setSubmissionBusy(false)
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
  if (pageState.kind === 'target_not_frozen') return <PageMessage title="Target 尚未冻结" detail={`当前状态为 ${pageState.target.status}，必须先在 S04 Freeze。`} />
  if (pageState.kind === 'error') return <PageMessage title="Candidate Validation 加载失败" detail={pageState.message} />
  if (pageState.kind === 'no_candidate') return <CandidateSubmission data={pageState.data} busy={submissionBusy} error={submissionError} onSubmit={(label, summary, responses) => { void submitCandidate(label, summary, responses) }} />
  return <CandidateWorkspace data={pageState.data} selectedCaseId={selectedCaseId} onSelectCase={setSelectedCaseId} decisionBusy={decisionBusy} decisionError={decisionError} onDecision={(decision, actor, reason, overrideReason) => { void submitDecision(decision, actor, reason, overrideReason) }} />
}

export default CandidateValidationPage
