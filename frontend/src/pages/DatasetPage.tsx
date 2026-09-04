import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import {
  MdArrowBack,
  MdCheckCircle,
  MdChevronRight,
  MdClose,
  MdErrorOutline,
  MdFilterList,
  MdOutlinePieChart,
  MdSearch,
  MdUploadFile,
  MdWarningAmber,
} from 'react-icons/md'

import {
  ApiRequestError,
  confirmDatasetImport,
  previewDatasetImport,
  type ImportConfirmResponse,
  type ImportErrorDetail,
  type ImportPreviewResponse,
  type PrivacyStatus,
} from '../api'
import './DatasetPage.css'

type ImportStatus =
  | 'idle'
  | 'previewing'
  | 'preview_ready'
  | 'preview_error'
  | 'confirming'
  | 'success'
  | 'confirm_error'

type DatasetOutletContext = {
  datasetImportOpen: boolean
  closeDatasetImport: () => void
}

type ImportUiError = {
  code: string
  message: string
  details: ImportErrorDetail[]
}

const caseRows = [
  {
    id: '[CASE_ID]',
    scenario: '[SCENARIO]',
    intent: '[INTENT_SUMMARY]',
    membership: '[MEMBERSHIP]',
    status: '[STATUS]',
    set: 'Core',
    scenarioFilter: 'Refund',
  },
  {
    id: '[CASE_ID_02]',
    scenario: '[SCENARIO_02]',
    intent: '[INTENT_SUMMARY_02]',
    membership: '[MEMBERSHIP_02]',
    status: '[STATUS_02]',
    set: 'Challenge',
    scenarioFilter: 'Logistics',
  },
  {
    id: '[CASE_ID_03]',
    scenario: '[SCENARIO_03]',
    intent: '[INTENT_SUMMARY_03]',
    membership: '[MEMBERSHIP_03]',
    status: '[STATUS_03]',
    set: 'Core',
    scenarioFilter: 'Refund',
  },
] as const

const membershipSets = [
  { label: 'CORE-REVIEW-SET-V1', count: 80, tone: 'slate' },
  { label: 'CHALLENGE-SET-V1', count: 20, tone: 'warning' },
  { label: 'TARGET-VALIDATION-SET-V1', count: 6, tone: 'muted' },
  { label: 'REGRESSION-SET-V1', count: 8, tone: 'muted' },
] as const

