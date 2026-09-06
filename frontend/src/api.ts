export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
).replace(/\/$/, '')

export type PrivacyStatus =
  | 'unknown'
  | 'synthetic'
  | 'deidentified'
  | 'may_contain_personal_data'

export type ImportErrorDetail = {
  row?: number | null
  item_index?: number | null
  field: string
  code: string
  message: string
}

export type PreviewConversation = {
  external_id: string
  messages: Array<{
    role: 'user' | 'assistant'
    content: string
  }>
  metadata: Record<string, unknown>
}

export type ImportPreviewResponse = {
  import_token: string
  dataset_identity: {
    name: string
    description: string | null
    version: string
    source: 'user_upload'
    privacy_status: PrivacyStatus
    representativeness_statement: string | null
  }
  total_conversation_count: number
  scenario_distribution: Record<string, number>
  preview_conversations: PreviewConversation[]
}

export type ImportConfirmResponse = {
  dataset_id: string
  name: string
  version: string
  source: 'user_upload'
  privacy_status: PrivacyStatus
  representativeness_statement: string | null
  conversation_count: number
  created_at: string
}

export type DatasetListItem = {
  dataset_id: string
  name: string
  description: string | null
  version: string
  source: 'user_upload' | 'fixture_import'
  privacy_status: PrivacyStatus
  representativeness_statement: string | null
  conversation_count: number
  created_at: string
}

export type DatasetDetail = DatasetListItem & {
  scenario_distribution: Record<string, number>
}

export type DatasetConversation = {
  id: string
  external_id: string
  messages: Array<{
    role: 'user' | 'assistant'
    content: string
  }>
  metadata: Record<string, unknown> | null
  created_at: string
}

export type EvaluationRun = {
  id: string
  dataset_id: string
  run_type: 'baseline' | 'candidate'
  status:
    | 'pending'
    | 'running'
    | 'completed'
    | 'partial_failure'
    | 'failed'
    | 'invalid'
  baseline_run_id: string | null
  target_id: string | null
  candidate_label: string | null
  candidate_change_summary: string | null
  judge_model: string
  judge_contract_version: string
  run_source: 'seed' | 'live'
  response_set_key: string
  error_code: string | null
  error_message: string | null
  problem_aggregation_completed_at: string | null
  candidate_responses_snapshot: CandidateResponseInput[] | null
  response_set_hash: string | null
  candidate_manifest_snapshot: Record<string, unknown> | null
  candidate_validation_summary: CandidateValidationSummary | null
  final_decision: 'accept' | 'continue' | null
  decided_by: string | null
  decided_at: string | null
  reason: string | null
  override_reason: string | null
  created_at: string
}

export type JudgeEvidence = {
  evidence_type: 'response' | 'case_fact' | 'reference'
  content: string
  source_ref: string | null
}

export type JudgeOutput = {
  judgment: 'success' | 'warning' | 'failure' | 'uncertain'
  primary_failure_mode:
    | 'incorrect_information'
    | 'incomplete_unresolved'
    | 'intent_relevance_failure'
    | 'improper_refusal'
    | 'policy_procedure_violation'
    | 'other'
    | null
  secondary_flags: Array<Exclude<JudgeOutput['primary_failure_mode'], null>>
  problem: string | null
  severity: 'low' | 'medium' | 'high' | 'critical' | null
  evidence: JudgeEvidence[]
  uncertainty: string | null
  review_required: boolean | null
  rationale: string
}

export type HumanDecision = {
  id: string
  evaluation_result_id: string
  reviewer: string
  reviewed_at: string
  original_result: JudgeOutput
  final_result: JudgeOutput
  change_reason: string | null
}

export type FinalEffectiveResult = {
  evaluation_result_id: string
  conversation_id: string
  case_id: string
  status: 'final' | 'pending_review'
  source: 'machine' | 'human' | null
  machine_result: JudgeOutput
  final_result: JudgeOutput | null
  human_decision_id: string | null
  human_decision: HumanDecision | null
}

export type ProblemEvidence = {
  problem_id: string
  evaluation_result_id: string
  conversation_id: string
  case_id: string
  evidence_type: JudgeEvidence['evidence_type']
  content: string
  source_ref: string | null
}

