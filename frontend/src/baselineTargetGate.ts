import type { EvaluationRun, FinalEffectiveResult, Problem } from './api'

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
