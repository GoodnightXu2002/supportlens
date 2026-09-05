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
import { useSearchParams } from 'react-router-dom'

import {
  ApiRequestError,
  getDatasetConversations,
  getDatasetDetail,
  getEvaluationRun,
  getFinalEffectiveResults,
  getProblems,
  type DatasetConversation,
  type DatasetDetail,
  type EvaluationRun,
  type FinalEffectiveResult,
  type JudgeOutput,
  type Problem,
} from '../api'
import './BaselineAnalysisPage.css'

type LoadedData = {
  run: EvaluationRun
  dataset: DatasetDetail
  conversations: DatasetConversation[]
  finalResults: FinalEffectiveResult[]
  problems: Problem[]
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
  return value === null ? '不可用' : signalLabels[value]
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

function CaseStatus({ result }: { result: FinalEffectiveResult }) {
  if (result.status === 'pending_review') {
    return (
      <MdError
        className="s03-status-icon s03-status-icon--warning"
        aria-label="需要人工复核"
      />
    )
  }

  return (
    <MdCheckCircle
      className="s03-status-icon s03-status-icon--success"
      aria-label={result.source === 'human' ? '人工复核后生效' : 'Machine Final'}
    />
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
  const [searchParams] = useSearchParams()
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
  const [selectedProblemId, setSelectedProblemId] = useState<string | null>(null)
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null)
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

        const [dataset, conversations, finalResults, problems] = await Promise.all([
          getDatasetDetail(run.dataset_id, controller.signal),
          getDatasetConversations(run.dataset_id, controller.signal),
          getFinalEffectiveResults(run.id, controller.signal),
          getProblems(run.id, controller.signal),
        ])
        setLoadResult({
          runId,
          state: {
            kind: 'ready',
            data: { run, dataset, conversations, finalResults, problems },
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
  const selectedProblem = (
    problems.find((problem) => problem.problem_id === selectedProblemId)
    ?? problems[0]
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
  const affectedResults = selectedProblem?.affected_evaluation_result_ids
    .map((resultId) => finalResultById.get(resultId))
    .filter((result): result is FinalEffectiveResult => result !== undefined)
    ?? []
  const selectedResult = (
    affectedResults.find((result) => result.evaluation_result_id === selectedResultId)
    ?? affectedResults[0]
  )
  const selectedConversation = selectedResult
    ? conversationById.get(selectedResult.conversation_id)
    : undefined
  const selectedEvidence = selectedProblem && selectedResult
    ? selectedProblem.evidence.filter(
        (item) => item.evaluation_result_id === selectedResult.evaluation_result_id,
      )
    : []

  if (pageState.kind === 'missing_run_id') {
    return (
      <PageMessage
        title="缺少 Evaluation Run"
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
        title="Evaluation Run 不存在"
        detail={`未找到 run_id=${runId} 对应的评测运行。`}
      />
    )
  }
  if (pageState.kind === 'aggregation_not_completed') {
    return (
      <PageMessage
        title="Problem Aggregation 尚未完成"
        detail={`Run ${shortId(pageState.run.id)} 当前不能展示正式 Problem 数据。`}
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
              <p>{pendingReviewCount === 0 ? 'REVIEW-CLEARED' : `PENDING-REVIEW: ${pendingReviewCount}`}</p>
            </div>
          </div>

          <span className="s03-review-strip__divider" aria-hidden="true" />

          <dl className="s03-metadata">
            <div>
              <dt>数据集</dt>
              <dd title={`${data.dataset.name} ${data.dataset.version}`}>
                {data.dataset.name} {data.dataset.version}
              </dd>
            </div>
            <div>
              <dt>Evaluation Run</dt>
              <dd title={`${data.run.id} · ${data.run.run_source} · ${data.run.created_at}`}>
                {shortId(data.run.id)} · {data.run.status}
              </dd>
            </div>
            <div>
              <dt>数据类型</dt>
              <dd>{data.dataset.privacy_status} · {data.dataset.source}</dd>
            </div>
            <div className="s03-metadata__type">
              <dt>Judge</dt>
              <dd title={data.run.judge_model}>{data.run.judge_contract_version}</dd>
            </div>
            <div>
              <dt>声明范围</dt>
              <dd title={data.dataset.representativeness_statement ?? undefined}>
                {data.dataset.representativeness_statement ?? '未提供代表性声明'}
              </dd>
            </div>
          </dl>
        </div>

        <button className="s03-review-action" type="button" disabled>
          {pendingReviewCount === 0 ? '无需人工复核' : `待复核 ${pendingReviewCount}`}
        </button>
      </div>

      <div className="s03-workspace">
        <section className="s03-pane s03-problems" aria-labelledby="s03-problems-title">
          <header className="s03-pane-header">
            <h2 id="s03-problems-title">问题聚类（{problems.length}）</h2>
            <button className="s03-icon-button" type="button" aria-label="筛选问题聚类" disabled>
              <MdFilterList aria-hidden="true" />
            </button>
          </header>

          <div className="s03-pane-scroll s03-problem-list">
            {problems.length === 0 ? (
              <p className="s03-empty-message">Problem Aggregation 已完成，本 Run 没有可展示的 Problem。</p>
            ) : problems.map((problem) => {
              const isActive = problem.problem_id === selectedProblem?.problem_id
              const frequencyPercent = problem.frequency.denominator === 0
                ? null
                : (problem.frequency.numerator / problem.frequency.denominator) * 100
              return (
                <article
                  className={isActive
                    ? 's03-problem-card s03-problem-card--active'
                    : 's03-problem-card'}
                  key={problem.problem_id}
                  onClick={() => {
                    setSelectedProblemId(problem.problem_id)
                    setSelectedResultId(null)
                  }}
                >
                  <div className="s03-problem-card__topline">
                    <span
                      className={isActive ? 's03-code-label s03-code-label--strong' : 's03-code-label'}
                      title={problem.problem_id}
                    >
                      {problem.scenario} · P-{shortId(problem.problem_id)}
                    </span>
                    <span className={isActive ? 's03-count-badge s03-count-badge--active' : 's03-count-badge'}>
                      {problem.affected_case_count} 个案例
                    </span>
                  </div>
                  <h3>{problem.definition}</h3>
                  {isActive ? (
                    <>
                      <dl className="s03-priority-grid">
                        <div><dt><span className="s03-dot s03-dot--critical" aria-hidden="true" />严重程度：</dt><dd>{problem.priority_severity ? severityLabels[problem.priority_severity] : '不可用'}</dd></div>
                        <div><dt><span className="s03-dot s03-dot--critical" aria-hidden="true" />业务影响：</dt><dd>{signalLabel(problem.business_impact)}</dd></div>
                        <div className="s03-priority-grid__frequency"><dt><span className="s03-dot s03-dot--secondary" aria-hidden="true" />频率：</dt><dd>{problem.frequency.numerator}/{problem.frequency.denominator}{frequencyPercent === null ? '' : ` (${frequencyPercent.toFixed(1)}%)`}</dd></div>
                        <div><dt><span className="s03-dot s03-dot--info" aria-hidden="true" />模式一致性：</dt><dd>{signalLabel(problem.pattern_consistency)}</dd></div>
                        <div className="s03-priority-grid__wide"><dt><span className="s03-dot s03-dot--info" aria-hidden="true" />证据置信度：</dt><dd>{signalLabel(problem.evidence_confidence)}</dd></div>
                      </dl>
                      <p className="s03-profile-detail">
                        Severity Distribution：L {problem.severity_distribution.low} / M {problem.severity_distribution.medium} / H {problem.severity_distribution.high} / C {problem.severity_distribution.critical}
                      </p>
                      <p className="s03-ranking-detail">
                        {problem.rank !== null
                          ? `Dense Rank ${problem.rank}${problem.equal_review_priority ? ' · Equal Review Priority' : ''}`
                          : `不可排名${problem.ranking_blockers.length > 0 ? `：${problem.ranking_blockers.join(', ')}` : ''}`}
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
            <h2 id="s03-cases-title">受影响案例（{affectedResults.length}）</h2>
            <p>{selectedProblem ? `P-${shortId(selectedProblem.problem_id)} 案例下钻` : '暂无 Problem'}</p>
          </header>

          <div className="s03-pane-scroll s03-case-list">
            {selectedProblem ? (
              <>
                <div className="s03-case-grid s03-case-table-head" aria-hidden="true">
                  <span>案例 ID</span><span>意图摘要</span><span>状态</span>
                </div>
                <div className="s03-case-rows">
                  {affectedResults.map((result) => {
                    const conversation = conversationById.get(result.conversation_id)
                    const isActive = result.evaluation_result_id === selectedResult?.evaluation_result_id
                    return (
                      <article
                        className={isActive
                          ? 's03-case-grid s03-case-row s03-case-row--active'
                          : 's03-case-grid s03-case-row'}
                        key={result.evaluation_result_id}
                        onClick={() => setSelectedResultId(result.evaluation_result_id)}
                      >
                        <span className="s03-case-id">
                          {isActive ? <span className="s03-case-id__rail" aria-hidden="true" /> : null}
                          {result.case_id}
                        </span>
                        <span className="s03-case-summary" title={caseSummary(conversation)}>{caseSummary(conversation)}</span>
                        <span className="s03-case-status"><CaseStatus result={result} /></span>
                      </article>
                    )
                  })}
                </div>
              </>
            ) : (
              <p className="s03-empty-message">没有可下钻的受影响案例。</p>
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
              <p className="s03-empty-message">选择一个 Problem 和 Case 后查看证据链。</p>
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
                    <h3>节点 2 / 基线回复</h3>
                    {assistantMessages.map((message, index) => (
                      <blockquote key={`${selectedConversation.id}-assistant-${index}`}>{message.content}</blockquote>
                    ))}
                  </div>
                </article>

                <article className="s03-evidence-node">
                  <span className="s03-node-marker s03-node-marker--icon"><MdSmartToy aria-hidden="true" /></span>
                  <div className="s03-node-content">
                    <h3 className="s03-node-title--italic">节点 3 / Machine 原始判定</h3>
                    <div className="s03-ai-judgment">
                      <div className="s03-ai-judgment__status">
                        <span>判定：{judgmentLabels[selectedResult.machine_result.judgment]}</span>
                        <span>{selectedResult.machine_result.primary_failure_mode ?? '无 Primary Failure Mode'}</span>
                      </div>
                      <p>Problem：{selectedResult.machine_result.problem ?? '无'}</p>
                      <p>
                        Severity：{selectedResult.machine_result.severity ? severityLabels[selectedResult.machine_result.severity] : '不可用'}
                        {' · '}Review Required：{String(selectedResult.machine_result.review_required)}
                      </p>
                      {selectedResult.machine_result.secondary_flags.length > 0 ? (
                        <p>Secondary Flags：{selectedResult.machine_result.secondary_flags.join(', ')}</p>
                      ) : null}
                      {selectedResult.machine_result.uncertainty ? (
                        <p>Uncertainty：{selectedResult.machine_result.uncertainty}</p>
                      ) : null}
                      <p>{selectedResult.machine_result.rationale}</p>
                      {selectedResult.machine_result.evidence.length > 0 ? (
                        <ul>{selectedResult.machine_result.evidence.map((item, index) => <li key={`${selectedResult.evaluation_result_id}-machine-${index}`}>{item.evidence_type}: {item.content}{item.source_ref ? ` (${item.source_ref})` : ''}</li>)}</ul>
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
                    ) : <p className="s03-evidence-empty">Final Effective Result 未提供 Case Fact evidence。</p>}
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
                    {!referenceEvidence && referenceItems.length === 0 ? <p className="s03-evidence-empty">未提供可追溯 Reference evidence。</p> : null}
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
                            {isHumanCorrection ? '已修正 Machine 判定' : '已确认 Machine 判定'}
                          </p>
                          <div><span>复核人 / 时间</span><p>{selectedResult.human_decision.reviewer} · {formatDate(selectedResult.human_decision.reviewed_at)}</p></div>
                          <div><span>复核理由</span><p>{selectedResult.human_decision.change_reason ?? '结论未修改，无 change reason。'}</p></div>
                        </>
                      ) : (
                        <p className="s03-human-review__decision">
                          {selectedResult.status === 'pending_review' ? '等待人工复核' : 'Machine Final / 无人工复核'}
                        </p>
                      )}
                    </div>
                  </div>
                </article>

                <article className="s03-evidence-node">
                  <span className="s03-node-marker s03-node-marker--final"><MdGavel aria-hidden="true" /></span>
                  <div className="s03-node-content">
                    <h3>节点 7 / 最终生效结果</h3>
                    <div className="s03-final-result">
                      <div><span>最终判定</span><strong>{selectedResult.final_result ? judgmentLabels[selectedResult.final_result.judgment] : 'Pending Review'}</strong></div>
                      <div><span>记录状态</span><em>{selectedResult.status === 'final' ? `${selectedResult.source === 'human' ? 'Human' : 'Machine'} Final` : 'Pending Review'}</em></div>
                      {selectedResult.final_result ? (
                        <p>
                          Problem：{selectedResult.final_result.problem ?? '无'}<br />
                          Severity：{selectedResult.final_result.severity ? severityLabels[selectedResult.final_result.severity] : '不可用'} · {selectedResult.final_result.primary_failure_mode ?? '无 Primary Failure Mode'}
                        </p>
                      ) : null}
                      <p>{selectedResult.final_result?.rationale ?? '人工复核完成前不存在 Final Effective Result。'}</p>
                      {selectedResult.final_result?.evidence.length ? (
                        <ul>{selectedResult.final_result.evidence.map((item, index) => <li key={`${selectedResult.evaluation_result_id}-final-${index}`}>{item.evidence_type}: {item.content}{item.source_ref ? ` (${item.source_ref})` : ''}</li>)}</ul>
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
        <div className="s03-analyst"><strong title={data.run.id}>Run {shortId(data.run.id)}</strong></div>
        <div className="s03-bottom-actions">
          <span>{pendingReviewCount === 0 ? `${data.finalResults.length} 个 Final Effective Results` : `剩余 ${pendingReviewCount} 个案例待复核`}</span>
          <button type="button" disabled>进入目标与计划</button>
        </div>
      </footer>
    </section>
  )
}

export default BaselineAnalysisPage
