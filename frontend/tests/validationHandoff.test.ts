import assert from 'node:assert/strict'
import test from 'node:test'

import type { DatasetConversation } from '../src/api.ts'
import {
  buildValidationCaseExport,
  parseCandidateResponsesJson,
} from '../src/validationHandoff.ts'

const conversations: DatasetConversation[] = ['CASE-A', 'CASE-B'].map((caseId, index) => ({
  id: `00000000-0000-0000-0000-00000000000${index + 1}`,
  external_id: caseId,
  messages: [{ role: 'user', content: `Question for ${caseId}` }],
  metadata: null,
  created_at: '2026-01-01T00:00:00Z',
}))
const required = conversations.map((conversation) => conversation.external_id)

test('validation handoff exports the frozen plan and accepts only exact valid responses', () => {
  const target = {
    target_case_ids: ['CASE-A'],
    regression_case_ids: ['CASE-B'],
    challenge_case_ids: [],
  }
  assert.deepEqual(buildValidationCaseExport(target, conversations), [
    { case_id: 'CASE-A', set: 'target', messages: conversations[0].messages },
    { case_id: 'CASE-B', set: 'regression', messages: conversations[1].messages },
  ])

  const valid = JSON.stringify(required.map((caseId) => ({
    case_id: caseId,
    assistant_content: `Response for ${caseId}`,
  })))
  assert.deepEqual(
    parseCandidateResponsesJson(valid, required, conversations).map(({ case_id }) => case_id),
    required,
  )

  const rejected = [
    ['{', 'JSON 文件格式错误'],
    [JSON.stringify([{ case_id: 'CASE-A', assistant_content: 'ok' }]), '缺少必需案例'],
    [JSON.stringify(required.map(() => ({ case_id: 'CASE-A', assistant_content: 'ok' }))), 'case_id 重复'],
    [JSON.stringify([{ case_id: 'CASE-A', assistant_content: 'ok' }, { case_id: 'CASE-X', assistant_content: 'ok' }]), '不属于当前冻结验证计划'],
    [JSON.stringify([{ case_id: 'CASE-A', assistant_content: '' }, { case_id: 'CASE-B', assistant_content: 'ok' }]), 'assistant_content 不能为空'],
  ] as const
  for (const [input, message] of rejected) {
    assert.throws(() => parseCandidateResponsesJson(input, required, conversations), new RegExp(message))
  }
})
