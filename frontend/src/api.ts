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
