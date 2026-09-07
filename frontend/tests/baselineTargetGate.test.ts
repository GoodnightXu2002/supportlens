import assert from 'node:assert/strict'
import test from 'node:test'

import type { FinalEffectiveResult, Problem } from '../src/api.ts'
import { getTargetEntryBlocker } from '../src/baselineTargetGate.ts'

const problem = (affectedCoreCases: number) => ({
  frequency: { numerator: affectedCoreCases, denominator: 80 },
}) as Problem

const result = (
  judgment: 'warning' | 'failure',
  primaryFailureMode: 'incorrect_information' | null,
) => ({
  final_result: {
    judgment,
    primary_failure_mode: primaryFailureMode,
  },
}) as FinalEffectiveResult

const gate = (
  selectedProblem: Problem,
  affectedFinalResults: FinalEffectiveResult[],
  hasExistingTarget = false,
) => getTargetEntryBlocker({
  hasExistingTarget,
  runType: 'baseline',
  runStatus: 'completed',
  pendingReviewCount: 0,
  problem: selectedProblem,
  affectedFinalResults,
})

test('S03 target entry distinguishes core warnings, failures, and challenge-only problems', () => {
  assert.equal(gate(problem(1), [result('warning', null)]), null)
  assert.equal(gate(problem(1), [result('failure', 'incorrect_information')]), null)
  assert.match(gate(problem(1), [result('failure', null)]) ?? '', /Primary Failure Mode/)
  assert.equal(
    gate(problem(0), [result('failure', 'incorrect_information')], true),
    '该问题仅出现在挑战案例中，暂不作为本轮优化目标。',
  )
})
