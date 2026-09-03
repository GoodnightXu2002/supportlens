import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  MdCheckCircle,
  MdChevronRight,
  MdFilterList,
  MdOutlinePieChart,
  MdSearch,
  MdWarningAmber,
} from 'react-icons/md'

import './DatasetPage.css'

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
  const [query, setQuery] = useState('')
  const [caseSet, setCaseSet] = useState('all')
  const [scenario, setScenario] = useState('all')

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
    </section>
  )
}

export default DatasetPage