export type Problem = {
  problem_id: string
  evaluation_run_id: string
  scenario: string
  definition: string
  mapping_key: string
  mapping_version: string
  created_at: string
  affected_case_count: number
  affected_evaluation_result_ids: string[]
  affected_case_ids: string[]
  evidence: ProblemEvidence[]
  profile_version: 'BASELINE-PROBLEM-PROFILE-V1'
  frequency: { numerator: number; denominator: number }
  severity_distribution: {
    low: number
    medium: number
    high: number
    critical: number
  }
  priority_severity: JudgeOutput['severity']
  business_impact: 'high' | 'medium' | 'low' | null
  business_impact_status: 'mapped' | 'unmapped'
  business_impact_mapping_version: string
  review_status: 'cleared' | 'pending'
  evidence_sufficiency: 'sufficient' | 'insufficient'
  evidence_confidence: 'high' | 'medium' | 'unknown' | null
  reference_conflict_status: 'clear' | 'present' | 'unsupported'
  pattern_consistency: 'strong' | 'moderate' | 'weak' | null
  individual_risk_issue: boolean
  ranking_eligible: boolean
  ranking_blockers: string[]
  rank: number | null
  equal_review_priority: boolean | null
}

export type OptimizationTarget = {
  id: string
  baseline_run_id: string
  problem_id: string
  version: number
  status: 'draft' | 'confirmed' | 'frozen'
  definition: string
  inclusion_criteria: string
  exclusion_criteria: string
  baseline_affected_case_ids: string[]
  reference_basis: ProblemEvidence[]
  failure_mode: NonNullable<JudgeOutput['primary_failure_mode']>
  baseline_metric: {
    affected_core_cases: number
    core_denominator: number
    frequency: { numerator: number; denominator: number }
  }
  expected_observable_change: string
  confirmed_by: string | null
  confirmed_at: string | null
  hypothesis_confirmed_by: string | null
  hypothesis_confirmed_at: string | null
  hypothesis_statement: string | null
  hypothesis_evidence_refs: string[]
  change_surface: string | null
  planned_change: string | null
  guardrails: string[]
  change_status: 'planned'
  target_case_ids: string[]
  regression_case_ids: string[]
  challenge_case_ids: string[]
  protected_capabilities: string[]
  baseline_snapshot: {
    problem_id: string
    definition: string
    scenario: string
    priority_severity: JudgeOutput['severity']
    business_impact: 'high' | 'medium' | 'low' | null
    frequency: { numerator: number; denominator: number }
    pattern_consistency: 'strong' | 'moderate' | 'weak' | null
    evidence_confidence: 'high' | 'medium' | 'unknown' | null
    affected_case_ids: string[]
  }
  evaluation_config_snapshot: Record<string, unknown>
  policy_version: string | null
  plan_hash: string | null
  frozen_by: string | null
  frozen_at: string | null
  created_at: string
  updated_at: string
}

export type OptimizationTargetCreateInput = {
  definition: string
  inclusion_criteria: string
  exclusion_criteria: string
  expected_observable_change: string
  hypothesis_statement?: string | null
  hypothesis_evidence_refs?: string[]
  change_surface?: string | null
  planned_change?: string | null
  guardrails?: string[]
  protected_capabilities?: string[]
  policy_version?: string | null
}

export type OptimizationTargetPatchInput = Partial<
  OptimizationTargetCreateInput
>

export type CandidateResponseInput = {
  conversation_id: string
  case_id: string
  assistant_content: string
}

export type CandidateRunCreateInput = {
  baseline_run_id: string
  target_id: string
  plan_hash: string
  candidate_label: string
  candidate_change_summary: string
  source: string
  actual_change_summary: string
  actual_change_status: 'verified'
  generation_parity_status: 'verified'
  candidate_first_exposure_at: string
  responses: CandidateResponseInput[]
}

export type CaseComparison = {
  id: string
  baseline_run_id: string
  candidate_run_id: string
  target_id: string
  conversation_id: string
  case_id: string
  baseline_evaluation_result_id: string
  candidate_evaluation_result_id: string
  movement:
    | 'improved'
    | 'partially_improved'
    | 'stable'
    | 'regressed'
    | 'inconclusive'
  target_problem_status: 'present' | 'absent' | 'not_applicable' | 'inconclusive'
  target_worse: boolean
  regression_level: 'critical' | 'major' | 'minor' | null
  evidence_snapshot: {
    baseline: JudgeEvidence[] | null
    candidate: JudgeEvidence[] | null
  }
  rule_result_snapshot: Record<string, unknown>
  created_at: string
}

export type CandidateValidationSummary = {
  candidate_run_id: string
  baseline_run_id: string
  target_id: string
  target_outcome: 'resolved' | 'improved' | 'not_improved' | 'inconclusive'
  regression_summary: {
    critical: number
    major: number
    minor: number
  }
  other_problems: Array<Record<string, unknown>>
  new_systematic_problems: Array<Record<string, unknown>>
  review_complete: boolean
  integrity_gate: 'passed' | 'failed'
  compatibility_gate: 'passed' | 'failed'
  protected_capability_gate: 'not_applicable' | 'unsupported'
  recommended_verdict: 'ACCEPT' | 'CONTINUE' | 'INCONCLUSIVE'
  policy_version: string
  rule_outcomes: {
    target_case_count: number
    clear_improved_count: number
    improvement_threshold: number
    target_worse_count: number
    remaining_target_high_critical: number
  }
  blockers: string[]
}

