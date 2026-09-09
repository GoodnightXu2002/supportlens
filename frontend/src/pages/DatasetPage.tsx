import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useOutletContext, useSearchParams } from 'react-router-dom'
import {
  MdArrowBack,
  MdCheckCircle,
  MdClose,
  MdErrorOutline,
  MdOutlinePieChart,
  MdSearch,
  MdUploadFile,
  MdWarningAmber,
} from 'react-icons/md'

import {
  ApiRequestError,
  confirmDatasetImport,
  getDatasetConversations,
  getDatasetDetail,
  getDatasets,
  previewDatasetImport,
  type DatasetConversation,
  type DatasetDetail,
  type DatasetListItem,
  type ImportConfirmResponse,
  type ImportErrorDetail,
  type ImportPreviewResponse,
  type PrivacyStatus,
} from '../api'
import {
  datasetSourceLabel,
  privacyStatusLabel,
  scenarioLabel,
} from '../displayLabels'
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
  openDatasetImport: () => void
  closeDatasetImport: () => void
}

type ImportUiError = {
  code: string
  message: string
  details: ImportErrorDetail[]
}

type DatasetListStatus = 'loading' | 'loaded' | 'error'

type DatasetReadError = {
  datasetId: string
  code: string
  message: string
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

function readErrorFromUnknown(error: unknown) {
  if (error instanceof ApiRequestError) {
    return { code: error.code, message: error.message }
  }
  return {
    code: 'dataset_read_failed',
    message: '无法读取数据集。请确认后端正在运行后重试。',
  }
}

function conversationScenario(conversation: DatasetConversation) {
  const value = conversation.metadata?.scenario
  return typeof value === 'string' && value.trim() ? value : '—'
}

function conversationSummary(conversation: DatasetConversation) {
  const firstUserMessage = conversation.messages.find(
    (message) => message.role === 'user',
  )?.content
  if (!firstUserMessage) return '—'
  return firstUserMessage.length > 96
    ? `${firstUserMessage.slice(0, 96)}…`
    : firstUserMessage
}

function conversationMetadata(conversation: DatasetConversation) {
  return JSON.stringify(conversation.metadata ?? {})
}

function DatasetPage() {
  const { datasetImportOpen, openDatasetImport, closeDatasetImport } =
    useOutletContext<DatasetOutletContext>()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedDatasetId = searchParams.get('dataset_id')
  const [query, setQuery] = useState('')
  const [scenario, setScenario] = useState('all')
  const [datasets, setDatasets] = useState<DatasetListItem[]>([])
  const [datasetListStatus, setDatasetListStatus] =
    useState<DatasetListStatus>('loading')
  const [datasetListError, setDatasetListError] = useState<string | null>(null)
  const [datasetListRequest, setDatasetListRequest] = useState(0)
  const [datasetDetail, setDatasetDetail] = useState<DatasetDetail | null>(null)
  const [conversations, setConversations] = useState<DatasetConversation[]>([])
  const [datasetReadError, setDatasetReadError] =
    useState<DatasetReadError | null>(null)
  const [datasetReadRequest, setDatasetReadRequest] = useState(0)
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

  const selectedDatasetId = requestedDatasetId ?? datasets[0]?.dataset_id ?? null
  const selectedDatasetExists = selectedDatasetId
    ? datasets.some((dataset) => dataset.dataset_id === selectedDatasetId)
    : false
  const detailReady = datasetDetail?.dataset_id === selectedDatasetId
  const activeReadError =
    datasetReadError?.datasetId === selectedDatasetId ? datasetReadError : null
  const datasetNotFound =
    datasetListStatus === 'loaded' &&
    datasets.length > 0 &&
    Boolean(requestedDatasetId) &&
    (!selectedDatasetExists || activeReadError?.code === 'dataset_not_found')

  useEffect(() => {
    const controller = new AbortController()

    void getDatasets(controller.signal)
      .then((nextDatasets) => {
        if (controller.signal.aborted) return
        setDatasets(nextDatasets)
        setDatasetListError(null)
        setDatasetListStatus('loaded')

        const currentParams = new URLSearchParams(window.location.search)
        if (nextDatasets.length > 0 && !currentParams.get('dataset_id')) {
          currentParams.set('dataset_id', nextDatasets[0].dataset_id)
          setSearchParams(currentParams, { replace: true })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || isAbortError(error)) return
        const readError = readErrorFromUnknown(error)
        setDatasetListError(readError.message)
        setDatasetListStatus('error')
      })

    return () => controller.abort()
  }, [datasetListRequest, setSearchParams])

  useEffect(() => {
    if (!selectedDatasetId || !selectedDatasetExists) return
    const controller = new AbortController()

    void Promise.all([
      getDatasetDetail(selectedDatasetId, controller.signal),
      getDatasetConversations(selectedDatasetId, controller.signal),
    ])
      .then(([nextDetail, nextConversations]) => {
        if (controller.signal.aborted) return
        setDatasetDetail(nextDetail)
        setConversations(nextConversations)
        setDatasetReadError(null)
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || isAbortError(error)) return
        const readError = readErrorFromUnknown(error)
        setDatasetReadError({
          datasetId: selectedDatasetId,
          code: readError.code,
          message: readError.message,
        })
      })

    return () => controller.abort()
  }, [datasetReadRequest, selectedDatasetExists, selectedDatasetId])

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

  const scenarioOptions = useMemo(
    () =>
      Array.from(
        new Set(
          conversations
            .map(conversationScenario)
            .filter((value) => value !== '—'),
        ),
      ).sort((left, right) => left.localeCompare(right)),
    [conversations],
  )

  const visibleRows = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()

    return conversations.filter((conversation) => {
      const rowScenario = conversationScenario(conversation)
      const matchesQuery =
        normalizedQuery.length === 0 ||
        conversation.external_id.toLowerCase().includes(normalizedQuery) ||
        rowScenario.toLowerCase().includes(normalizedQuery) ||
        conversation.messages.some((message) =>
          message.content.toLowerCase().includes(normalizedQuery),
        )
      const matchesScenario =
        scenario === 'all' || rowScenario === scenario

      return matchesQuery && matchesScenario
    })
  }, [conversations, query, scenario])

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
      message: '无法连接导入服务。请确认后端正在运行后重试。',
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
        message: '请选择 CSV / JSON 文件，并填写数据集名称与版本。',
        details: [],
      })
      return
    }

    const extension = file.name.split('.').pop()?.toLowerCase()
    if (extension !== 'csv' && extension !== 'json') {
      setImportStatus('preview_error')
      setImportError({
        code: 'unsupported_file_type',
        message: '仅支持 .csv 或 .json 文件；后端仍会执行最终校验。',
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
      setQuery('')
      setScenario('all')
      setDatasetDetail(null)
      setConversations([])
      setDatasetReadError(null)
      setDatasetListStatus('loading')
      setSearchParams({ dataset_id: result.dataset_id }, { replace: true })
      setDatasetListRequest((request) => request + 1)
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
      return `第 ${detail.item_index + 1} 项（索引 ${detail.item_index}）`
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

  function selectDataset(datasetId: string) {
    setQuery('')
    setScenario('all')
    setDatasetReadError(null)
    setSearchParams({ dataset_id: datasetId })
  }

  function retryDatasetList() {
    setDatasetListError(null)
    setDatasetListStatus('loading')
    setDatasetListRequest((request) => request + 1)
  }

  function retrySelectedDataset() {
    setDatasetReadError(null)
    setDatasetDetail(null)
    setConversations([])
    setDatasetReadRequest((request) => request + 1)
  }

  function renderDataState(
    title: string,
    message: string,
    actionLabel?: string,
    onAction?: () => void,
    code?: string,
  ) {
    return (
      <div className="s02-canvas">
        <section className="s02-data-state" aria-live="polite">
          <MdOutlinePieChart aria-hidden="true" />
          <h1>{title}</h1>
          <p>{message}</p>
          {code ? <code>{code}</code> : null}
          {actionLabel && onAction ? (
            <button type="button" onClick={onAction}>{actionLabel}</button>
          ) : null}
        </section>
      </div>
    )
  }

  return (
    <section className="s02-page" aria-label="数据集详情工作区">
      {datasetListStatus === 'loading'
        ? renderDataState('正在读取数据集', '正在从后端获取可用数据集…')
        : datasetListStatus === 'error'
          ? renderDataState(
              '数据集加载失败',
              datasetListError ?? '无法获取数据集列表。',
              '重试',
              retryDatasetList,
            )
          : datasets.length === 0
            ? renderDataState(
                '尚无数据集',
                '导入 CSV 或 JSON 后，真实数据集与会话将显示在这里。',
                '新建 / 导入数据集',
                openDatasetImport,
              )
            : datasetNotFound
              ? renderDataState(
                  '未找到数据集',
                  'URL 指定的数据集不存在，未使用其他数据集替代。',
                  '查看最新数据集',
                  () => selectDataset(datasets[0].dataset_id),
                  requestedDatasetId ?? undefined,
                )
              : activeReadError
                ? renderDataState(
                    '数据集读取失败',
                    activeReadError.message,
                    '重试',
                    retrySelectedDataset,
                    activeReadError.code,
                  )
                : !detailReady || !datasetDetail
                  ? renderDataState(
                      '正在读取数据集',
                      '正在获取数据集详情与会话…',
                    )
                  : (
                    <>
      <div className="s02-canvas">
        <section className="s02-ready-banner" aria-label="数据集状态">
          <MdCheckCircle aria-hidden="true" />
          <div>
            <h1>{datasetDetail.name}<span>已就绪</span></h1>
            <p>{datasetDetail.description ?? '未提供数据集描述。'}</p>
          </div>
          {datasets.length > 1 ? (
            <label className="s02-dataset-switcher">
              <span>当前数据集</span>
              <select
                value={datasetDetail.dataset_id}
                onChange={(event) => selectDataset(event.target.value)}
              >
                {datasets.map((dataset) => (
                  <option key={dataset.dataset_id} value={dataset.dataset_id}>
                    {dataset.name} · {dataset.version}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </section>

        <section className="s02-metadata" aria-label="数据集基本信息">
          <div className="s02-metadata__item">
            <span>数据集 ID</span>
            <code>{datasetDetail.dataset_id}</code>
          </div>
          <div className="s02-metadata__item s02-metadata__item--source">
            <span>来源</span>
            <strong>{datasetSourceLabel(datasetDetail.source)}</strong>
          </div>
          <div className="s02-metadata__item">
            <span>案例总数</span>
            <code>{datasetDetail.conversation_count} 个案例</code>
          </div>
          <div className="s02-metadata__item s02-metadata__item--last">
            <span>创建时间</span>
            <code>{formatCreatedAt(datasetDetail.created_at)}</code>
          </div>
          <div className="s02-metadata__secondary">
            <div><span>版本</span><code>{datasetDetail.version}</code></div>
            <div><span>隐私状态</span><code>{privacyStatusLabel(datasetDetail.privacy_status)}</code></div>
            <div><span>描述</span><strong>{datasetDetail.description ?? '未提供'}</strong></div>
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
                    {Object.entries(datasetDetail.scenario_distribution).length > 0 ? (
                      Object.entries(datasetDetail.scenario_distribution).map(
                        ([label, count]) => (
                          <span key={label}>{scenarioLabel(label)} <strong>{count}</strong></span>
                        ),
                      )
                    ) : (
                      <span>未提供场景</span>
                    )}
                  </div>
                </div>
                <div>
                  <h3>案例集成员数量</h3>
                  <p className="s02-unconfigured">未配置</p>
                </div>
              </div>

              <div className="s02-overview__references">
                <div>
                  <h3>参考依据</h3>
                  <p className="s02-unconfigured">未配置</p>
                </div>
                <div>
                  <h3>代表性声明</h3>
                  <p className="s02-representativeness">
                    {datasetDetail.representativeness_statement ?? '未提供'}
                  </p>
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
                  <span className="s02-visually-hidden">业务场景</span>
                  <select value={scenario} onChange={(event) => setScenario(event.target.value)}>
                    <option value="all">业务场景（全部）</option>
                    {scenarioOptions.map((value) => (
                      <option key={value} value={value}>{scenarioLabel(value)}</option>
                    ))}
                  </select>
                </label>
              </div>
            </div>

            <div className="s02-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>案例 ID</th>
                    <th>业务场景</th>
                    <th>消息摘要</th>
                    <th>元数据</th>
                    <th>创建时间</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((conversation) => (
                    <tr key={conversation.id}>
                      <td><code>{conversation.external_id}</code></td>
                      <td>{scenarioLabel(conversationScenario(conversation))}</td>
                      <td title={conversationSummary(conversation)}>
                        {conversationSummary(conversation)}
                      </td>
                      <td>
                        <code
                          className="s02-metadata-value"
                          title={conversationMetadata(conversation)}
                        >
                          {conversationMetadata(conversation)}
                        </code>
                      </td>
                      <td>{formatCreatedAt(conversation.created_at)}</td>
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
            <strong>仿生产数据不等于具备生产代表性。</strong>
            <span>结论仅适用于当前评测集，不代表生产发生率、统计显著性或业务收益。</span>
          </p>
        </div>
        <Link to="/review">用于质量复盘</Link>
      </footer>
                    </>
                  )}

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
                  上传标准 CSV 或 JSON，先完成全量校验，再确认写入数据集。
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
                  <p>全部会话已完成原子写入，可以关闭窗口。</p>
                  <dl>
                    <div><dt>数据集 ID</dt><dd><code>{importResult.dataset_id}</code></dd></div>
                    <div><dt>名称</dt><dd>{importResult.name}</dd></div>
                    <div><dt>版本</dt><dd><code>{importResult.version}</code></dd></div>
                    <div><dt>会话</dt><dd>{importResult.conversation_count}</dd></div>
                    <div><dt>创建时间</dt><dd>{formatCreatedAt(importResult.created_at)}</dd></div>
                  </dl>
                </div>
              ) : preview ? (
                <div className="s02-import-preview">
                  <div className="s02-import-summary">
                    <div>
                      <span>数据集</span>
                      <strong>{preview.dataset_identity.name}</strong>
                      <code>{preview.dataset_identity.version}</code>
                    </div>
                    <div><span>文件</span><strong>{file?.name}</strong></div>
                    <div><span>会话</span><strong>{preview.total_conversation_count}</strong></div>
                  </div>

                  <section className="s02-import-scenarios" aria-labelledby="s02-scenarios-title">
                    <h3 id="s02-scenarios-title">场景分布</h3>
                    <div>
                      {Object.entries(preview.scenario_distribution).map(([label, count]) => (
                        <span key={label}><code>{scenarioLabel(label)}</code><strong>{count}</strong></span>
                      ))}
                    </div>
                  </section>

                  <section className="s02-import-conversations" aria-labelledby="s02-preview-title">
                    <div className="s02-import-conversations__heading">
                      <h3 id="s02-preview-title">会话预览</h3>
                      <span>显示前 {preview.preview_conversations.length} 条</span>
                    </div>
                    <div className="s02-import-conversations__list">
                      {preview.preview_conversations.map((conversation) => (
                        <article key={conversation.external_id}>
                          <header>
                            <code>{conversation.external_id}</code>
                            <span>{conversation.metadata.scenario ? scenarioLabel(String(conversation.metadata.scenario)) : '未声明场景'}</span>
                          </header>
                          <ol>
                            {conversation.messages.map((message, index) => (
                              <li key={`${conversation.external_id}-${index}`}>
                                <strong>{message.role === 'user' ? '用户' : '助手'}</strong>
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
                      <small>{file ? `${(file.size / 1024).toFixed(1)} KB` : '最大 5 MB；后端执行最终校验'}</small>
                    </span>
                  </label>

                  <div className="s02-import-form__grid">
                    <label className="s02-import-field s02-import-field--wide">
                      <span>数据集名称 <b>必填</b></span>
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
                      <span>版本</span>
                      <input
                        type="text"
                        value={version}
                        required
                        onChange={(event) => setVersion(event.target.value)}
                      />
                    </label>
                    <label className="s02-import-field">
                      <span>隐私状态</span>
                      <select
                        value={privacyStatus}
                        onChange={(event) => setPrivacyStatus(event.target.value as PrivacyStatus)}
                      >
                        <option value="unknown">{privacyStatusLabel('unknown')}</option>
                        <option value="synthetic">{privacyStatusLabel('synthetic')}</option>
                        <option value="deidentified">{privacyStatusLabel('deidentified')}</option>
                        <option value="may_contain_personal_data">{privacyStatusLabel('may_contain_personal_data')}</option>
                      </select>
                    </label>
                    <label className="s02-import-field s02-import-field--full">
                      <span>描述 <b>可选</b></span>
                      <textarea
                        rows={2}
                        value={description}
                        placeholder="说明数据集用途、范围或版本背景"
                        onChange={(event) => setDescription(event.target.value)}
                      />
                    </label>
                    <label className="s02-import-field s02-import-field--full">
                      <span>代表性声明 <b>可选</b></span>
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