function DatasetPage() {
  const { datasetImportOpen, closeDatasetImport } =
    useOutletContext<DatasetOutletContext>()
  const [query, setQuery] = useState('')
  const [caseSet, setCaseSet] = useState('all')
  const [scenario, setScenario] = useState('all')
  const [importStatus, setImportStatus] = useState<ImportStatus>('idle')
  const [file, setFile] = useState<File | null>(null)
  const [datasetName, setDatasetName] = useState('')
  const [description, setDescription] = useState('')
  const [version, setVersion] = useState('v1.0')
  const [privacyStatus, setPrivacyStatus] =
    useState<PrivacyStatus>('unknown')
  const [representativenessStatement, setRepresentativenessStatement] =
    useState('')
  const [preview, setPreview] = useState<ImportPreviewResponse | null>(null)
  const [importResult, setImportResult] =
    useState<ImportConfirmResponse | null>(null)
  const [importError, setImportError] = useState<ImportUiError | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const operationPending =
    importStatus === 'previewing' || importStatus === 'confirming'

  useEffect(() => {
    if (!datasetImportOpen) return
    window.requestAnimationFrame(() => fileInputRef.current?.focus())
  }, [datasetImportOpen])

  useEffect(() => {
    if (!datasetImportOpen) return

    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape' && !operationPending) handleImportClose()
    }

    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  })

  const visibleRows = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()

    return caseRows.filter((row) => {
      const matchesQuery =
        normalizedQuery.length === 0 ||
        [row.id, row.scenario, row.intent, row.membership, row.status].some(
          (value) => value.toLowerCase().includes(normalizedQuery),
        )
      const matchesSet = caseSet === 'all' || row.set === caseSet
      const matchesScenario =
        scenario === 'all' || row.scenarioFilter === scenario

      return matchesQuery && matchesSet && matchesScenario
    })
  }, [caseSet, query, scenario])

  function resetImportFlow() {
    setImportStatus('idle')
    setFile(null)
    setDatasetName('')
    setDescription('')
    setVersion('v1.0')
    setPrivacyStatus('unknown')
    setRepresentativenessStatement('')
    setPreview(null)
    setImportResult(null)
    setImportError(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  function handleImportClose() {
    if (operationPending) return
    resetImportFlow()
    closeDatasetImport()
  }

  function errorFromUnknown(error: unknown): ImportUiError {
    if (error instanceof ApiRequestError) {
      return {
        code: error.code,
        message: error.message,
        details: error.details,
      }
    }
    return {
      code: 'network_error',
      message: '无法连接导入服务。请确认 Backend 正在运行后重试。',
      details: [],
    }
  }

  async function handlePreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalizedName = datasetName.trim()
    const normalizedVersion = version.trim()

    if (!file || !normalizedName || !normalizedVersion) {
      setImportStatus('preview_error')
      setImportError({
        code: 'required_input_missing',
        message: '请选择 CSV / JSON 文件，并填写 Dataset Name 与 Version。',
        details: [],
      })
      return
    }

    const extension = file.name.split('.').pop()?.toLowerCase()
    if (extension !== 'csv' && extension !== 'json') {
      setImportStatus('preview_error')
      setImportError({
        code: 'unsupported_file_type',
        message: '仅支持 .csv 或 .json 文件；Backend 仍会执行最终校验。',
        details: [],
      })
      return
    }

    setImportStatus('previewing')
    setImportError(null)
    setPreview(null)
    try {
      const result = await previewDatasetImport({
        file,
        name: normalizedName,
        description: description.trim(),
        version: normalizedVersion,
        privacyStatus,
        representativenessStatement: representativenessStatement.trim(),
      })
      setPreview(result)
      setImportStatus('preview_ready')
    } catch (error) {
      setImportError(errorFromUnknown(error))
      setImportStatus('preview_error')
    }
  }

  async function handleConfirm() {
    if (!preview || importStatus === 'confirming') return

    setImportStatus('confirming')
    setImportError(null)
    try {
      const result = await confirmDatasetImport(preview.import_token)
      setImportResult(result)
      setImportStatus('success')
    } catch (error) {
      setImportError(errorFromUnknown(error))
      setImportStatus('confirm_error')
    }
  }

  function returnToForm() {
    setPreview(null)
    setImportError(null)
    setImportStatus('idle')
  }

  function errorLocation(detail: ImportErrorDetail) {
    if (typeof detail.row === 'number') return `第 ${detail.row} 行`
    if (typeof detail.item_index === 'number') {
      return `第 ${detail.item_index + 1} 项（index ${detail.item_index}）`
    }
    return '文件级'
  }

  function formatCreatedAt(value: string) {
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value
    return new Intl.DateTimeFormat('zh-CN', {
      dateStyle: 'medium',
      timeStyle: 'medium',
    }).format(date)
  }

  return (
    <section className="s02-page" aria-label="数据集详情工作区">
      <div className="s02-canvas">
        <section className="s02-ready-banner" aria-label="数据集状态">
          <MdCheckCircle aria-hidden="true" />
          <div>
            <h1>状态：<span>已就绪 READY</span></h1>
            <p>数据集必需输入与校验已通过，可用于质量复盘。</p>
          </div>
        </section>

        <section className="s02-metadata" aria-label="数据集基本信息">
          <div className="s02-metadata__item">
            <span>数据集 ID</span>
            <code>DS-NOVAMART-001 v1.0</code>
          </div>
          <div className="s02-metadata__item s02-metadata__item--source">
            <span>来源</span>
            <strong>合成的类生产评测样例（Synthetic Production-like Evaluation Fixture）</strong>
          </div>
          <div className="s02-metadata__item">
            <span>案例总数</span>
            <code>100 个案例</code>
          </div>
          <div className="s02-metadata__item s02-metadata__item--validation">
            <span>校验详情</span>
            <strong><MdCheckCircle aria-hidden="true" />有效 VALID</strong>
            <small>校验问题：[VALIDATION_ISSUES]</small>
            <button type="button">校验报告：[REPORT_ACCESS]</button>
          </div>
          <div className="s02-metadata__secondary">
            <div><span>隐私状态</span><code>[DATA_PRIVACY_STATUS]</code></div>
            <div><span>数据集快照</span><code>[SNAPSHOT_ID]</code></div>
            <div><span>不可变版本状态</span><code>[IMMUTABLE_STATUS]</code></div>
          </div>
        </section>

        <section className="s02-workspace">
          <div className="s02-overview">
            <h2><MdOutlinePieChart aria-hidden="true" />数据集概览</h2>
            <div className="s02-overview__grid">
              <div className="s02-overview__distribution">
                <div>
                  <h3>业务场景分布</h3>
                  <div className="s02-stat-chips">
                    <span>退款 <strong>30</strong></span>
                    <span>物流 <strong>25</strong></span>
                    <span>商品咨询 <strong>20</strong></span>
                    <span>售后 <strong>25</strong></span>
                  </div>
                </div>
                <div>
                  <h3>案例集成员数量</h3>
                  <div className="s02-membership-chips">
                    {membershipSets.map((item) => (
                      <span key={item.label}>
                        <i className={`s02-dot s02-dot--${item.tone}`} />
                        <code>{item.label} ({item.count})</code>
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              <div className="s02-overview__references">
                <div>
                  <h3>参考依据</h3>
                  <p><code>NOVAMART-RULES-V1</code><button type="button">查看参考依据包</button></p>
                </div>
                <div>
                  <h3>代表性声明</h3>
                  <code>DATASET-REPRESENTATIVENESS-STATEMENT-V1</code>
                </div>
              </div>
            </div>
          </div>

          <div className="s02-case-list">
            <div className="s02-case-list__toolbar">
              <h2>案例列表</h2>
              <div className="s02-filters">
                <label className="s02-search">
                  <MdSearch aria-hidden="true" />
                  <span className="s02-visually-hidden">搜索案例</span>
                  <input
                    type="search"
                    placeholder="搜索案例…"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                  />
                </label>
                <label>
                  <span className="s02-visually-hidden">案例集</span>
                  <select value={caseSet} onChange={(event) => setCaseSet(event.target.value)}>
                    <option value="all">案例集（全部）</option>
                    <option value="Core">Core</option>
                    <option value="Challenge">Challenge</option>
                  </select>
                </label>
                <label>
                  <span className="s02-visually-hidden">业务场景</span>
                  <select value={scenario} onChange={(event) => setScenario(event.target.value)}>
                    <option value="all">业务场景（全部）</option>
                    <option value="Refund">Refund</option>
                    <option value="Logistics">Logistics</option>
                  </select>
                </label>
                <button className="s02-more-filter" type="button">
                  <MdFilterList aria-hidden="true" />更多
                </button>
              </div>
            </div>

            <div className="s02-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>案例 ID</th>
                    <th>业务场景</th>
                    <th>意图摘要</th>
                    <th>成员属性</th>
                    <th>校验状态</th>
                    <th><span className="s02-visually-hidden">操作</span></th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((row) => (
                    <tr key={row.id}>
                      <td><code>{row.id}</code></td>
                      <td>{row.scenario}</td>
                      <td>{row.intent}</td>
                      <td><span className="s02-membership-tag">{row.membership}</span></td>
                      <td><span className="s02-valid-status"><MdCheckCircle aria-hidden="true" />{row.status}</span></td>
                      <td><button type="button">查看证据<MdChevronRight aria-hidden="true" /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {visibleRows.length === 0 ? <p className="s02-empty">没有符合当前筛选条件的案例。</p> : null}
            </div>
          </div>
        </section>
      </div>

      <footer className="s02-footer">
        <div>
          <MdWarningAmber aria-hidden="true" />
          <p>
            <strong>生产式（Production-like）不等于生产代表性（Production-representative）。</strong>
            <span>结论仅适用于当前评测集（Evaluation Set），不代表生产发生率、统计显著性或业务收益。</span>
          </p>
        </div>
        <Link to="/review">用于质量复盘</Link>
      </footer>

      {datasetImportOpen ? (
        <div
          className="s02-import-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) handleImportClose()
          }}
        >
          <section
            className="s02-import-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="s02-import-title"
            aria-describedby="s02-import-description"
          >
            <header className="s02-import-dialog__header">
              <div>
                <h2 id="s02-import-title">新建 / 导入数据集</h2>
                <p id="s02-import-description">
                  上传标准 CSV 或 JSON，先完成全量校验，再确认写入 Dataset。
                </p>
              </div>
              <button
                className="s02-import-icon-button"
                type="button"
                aria-label="关闭导入窗口"
                disabled={operationPending}
                onClick={handleImportClose}
              >
                <MdClose aria-hidden="true" />
              </button>
            </header>

            <div className="s02-import-dialog__body" aria-live="polite">
              {importStatus === 'success' && importResult ? (
                <div className="s02-import-success">
                  <MdCheckCircle aria-hidden="true" />
                  <h3>数据集已成功导入</h3>
                  <p>全部 Conversation 已完成原子写入，可以关闭窗口。</p>
                  <dl>
                    <div><dt>Dataset ID</dt><dd><code>{importResult.dataset_id}</code></dd></div>
                    <div><dt>Name</dt><dd>{importResult.name}</dd></div>
                    <div><dt>Version</dt><dd><code>{importResult.version}</code></dd></div>
                    <div><dt>Conversation</dt><dd>{importResult.conversation_count}</dd></div>
                    <div><dt>Created</dt><dd>{formatCreatedAt(importResult.created_at)}</dd></div>
                  </dl>
                </div>
              ) : preview ? (
                <div className="s02-import-preview">
                  <div className="s02-import-summary">
                    <div>
                      <span>Dataset</span>
                      <strong>{preview.dataset_identity.name}</strong>
                      <code>{preview.dataset_identity.version}</code>
                    </div>
                    <div><span>文件</span><strong>{file?.name}</strong></div>
                    <div><span>Conversation</span><strong>{preview.total_conversation_count}</strong></div>
                  </div>

                  <section className="s02-import-scenarios" aria-labelledby="s02-scenarios-title">
                    <h3 id="s02-scenarios-title">Scenario distribution</h3>
                    <div>
                      {Object.entries(preview.scenario_distribution).map(([label, count]) => (
                        <span key={label}><code>{label}</code><strong>{count}</strong></span>
                      ))}
                    </div>
                  </section>

                  <section className="s02-import-conversations" aria-labelledby="s02-preview-title">
                    <div className="s02-import-conversations__heading">
                      <h3 id="s02-preview-title">Preview conversations</h3>
                      <span>显示前 {preview.preview_conversations.length} 条</span>
                    </div>
                    <div className="s02-import-conversations__list">
                      {preview.preview_conversations.map((conversation) => (
                        <article key={conversation.external_id}>
                          <header>
                            <code>{conversation.external_id}</code>
                            <span>{String(conversation.metadata.scenario ?? '未声明 scenario')}</span>
                          </header>
                          <ol>
                            {conversation.messages.map((message, index) => (
                              <li key={`${conversation.external_id}-${index}`}>
                                <strong>{message.role === 'user' ? 'USER' : 'ASSISTANT'}</strong>
                                <p>{message.content}</p>
                              </li>
                            ))}
                          </ol>
                        </article>
                      ))}
                    </div>
                  </section>
                </div>
              ) : (
                <form id="s02-import-form" className="s02-import-form" onSubmit={handlePreview}>
                  <label className="s02-import-file">
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".csv,.json,text/csv,application/json"
                      onChange={(event) => {
                        setFile(event.target.files?.[0] ?? null)
                        setImportError(null)
                        setImportStatus('idle')
                      }}
                    />
                    <MdUploadFile aria-hidden="true" />
                    <span>
                      <strong>{file ? file.name : '选择 CSV / JSON 文件'}</strong>
                      <small>{file ? `${(file.size / 1024).toFixed(1)} KB` : '最大 5 MB；Backend 执行最终校验'}</small>
                    </span>
                  </label>

                  <div className="s02-import-form__grid">
                    <label className="s02-import-field s02-import-field--wide">
                      <span>Dataset Name <b>必填</b></span>
                      <input
                        type="text"
                        value={datasetName}
                        required
                        autoComplete="off"
                        placeholder="例如：2026-09 客服质量样本"
                        onChange={(event) => setDatasetName(event.target.value)}
                      />
                    </label>
                    <label className="s02-import-field">
                      <span>Version</span>
                      <input
                        type="text"
                        value={version}
                        required
                        onChange={(event) => setVersion(event.target.value)}
                      />
                    </label>
                    <label className="s02-import-field">
                      <span>Privacy Status</span>
                      <select
                        value={privacyStatus}
                        onChange={(event) => setPrivacyStatus(event.target.value as PrivacyStatus)}
                      >
                        <option value="unknown">unknown</option>
                        <option value="synthetic">synthetic</option>
                        <option value="deidentified">deidentified</option>
                        <option value="may_contain_personal_data">may_contain_personal_data</option>
                      </select>
                    </label>
                    <label className="s02-import-field s02-import-field--full">
                      <span>Description <b>可选</b></span>
                      <textarea
                        rows={2}
                        value={description}
                        placeholder="说明数据集用途、范围或版本背景"
                        onChange={(event) => setDescription(event.target.value)}
                      />
                    </label>
                    <label className="s02-import-field s02-import-field--full">
                      <span>Representativeness Statement <b>可选</b></span>
                      <textarea
                        rows={2}
                        value={representativenessStatement}
                        placeholder="说明样本代表范围及不代表的结论"
                        onChange={(event) => setRepresentativenessStatement(event.target.value)}
                      />
                    </label>
                  </div>
                  <p className="s02-import-source-note">
                    此入口固定以 <code>source=user_upload</code> 导入。
                  </p>
                </form>
              )}

              {importError ? (
                <section className="s02-import-errors" aria-label="导入错误">
                  <div>
                    <MdErrorOutline aria-hidden="true" />
                    <p><strong>{importError.code}</strong><span>{importError.message}</span></p>
                  </div>
                  {importError.details.length > 0 ? (
                    <ul>
                      {importError.details.map((detail, index) => (
                        <li key={`${detail.code}-${detail.field}-${index}`}>
                          <code>{errorLocation(detail)} · {detail.field} · {detail.code}</code>
                          <span>{detail.message}</span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </section>
              ) : null}
            </div>

            <footer className="s02-import-dialog__footer">
              {importStatus === 'success' ? (
                <button className="s02-import-primary" type="button" onClick={handleImportClose}>
                  查看已导入数据集
                </button>
              ) : preview ? (
                <>
                  <button
                    className="s02-import-secondary"
                    type="button"
                    disabled={operationPending}
                    onClick={returnToForm}
                  >
                    <MdArrowBack aria-hidden="true" />返回修改
                  </button>
                  <button
                    className="s02-import-primary"
                    type="button"
                    disabled={operationPending}
                    onClick={handleConfirm}
                  >
                    {importStatus === 'confirming' ? '正在导入…' : '确认导入'}
                  </button>
                </>
              ) : (
                <>
                  <button className="s02-import-secondary" type="button" onClick={handleImportClose}>
                    取消
                  </button>
                  <button
                    className="s02-import-primary"
                    type="submit"
                    form="s02-import-form"
                    disabled={importStatus === 'previewing'}
                  >
                    {importStatus === 'previewing' ? '正在验证…' : '验证并预览'}
                  </button>
                </>
              )}
            </footer>
          </section>
        </div>
      ) : null}
    </section>
  )
}

export default DatasetPage
