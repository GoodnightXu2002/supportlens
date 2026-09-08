import type { EvaluationRun, FinalEffectiveResult, JudgeOutput, Problem } from './api'

export type ProblemSelectionCase = {
  resultId: string
  caseId: string
  caseSet: unknown
  judgment: JudgeOutput['judgment']
  primaryFailureMode: JudgeOutput['primary_failure_mode']
}

export function getProblemSelectionBlocker(cases: ProblemSelectionCase[]) {
  const coreCases = cases.filter((item) => item.caseSet === 'core')
  if (coreCases.length === 0) return '仅出现在挑战案例中，不能纳入本轮优化。'

  const failureModes = coreCases
    .filter((item) => item.judgment === 'failure')
    .map((item) => item.primaryFailureMode)
  if (failureModes.some((mode) => mode === null) || new Set(failureModes).size > 1) {
    return 'Core Failure 没有唯一的 Primary Failure Mode。'
  }
  return coreCases.some((item) => item.judgment === 'warning' || item.judgment === 'failure')
    ? null
    : '没有可纳入本轮优化的 Core Warning 或 Core Failure。'
}

export function getSelectedCoreCases(
  selectedProblemIds: string[],
  casesByProblemId: Map<string, ProblemSelectionCase[]>,
) {
  const selectedCases = new Map<string, { resultId: string; problemIds: string[] }>()
  selectedProblemIds.forEach((problemId) => {
    (casesByProblemId.get(problemId) ?? [])
      .filter((item) => item.caseSet === 'core')
      .forEach((item) => {
        const selectedCase = selectedCases.get(item.caseId)
        if (selectedCase) selectedCase.problemIds.push(problemId)
        else selectedCases.set(item.caseId, { resultId: item.resultId, problemIds: [problemId] })
      })
  })
  return [...selectedCases].map(([caseId, details]) => ({ caseId, ...details }))
}

type TargetEntryGateInput = {
  hasExistingTarget: boolean
  runType: EvaluationRun['run_type']
  runStatus: EvaluationRun['status']
  pendingReviewCount: number
  problem: Problem | undefined
  affectedFinalResults: Array<FinalEffectiveResult | undefined>
}

export function getTargetEntryBlocker({
  hasExistingTarget,
  runType,
  runStatus,
  pendingReviewCount,
  problem,
  affectedFinalResults,
}: TargetEntryGateInput) {
  if (problem?.frequency.numerator === 0) {
    return '该问题仅出现在挑战案例中，暂不作为本轮优化目标。'
  }
  if (hasExistingTarget) return null
  if (runType !== 'baseline') return '阻塞：目标与计划只接受 Baseline Run。'
  if (runStatus !== 'completed') return '阻塞：Baseline Run 尚未 completed。'
  if (pendingReviewCount > 0) return `阻塞：仍有 ${pendingReviewCount} 个案例待人工复核。`
  if (!problem) return '阻塞：当前没有可进入目标与计划的 Problem。'

  const failureResults = affectedFinalResults.filter(
    (result) => result?.final_result?.judgment === 'failure',
  )
  const failureModes = new Set(
    failureResults.map((result) => result?.final_result?.primary_failure_mode),
  )
  return failureResults.some((result) => !result?.final_result?.primary_failure_mode)
    || failureModes.size > 1
    ? '阻塞：受影响的失败案例没有唯一的 Primary Failure Mode。'
    : null
}