export type CandidateFinalDecisionInput = {
  final_decision: 'accept' | 'continue'
  decided_by: string
  reason: string
  override_reason?: string | null
}

export class ApiRequestError extends Error {
  readonly code: string
  readonly details: ImportErrorDetail[]
  readonly status: number

  constructor(
    message: string,
    code: string,
    status: number,
    details: ImportErrorDetail[] = [],
  ) {
    super(message)
    this.name = 'ApiRequestError'
    this.code = code
    this.details = details
    this.status = status
  }
}

type ErrorEnvelope = {
  error?: {
    code?: string
    message?: string
    details?: ImportErrorDetail[] | null
  }
}

async function requestJson<T>(response: Response): Promise<T> {
  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (response.ok) {
    return payload as T
  }

  const apiError = (payload as ErrorEnvelope | null)?.error
  throw new ApiRequestError(
    apiError?.message ?? `请求失败（HTTP ${response.status}）。`,
    apiError?.code ?? 'request_failed',
    response.status,
    Array.isArray(apiError?.details) ? apiError.details : [],
  )
}

export async function previewDatasetImport(input: {
  file: File
  name: string
  description: string
  version: string
  privacyStatus: PrivacyStatus
  representativenessStatement: string
}): Promise<ImportPreviewResponse> {
  const body = new FormData()
  body.append('file', input.file)
  body.append('name', input.name)
  body.append('version', input.version)
  body.append('source', 'user_upload')
  body.append('privacy_status', input.privacyStatus)
  if (input.description) body.append('description', input.description)
  if (input.representativenessStatement) {
    body.append(
      'representativeness_statement',
      input.representativenessStatement,
    )
  }

  return requestJson<ImportPreviewResponse>(
    await fetch(`${API_BASE_URL}/api/dataset-imports/preview`, {
      method: 'POST',
      body,
    }),
  )
}

export async function confirmDatasetImport(
  importToken: string,
): Promise<ImportConfirmResponse> {
  return requestJson<ImportConfirmResponse>(
    await fetch(`${API_BASE_URL}/api/dataset-imports/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ import_token: importToken }),
    }),
  )
}

export async function getDatasets(
  signal?: AbortSignal,
): Promise<DatasetListItem[]> {
  return requestJson<DatasetListItem[]>(
    await fetch(`${API_BASE_URL}/api/datasets`, { signal }),
  )
}

export async function getDatasetDetail(
  datasetId: string,
  signal?: AbortSignal,
): Promise<DatasetDetail> {
  return requestJson<DatasetDetail>(
    await fetch(`${API_BASE_URL}/api/datasets/${encodeURIComponent(datasetId)}`, {
      signal,
    }),
  )
}

export async function getDatasetConversations(
  datasetId: string,
  signal?: AbortSignal,
): Promise<DatasetConversation[]> {
  return requestJson<DatasetConversation[]>(
    await fetch(
      `${API_BASE_URL}/api/datasets/${encodeURIComponent(datasetId)}/conversations`,
      { signal },
    ),
  )
}

export async function getEvaluationRun(
  runId: string,
  signal?: AbortSignal,
): Promise<EvaluationRun> {
  return requestJson<EvaluationRun>(
    await fetch(
      `${API_BASE_URL}/api/evaluation-runs/${encodeURIComponent(runId)}`,
      { signal },
    ),
  )
}

export async function createBaselineRun(
  datasetId: string,
): Promise<EvaluationRun> {
  return requestJson<EvaluationRun>(
    await fetch(`${API_BASE_URL}/api/evaluation-runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset_id: datasetId, run_type: 'baseline' }),
    }),
  )
}

export async function executeBaselineRun(
  runId: string,
): Promise<EvaluationRun> {
  return requestJson<EvaluationRun>(
    await fetch(
      `${API_BASE_URL}/api/evaluation-runs/${encodeURIComponent(runId)}/execute-baseline`,
      { method: 'POST' },
    ),
  )
}

export async function getDatasetEvaluationRuns(
  datasetId: string,
  signal?: AbortSignal,
): Promise<EvaluationRun[]> {
  return requestJson<EvaluationRun[]>(
    await fetch(
      `${API_BASE_URL}/api/datasets/${encodeURIComponent(datasetId)}/evaluation-runs`,
      { signal },
    ),
  )
}

export async function getFinalEffectiveResults(
  runId: string,
  signal?: AbortSignal,
): Promise<FinalEffectiveResult[]> {
  return requestJson<FinalEffectiveResult[]>(
    await fetch(
      `${API_BASE_URL}/api/evaluation-runs/${encodeURIComponent(runId)}/final-effective-results`,
      { signal },
    ),
  )
}

