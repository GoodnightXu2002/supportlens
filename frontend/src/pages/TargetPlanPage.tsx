import {
  MdArrowForward,
  MdHistory,
  MdLightbulbOutline,
  MdLockOutline,
  MdPersonOutline,
  MdPsychology,
  MdRadioButtonUnchecked,
  MdRule,
  MdWarningAmber,
} from 'react-icons/md'

import './TargetPlanPage.css'

const changeRecords = [
  {
    scope: '指令／参考依据使用',
    status: '计划草稿',
    detail: '强化外部 Agent 指令 / 参考依据使用的检查要求',
    warning: true,
  },
  {
    scope: '系统配置',
    status: '保持不变 · 待冻结',
    detail: 'Agent 生成机制、运行环境、数据集、评测配置与策略保持不变。',
    warning: false,
  },
  { scope: '实际变更', status: '未开始', detail: '—', warning: false },
  { scope: '偏差', status: '不适用', detail: '—', warning: false },
] as const

function TargetPlanPage() {
  return (
    <section className="s04-page" aria-label="目标与计划冻结前状态">
      <div className="s04-header-status" aria-label="当前状态：需要人工确认">
        <span aria-hidden="true" />
        需要人工确认
      </div>
      <MdLockOutline className="s04-candidate-lock" aria-hidden="true" />

      <div className="s04-canvas">
        <div className="s04-content">
          <dl className="s04-metadata">
            <div>
              <dt>数据集</dt>
              <dd>DS-NOVAMART-001 v1.0</dd>
            </div>
            <div>
              <dt>夹具类型</dt>
              <dd>合成生产相似数据（Synthetic Production-like）</dd>
            </div>
            <div>
              <dt>声明范围</dt>
              <dd>仅当前评测集（Evaluation Set）</dd>
            </div>
          </dl>

          <header className="s04-state">
            <div className="s04-state__title">
              <span aria-hidden="true" />
              <h1>验证计划待冻结</h1>
            </div>
            <dl>
              <div><dt>结论属性:</dt><dd>非最终结论</dd></div>
              <div><dt>当前阻断:</dt><dd>人工目标与优化假设尚未完成确认</dd></div>
            </dl>
          </header>

          <div className="s04-sections">
            <section className="s04-targets" aria-label="目标确认">
              <div className="s04-target-column">
                <h2><MdPsychology aria-hidden="true" />AI 推荐目标</h2>
                <div className="s04-target-value">退款资格判断准确性</div>
                <div className="s04-target-tags" aria-label="目标相关信息">
                  <span>P-REFUND-01</span>
                  <span className="s04-target-tags__priority">优先级 #1</span>
                  <span>6 个受影响案例</span>
                </div>
                <button className="s04-text-action" type="button">
                  查看 6 个目标案例与证据
                  <MdArrowForward aria-hidden="true" />
                </button>
              </div>

              <div className="s04-target-column s04-target-column--human">
                <div className="s04-section-heading">
                  <h2><MdPersonOutline aria-hidden="true" />人工目标确认</h2>
                  <span>待人工确认</span>
                </div>
                <div className="s04-empty-target">尚未形成人工确认目标</div>
                <button className="s04-outline-action" type="button">确认目标</button>
              </div>
            </section>

            <section className="s04-hypothesis" aria-labelledby="s04-hypothesis-title">
              <div className="s04-section-heading">
                <h2 id="s04-hypothesis-title"><MdLightbulbOutline aria-hidden="true" />优化假设</h2>
                <span>待确认 · 不代表已证明根因</span>
              </div>
              <p>若 Agent 能明确获得退款 / 退货资格的适用条件、例外条件与必要事实，退款规则误用可能减少。</p>
              <button className="s04-outline-action" type="button">确认优化假设</button>
            </section>

            <section className="s04-changes" aria-labelledby="s04-changes-title">
              <h2 id="s04-changes-title"><MdHistory aria-hidden="true" />变更记录</h2>
              <div className="s04-table-frame">
                <table>
                  <thead>
                    <tr><th>范围</th><th>状态</th><th>详情</th></tr>
                  </thead>
                  <tbody>
                    {changeRecords.map((record) => (
                      <tr key={record.scope}>
                        <td>{record.scope}</td>
                        <td className={record.warning ? 's04-table-status--warning' : undefined}>{record.status}</td>
                        <td>{record.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="s04-validation" aria-label="验证计划草稿">
              <div className="s04-validation-plan">
                <h2><MdRule aria-hidden="true" />验证计划草稿</h2>
                <dl className="s04-plan-grid">
                  <div><dt>目标案例</dt><dd>6 个 <button type="button">查看</button></dd></div>
                  <div><dt>回归案例</dt><dd>8 个 <button type="button">查看</button></dd></div>
                  <div className="s04-plan-grid__wide"><dt>受保护能力</dt><dd>物流、商品咨询、售后 <button type="button">查看纳入原因与关联案例</button></dd></div>
                  <div><dt>配置 ID</dt><dd className="s04-mono-value">EVAL-CONFIG-V1-FINAL</dd></div>
                  <div><dt>策略</dt><dd>V1</dd></div>
                  <div className="s04-plan-grid__wide"><dt>基线快照</dt><dd className="s04-mono-value">BASELINE-VALIDATION-SNAPSHOT-V1</dd></div>
                  <div className="s04-plan-grid__wide"><dt>计划哈希</dt><dd className="s04-plan-pending">冻结后生成</dd></div>
                </dl>
              </div>

              <div className="s04-integrity">
                <h3>实验完整性规则</h3>
                <ul>
                  <li className="s04-integrity__warning"><MdRadioButtonUnchecked aria-hidden="true" />人工确认目标：未完成</li>
                  <li className="s04-integrity__warning"><MdRadioButtonUnchecked aria-hidden="true" />确认优化假设：未完成</li>
                  <li><MdRadioButtonUnchecked aria-hidden="true" />核对验证计划：待完成</li>
                  <li><MdRadioButtonUnchecked aria-hidden="true" />冻结验证计划：未完成</li>
                </ul>
                <p className="s04-lock-note"><MdLockOutline aria-hidden="true" />候选版本验证保持锁定，直到验证计划完成冻结。</p>
                <p className="s04-warning-note"><MdWarningAmber aria-hidden="true" />验证计划冻结前不得生成、导入或查看 Candidate 结果；如发生结果暴露，实验将进入 Compromised 状态，且必须开始新的验证。</p>
              </div>
            </section>
          </div>
        </div>
      </div>

      <footer className="s04-action-rail">
        <p>完成目标与优化假设确认，并冻结验证计划后解锁。</p>
        <div>
          <button type="button" disabled>冻结验证计划</button>
          <button type="button" disabled>进入候选版本验证<MdArrowForward aria-hidden="true" /></button>
        </div>
      </footer>

      <div className="s04-analyst-dock">
        <img src="/s04-analyst.jpg" alt="分析员 04" />
        <strong>分析员 04</strong>
      </div>
    </section>
  )
}

export default TargetPlanPage
