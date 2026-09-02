import {
  MdCheckCircleOutline,
  MdOpenInNew,
  MdPlayArrow,
  MdSmartToy,
  MdTune,
} from 'react-icons/md'
import { PiDatabase } from 'react-icons/pi'
import { Link } from 'react-router-dom'

import './StartQualityReviewPage.css'

const readinessGates = [
  { label: '数据集', status: 'VALID' },
  { label: '基线回答集', status: 'COMPLETE' },
  { label: '评测配置', status: 'READY' },
  { label: 'Judge 验收政策', status: 'PASS' },
  { label: '必需参考依据', status: 'PRESENT' },
]

function StartQualityReviewPage() {
  return (
    <section className="s01-page" aria-label="开始质量复盘">
      <div className="s01-workspace">
        <div className="s01-workspace-content">
          <div className="s01-ready-banner" role="status">
            <MdCheckCircleOutline aria-hidden="true" />
            <div className="s01-ready-copy">
              <strong>已就绪 READY</strong>
              <span>所有评测前置条件均已满足。</span>
            </div>
          </div>

          <section className="s01-context" aria-labelledby="s01-context-title">
            <div className="s01-section-heading">
              <h2 id="s01-context-title">评测上下文</h2>
            </div>

            <article className="s01-context-row">
              <div className="s01-context-icon" aria-hidden="true">
                <PiDatabase />
              </div>
              <div className="s01-context-content">
                <div className="s01-context-topline">
                  <div>
                    <h3>数据集</h3>
                    <code className="s01-code-chip">DS-NOVAMART-001 v1.0</code>
                  </div>
                  <div className="s01-context-actions">
                    <Link className="s01-text-action s01-text-action--info" to="/dataset">
                      查看数据集详情
                      <MdOpenInNew aria-hidden="true" />
                    </Link>
                    <button className="s01-text-action" type="button">
                      更换数据集
                    </button>
                  </div>
                </div>
                <div className="s01-details-grid s01-details-grid--dataset">
                  <p>
                    <strong>详情:</strong> 100 个案例; CORE-REVIEW-SET-V1：80;
                    CHALLENGE-SET-V1：20
                  </p>
                  <p>
                    <strong>场景分布:</strong> Refund 30 / Logistics 25 / Product 20 /
                    After-sales 25
                  </p>
                  <p className="s01-details-wide">
                    <strong>结论边界:</strong> Synthetic Production-like Evaluation
                    Fixture. 结论仅适用于当前评测集 (Current Evaluation Set only).
                  </p>
                  <p>
                    <strong>数据集快照:</strong>{' '}
                    <code className="s01-inline-code">[SNAPSHOT_ID]</code>
                  </p>
                </div>
              </div>
            </article>

            <article className="s01-context-row">
              <div className="s01-context-icon" aria-hidden="true">
                <MdSmartToy />
              </div>
              <div className="s01-context-content">
                <div className="s01-context-topline">
                  <div>
                    <h3>基线版本</h3>
                    <code className="s01-code-chip">Customer Support Agent V1</code>
                  </div>
                  <div className="s01-context-actions">
                    <button
                      className="s01-text-action s01-text-action--info"
                      type="button"
                    >
                      查看回答集与生成清单
                      <MdOpenInNew aria-hidden="true" />
                    </button>
                    <button className="s01-text-action" type="button">
                      更换 Baseline
                    </button>
                  </div>
                </div>
                <div className="s01-details-grid">
                  <p>
                    <strong>标识:</strong>{' '}
                    <code className="s01-inline-code">
                      [BASELINE_PRODUCT_VERSION_ID]; [BASELINE_RESPONSE_SET_ID]
                    </code>
                  </p>
                  <p className="s01-status-line">
                    <strong>状态:</strong>
                    <code className="s01-status-chip">COMPLETE：100 / 100</code>
                  </p>
                </div>
              </div>
            </article>

            <article className="s01-context-row">
              <div className="s01-context-icon" aria-hidden="true">
                <MdTune />
              </div>
              <div className="s01-context-content">
                <div className="s01-context-topline">
                  <div>
                    <h3>评测配置</h3>
                    <code className="s01-code-chip">EVAL-CONFIG-V1-FINAL</code>
                  </div>
                  <div className="s01-context-actions">
                    <button
                      className="s01-text-action s01-text-action--info"
                      type="button"
                    >
                      查看评测配置与政策
                      <MdOpenInNew aria-hidden="true" />
                    </button>
                  </div>
                </div>
                <div className="s01-details-grid s01-details-grid--config">
                  <p>
                    <strong>配置 Hash:</strong>{' '}
                    <code className="s01-inline-code">[EVAL_CONFIG_HASH]</code>
                  </p>
                  <p>
                    <strong>政策:</strong> JUDGE-ACCEPTANCE-POLICY-V1
                    <code className="s01-pass-chip">(PASS)</code>
                  </p>
                </div>
              </div>
            </article>
          </section>

          <section className="s01-gates" aria-labelledby="s01-gates-title">
            <div className="s01-gates-heading">
              <h2 id="s01-gates-title">就绪门槛</h2>
              <code>5 / 5 PASSED</code>
            </div>
            <div className="s01-gates-grid">
              {readinessGates.map((gate) => (
                <div className="s01-gate" key={gate.label}>
                  <span>{gate.label}</span>
                  <code>{gate.status}</code>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>

      <footer className="s01-action-rail">
        <div className="s01-action-copy">
          <span>状态: 尚未生成评测结论</span>
          <span>启动后进入运行中状态；评测完成且输出有效后进入 S03 基线分析。</span>
        </div>
        <button className="s01-primary-action" type="button">
          开始质量复盘
          <MdPlayArrow aria-hidden="true" />
        </button>
      </footer>
    </section>
  )
}

export default StartQualityReviewPage