export async function getProblems(
  runId: string,
  signal?: AbortSignal,
): Promise<Problem[]> {
  return requestJson<Problem[]>(
    await fetch(
      `${API_BASE_URL}/api/evaluation-runs/${encodeURIComponent(runId)}/problems`,
      { signal },
    ),
  )
}

export async function getOptimizationTarget(
  targetId: string,
  signal?: AbortSignal,
): Promise<OptimizationTarget> {
  return requestJson<OptimizationTarget>(
    await fetch(
      `${API_BASE_URL}/api/optimization-targets/${encodeURIComponent(targetId)}`,
      { signal },
    ),
  )
}

export async function getOptimizationTargets(
  runId: string,
  signal?: AbortSignal,
): Promise<OptimizationTarget[]> {
  return requestJson<OptimizationTarget[]>(
    await fetch(
      `${API_BASE_URL}/api/evaluation-runs/${encodeURIComponent(runId)}/optimization-targets`,
      { signal },
    ),
  )
}

export async function createOptimizationTarget(
  runId: string,
  problemId: string,
  input: OptimizationTargetCreateInput,
): Promise<OptimizationTarget> {
  return requestJson<OptimizationTarget>(
    await fetch(
      `${API_BASE_URL}/api/evaluation-runs/${encodeURIComponent(runId)}/problems/${encodeURIComponent(problemId)}/optimization-targets`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      },
    ),
  )
}

export async function patchOptimizationTarget(
  targetId: string,
  input: OptimizationTargetPatchInput,
): Promise<OptimizationTarget> {
  return requestJson<OptimizationTarget>(
    await fetch(
      `${API_BASE_URL}/api/optimization-targets/${encodeURIComponent(targetId)}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      },
    ),
  )
}

async function submitOptimizationTargetActorAction(
  targetId: string,
  action: 'confirm-target' | 'confirm-hypothesis' | 'freeze',
  actor: string,
): Promise<OptimizationTarget> {
  return requestJson<OptimizationTarget>(
    await fetch(
      `${API_BASE_URL}/api/optimization-targets/${encodeURIComponent(targetId)}/${action}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor }),
      },
    ),
  )
}

export function confirmOptimizationTarget(
  targetId: string,
  actor: string,
): Promise<OptimizationTarget> {
  return submitOptimizationTargetActorAction(targetId, 'confirm-target', actor)
}

export function confirmOptimizationHypothesis(
  targetId: string,
  actor: string,
): Promise<OptimizationTarget> {
  return submitOptimizationTargetActorAction(
    targetId,
    'confirm-hypothesis',
    actor,
  )
}

export function freezeOptimizationTarget(
  targetId: string,
  actor: string,
): Promise<OptimizationTarget> {
  return submitOptimizationTargetActorAction(targetId, 'freeze', actor)
}

export async function createCandidateRun(
  input: CandidateRunCreateInput,
): Promise<EvaluationRun> {
  return requestJson<EvaluationRun>(
    await fetch(`${API_BASE_URL}/api/evaluation-runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }),
  )
}

export async function executeCandidateRun(
  runId: string,
): Promise<EvaluationRun> {
  return requestJson<EvaluationRun>(
    await fetch(
      `${API_BASE_URL}/api/evaluation-runs/${encodeURIComponent(runId)}/execute-candidate`,
      { method: 'POST' },
    ),
  )
}

export async function createCandidateComparisons(
  runId: string,
): Promise<CaseComparison[]> {
  return requestJson<CaseComparison[]>(
    await fetch(
      `${API_BASE_URL}/api/evaluation-runs/${encodeURIComponent(runId)}/case-comparisons`,
      { method: 'POST' },
    ),
  )
}

export async function getCandidateComparisons(
  runId: string,
  signal?: AbortSignal,
): Promise<CaseComparison[]> {
  return requestJson<CaseComparison[]>(
    await fetch(
      `${API_BASE_URL}/api/evaluation-runs/${encodeURIComponent(runId)}/case-comparisons`,
      { signal },
    ),
  )
}

export async function getCandidateValidationSummary(
  runId: string,
  signal?: AbortSignal,
): Promise<CandidateValidationSummary> {
  return requestJson<CandidateValidationSummary>(
    await fetch(
      `${API_BASE_URL}/api/evaluation-runs/${encodeURIComponent(runId)}/candidate-validation-summary`,
      { signal },
    ),
  )
}

export async function submitCandidateFinalDecision(
  runId: string,
  input: CandidateFinalDecisionInput,
): Promise<EvaluationRun> {
  return requestJson<EvaluationRun>(
    await fetch(
      `${API_BASE_URL}/api/evaluation-runs/${encodeURIComponent(runId)}/final-decision`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      },
    ),
  )
}
