// 显示层中文映射：仅影响展示文本，底层 enum / API / Contract 值保持不变。
// 未知值一律回退为原始值，保证可追溯性。

const scenarioLabels: Record<string, string> = {
  'After-sales': '售后',
  Logistics: '物流',
  Product: '商品',
  Refund: '退款',
}

const datasetSourceLabels: Record<string, string> = {
  user_upload: '用户上传',
  fixture_import: '固定样例导入',
}

const privacyStatusLabels: Record<string, string> = {
  synthetic: '合成数据',
  deidentified: '已去标识化',
  may_contain_personal_data: '可能包含个人数据',
  unknown: '未知',
}

const runStatusLabels: Record<string, string> = {
  pending: '待开始',
  running: '运行中',
  completed: '已完成',
  partial_failure: '部分失败',
  failed: '失败',
  invalid: '无效',
}

const runSourceLabels: Record<string, string> = {
  seed: '预置数据',
  live: '实时运行',
}

const targetStatusLabels: Record<string, string> = {
  draft: '草稿',
  confirmed: '已确认',
  frozen: '已冻结',
}

const failureModeLabels: Record<string, string> = {
  incorrect_information: '信息错误',
  incomplete_unresolved: '不完整 / 未解决',
  intent_relevance_failure: '意图相关性失败',
  improper_refusal: '不当拒答',
  policy_procedure_violation: '违反政策 / 流程',
  other: '其他',
}

const evidenceTypeLabels: Record<string, string> = {
  response: '回复',
  case_fact: '案例事实',
  reference: '参考依据',
}

const blockerLabels: Record<string, string> = {
  business_impact_unmapped: '业务影响待补充',
  priority_severity_unavailable: '优先级严重程度不可用',
  pattern_consistency_unavailable: '模式一致性不可用',
  pending_human_review: '待人工复核',
  case_comparison_inconclusive: '案例对比无法得出结论',
}

function lookup(labels: Record<string, string>, value: string | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  return labels[value] ?? value
}

export const scenarioLabel = (value: string | null | undefined) => lookup(scenarioLabels, value)
export const datasetSourceLabel = (value: string | null | undefined) => lookup(datasetSourceLabels, value)
export const privacyStatusLabel = (value: string | null | undefined) => lookup(privacyStatusLabels, value)
export const runStatusLabel = (value: string | null | undefined) => lookup(runStatusLabels, value)
export const runSourceLabel = (value: string | null | undefined) => lookup(runSourceLabels, value)
export const targetStatusLabel = (value: string | null | undefined) => lookup(targetStatusLabels, value)
export const failureModeLabel = (value: string | null | undefined) => lookup(failureModeLabels, value)
export const evidenceTypeLabel = (value: string | null | undefined) => lookup(evidenceTypeLabels, value)
export const blockerLabel = (value: string | null | undefined) => lookup(blockerLabels, value)
