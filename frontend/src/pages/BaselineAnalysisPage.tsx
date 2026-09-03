import {
  MdAccountTree,
  MdCancel,
  MdCheckCircle,
  MdError,
  MdFilterList,
  MdGavel,
  MdMenuBook,
  MdMoreHoriz,
  MdPerson,
  MdSmartToy,
} from 'react-icons/md'

import './BaselineAnalysisPage.css'

const cases = [
  { id: 'NM-001', summary: '促销商品退款…', status: 'review', label: '需要复核' },
  { id: 'NM-042', summary: '部分退款流程…', status: 'resolved', label: '已解决' },
  { id: 'NM-088', summary: '退货期限例外…', status: 'review', label: '需要复核' },
  { id: 'NM-103', summary: '数字商品退款…', status: 'pending', label: '待处理' },
] as const

function CaseStatus({ status, label }: (typeof cases)[number]) {
  if (status === 'resolved') {
    return <MdCheckCircle className="s03-status-icon s03-status-icon--success" aria-label={label} />
  }

  if (status === 'pending') {
    return <MdMoreHoriz className="s03-status-icon s03-status-icon--pending" aria-label={label} />
  }

  return <MdError className="s03-status-icon s03-status-icon--warning" aria-label={label} />
}

function BaselineAnalysisPage() {
  return (
    <section className="s03-page" aria-label="基线分析工作区">
      <div className="s03-review-strip">
        <div className="s03-review-strip__content">
          <div className="s03-review-state">
            <span className="s03-review-state__dot" aria-hidden="true" />
            <div>
              <h1>需要人工复核 - 非最终结论</h1>
              <p>状态码：REV-PENDING</p>
            </div>
          </div>

          <span className="s03-review-strip__divider" aria-hidden="true" />

          <dl className="s03-metadata">
            <div>
              <dt>数据集</dt>
              <dd>DS-NOVAMART-001 v1.0</dd>
            </div>
            <div className="s03-metadata__type">
              <dt>数据类型</dt>
              <dd>Synthetic Production-like Evaluation</dd>
            </div>
            <div>
              <dt>声明范围</dt>
              <dd>Evaluation Set</dd>
            </div>
          </dl>
        </div>

        <button className="s03-review-action" type="button">处理必要复核</button>
      </div>

      <div className="s03-workspace">
        <section className="s03-pane s03-problems" aria-labelledby="s03-problems-title">
          <header className="s03-pane-header">
            <h2 id="s03-problems-title">问题聚类（5）</h2>
            <button className="s03-icon-button" type="button" aria-label="筛选问题聚类">
              <MdFilterList aria-hidden="true" />
            </button>
          </header>

          <div className="s03-pane-scroll s03-problem-list">
            <article className="s03-problem-card">
              <div className="s03-problem-card__topline">
                <span className="s03-code-label">P-LOGIS-04</span>
                <span className="s03-count-badge">3 个案例</span>
              </div>
              <h3>物流追踪更新延迟</h3>
              <p className="s03-severity">
                <span className="s03-dot s03-dot--warning" aria-hidden="true" />
                严重程度：中
              </p>
            </article>

            <article className="s03-problem-card s03-problem-card--active">
              <div className="s03-problem-card__topline">
                <span className="s03-code-label s03-code-label--strong">P-REFUND-01</span>
                <span className="s03-count-badge s03-count-badge--active">6 个案例</span>
              </div>
              <h3>退款规则误用</h3>
              <dl className="s03-priority-grid">
                <div><dt><span className="s03-dot s03-dot--critical" aria-hidden="true" />严重程度：</dt><dd>高</dd></div>
                <div><dt><span className="s03-dot s03-dot--critical" aria-hidden="true" />业务影响：</dt><dd>高</dd></div>
                <div className="s03-priority-grid__frequency"><dt><span className="s03-dot s03-dot--secondary" aria-hidden="true" />频率：</dt><dd>6.0%</dd></div>
                <div><dt><span className="s03-dot s03-dot--info" aria-hidden="true" />模式一致性：</dt><dd>高</dd></div>
                <div className="s03-priority-grid__wide"><dt><span className="s03-dot s03-dot--info" aria-hidden="true" />证据置信度：</dt><dd>高</dd></div>
              </dl>
            </article>

            <article className="s03-problem-card">
              <div className="s03-problem-card__topline">
                <span className="s03-code-label">P-AUTH-02</span>
                <span className="s03-count-badge">1 个案例</span>
              </div>
              <h3>优惠券核销失败</h3>
              <p className="s03-severity">
                <span className="s03-dot s03-dot--secondary" aria-hidden="true" />
                严重程度：低
              </p>
            </article>
          </div>
        </section>

        <section className="s03-pane s03-cases" aria-labelledby="s03-cases-title">
          <header className="s03-pane-header s03-cases-header">
            <h2 id="s03-cases-title">受影响案例（6）</h2>
            <p>P-REFUND-01 案例下钻</p>
          </header>

          <div className="s03-pane-scroll s03-case-list">
            <div className="s03-case-grid s03-case-table-head" aria-hidden="true">
              <span>案例 ID</span><span>意图摘要</span><span>状态</span>
            </div>
            <div className="s03-case-rows">
              {cases.map((caseItem, index) => (
                <article className={index === 0 ? 's03-case-grid s03-case-row s03-case-row--active' : 's03-case-grid s03-case-row'} key={caseItem.id}>
                  <span className="s03-case-id">
                    {index === 0 ? <span className="s03-case-id__rail" aria-hidden="true" /> : null}
                    {caseItem.id}
                  </span>
                  <span className="s03-case-summary" title={caseItem.summary}>{caseItem.summary}</span>
                  <span className="s03-case-status"><CaseStatus {...caseItem} /></span>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="s03-pane s03-evidence" aria-labelledby="s03-evidence-title">
          <header className="s03-pane-header s03-evidence-header">
            <h2 id="s03-evidence-title">证据链 <span>CASE-NM-001</span></h2>
            <MdAccountTree aria-hidden="true" />
          </header>

          <div className="s03-pane-scroll s03-evidence-ledger">
            <div className="s03-evidence-line" aria-hidden="true" />

            <article className="s03-evidence-node">
              <span className="s03-node-marker"><span /></span>
              <div className="s03-node-content">
                <h3>节点 1 / 用户消息</h3>
                <blockquote>“我买的衣服参与了满减活动，现在我想退掉这件衣服，能退多少钱？”</blockquote>
              </div>
            </article>

            <article className="s03-evidence-node">
              <span className="s03-node-marker"><span /></span>
              <div className="s03-node-content">
                <h3>节点 2 / 基线回复</h3>
                <blockquote>“您好，退款金额将按照商品原价退还。期待再次为您服务。”</blockquote>
              </div>
            </article>

            <article className="s03-evidence-node">
              <span className="s03-node-marker s03-node-marker--icon"><MdSmartToy aria-hidden="true" /></span>
              <div className="s03-node-content">
                <h3 className="s03-node-title--italic">节点 3 / AI 原始判定</h3>
                <div className="s03-ai-judgment">
                  <div className="s03-ai-judgment__status"><span>判定: 正确</span><span>置信度：85%</span></div>
                  <p>AI 判定理由：基线回复对退款金额给出了明确回答。</p>
                </div>
              </div>
            </article>

            <article className="s03-evidence-node">
              <span className="s03-node-marker"><span className="s03-node-marker__fact" /></span>
              <div className="s03-node-content">
                <h3>节点 4 / 事实</h3>
                <ul><li>订单涉及促销满减。</li><li>基线回复按商品原价全额退款。</li></ul>
              </div>
            </article>

            <article className="s03-evidence-node">
              <span className="s03-node-marker s03-node-marker--icon"><MdMenuBook aria-hidden="true" /></span>
              <div className="s03-node-content">
                <h3>节点 5 / 参考依据</h3>
                <p className="s03-reference">DOC-POL-04: “若订单包含满减等优惠，部分退款时需按比例扣除优惠金额，绝不退还原价。”</p>
              </div>
            </article>

            <article className="s03-evidence-node">
              <span className="s03-node-marker s03-node-marker--human"><MdPerson aria-hidden="true" /></span>
              <div className="s03-node-content">
                <h3 className="s03-node-title--strong">节点 6 / 人工复核</h3>
                <div className="s03-human-review">
                  <p className="s03-human-review__decision"><MdCancel aria-hidden="true" />修正 AI 判定（错误）</p>
                  <div><span>复核理由</span><p>基线回复违背了退款政策 DOC-POL-04，参与满减的商品不能按原价退款。AI 漏看了满减条件。</p></div>
                </div>
              </div>
            </article>

            <article className="s03-evidence-node">
              <span className="s03-node-marker s03-node-marker--final"><MdGavel aria-hidden="true" /></span>
              <div className="s03-node-content">
                <h3>节点 7 / 最终生效结果</h3>
                <div className="s03-final-result">
                  <div><span>最终判定</span><strong>错误</strong></div>
                  <div><span>记录状态</span><em>已生效</em></div>
                  <p>结果已由人工复核修正。下游结论采用最终生效结果，AI 原始判定保留用于追溯。</p>
                </div>
              </div>
            </article>
          </div>
        </section>
      </div>

      <footer className="s03-bottom-bar">
        <div className="s03-analyst"><img src="/s03-analyst.jpg" alt="Analyst 04" /><strong>Analyst 04</strong></div>
        <div className="s03-bottom-actions"><span>剩余 5 个案例待复核</span><button type="button" disabled>进入目标与计划</button></div>
      </footer>
    </section>
  )
}

export default BaselineAnalysisPage
