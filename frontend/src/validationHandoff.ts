import type {
  CandidateResponseInput,
  DatasetConversation,
  OptimizationTarget,
} from './api'

function caseList(caseIds: string[]) {
  const preview = caseIds.slice(0, 5).join('、')
  return caseIds.length > 5 ? `${preview} 等 ${caseIds.length} 个案例` : preview
}

export function buildValidationCaseExport(
  target: Pick<OptimizationTarget, 'target_case_ids' | 'regression_case_ids' | 'challenge_case_ids'>,
  conversations: DatasetConversation[],
) {
  const conversationByCaseId = new Map(
    conversations.map((conversation) => [conversation.external_id, conversation]),
  )
  return [
    ...target.target_case_ids.map((caseId) => ({ caseId, set: 'target' as const })),
    ...target.regression_case_ids.map((caseId) => ({ caseId, set: 'regression' as const })),
    ...target.challenge_case_ids.map((caseId) => ({ caseId, set: 'challenge' as const })),
  ].map(({ caseId, set }) => {
    const conversation = conversationByCaseId.get(caseId)
    if (!conversation) throw new Error(`验证案例 ${caseId} 不在当前数据集中，无法导出。`)
    return { case_id: caseId, set, messages: conversation.messages }
  })
}

export function parseCandidateResponsesJson(
  text: string,
  requiredCaseIds: string[],
  conversations: DatasetConversation[],
): CandidateResponseInput[] {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new Error('JSON 文件格式错误，请检查语法。')
  }
  if (!Array.isArray(parsed)) throw new Error('JSON 顶层必须是数组。')

  const required = new Set(requiredCaseIds)
  const conversationByCaseId = new Map(
    conversations.map((conversation) => [conversation.external_id, conversation]),
  )
  const seen = new Set<string>()
  const responses = parsed.map((item, index) => {
    if (!item || typeof item !== 'object') {
      throw new Error(`第 ${index + 1} 条回复必须是对象。`)
    }
    const value = item as Record<string, unknown>
    if (typeof value.case_id !== 'string' || !value.case_id.trim()) {
      throw new Error(`第 ${index + 1} 条回复缺少有效 case_id。`)
    }
    const caseId = value.case_id.trim()
    if (seen.has(caseId)) throw new Error(`case_id 重复：${caseId}。`)
    if (!required.has(caseId)) {
      throw new Error(`case_id 不属于当前冻结验证计划：${caseId}。`)
    }
    if (typeof value.assistant_content !== 'string' || !value.assistant_content.trim()) {
      throw new Error(`案例 ${caseId} 的 assistant_content 不能为空。`)
    }
    const conversation = conversationByCaseId.get(caseId)
    if (!conversation) throw new Error(`无法关联数据集会话：${caseId}。`)
    seen.add(caseId)
    return {
      conversation_id: conversation.id,
      case_id: caseId,
      assistant_content: value.assistant_content,
    }
  })

  const missing = requiredCaseIds.filter((caseId) => !seen.has(caseId))
  if (missing.length) throw new Error(`缺少必需案例：${caseList(missing)}。`)
  return responses
}
