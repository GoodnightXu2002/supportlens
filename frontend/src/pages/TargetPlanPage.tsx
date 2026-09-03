import {
  MdArrowForward,
  MdCheckCircle,
  MdDescription,
  MdHistory,
  MdInfo,
  MdLightbulbOutline,
  MdLockOutline,
  MdPersonOutline,
  MdPsychology,
  MdRadioButtonUnchecked,
  MdRule,
  MdSmartToy,
  MdWarningAmber,
} from 'react-icons/md'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import './TargetPlanPage.css'

type TargetPlanState = 'pre-freeze' | 'frozen'

const preFreezeChangeRecords = [
  { scope: '指令／参考依据使用', status: '计划草稿', detail: '强化外部 Agent 指令 / 参考依据使用的检查要求', tone: 'warning' },
  { scope: '系统配置', status: '保持不变 · 待冻结', detail: 'Agent 生成机制、运行环境、数据集、评测配置与策略保持不变。', tone: 'neutral' },
  { scope: '实际变更', status: '未开始', detail: '—', tone: 'neutral' },
  { scope: '偏差', status: '不适用', detail: '—', tone: 'neutral' },
] as const

const frozenChangeRecords = [
  { scope: '指令/参考依据使用', status: '已冻结 FROZEN', detail: '强化退款资格条件、例外条件与必要事实的检查要求', tone: 'frozen' },
  { scope: '系统配置', status: '已冻结 FROZEN', detail: 'Agent 生成机制、运行环境、数据集、评测配置与策略', tone: 'frozen' },
  { scope: '实际变更', status: '已验证 VERIFIED', detail: '外部 Agent 已按声明的变更集（Change Set）完成修改', tone: 'verified' },
  { scope: '偏差', status: '无偏差 NONE', detail: '实际变更与计划变更无偏差', tone: 'frozen' },
] as const

function ContextMetadata() {
  return (
    <dl className="s04-metadata s04-metadata--prefreeze">
      <div><dt>数据集</dt><dd>DS-NOVAMART-001 v1.0</dd></div>
      <div><dt>数据类型</dt><dd>Synthetic Production-like</dd></div>
      <div><dt>声明范围</dt><dd>Evaluation Set</dd></div>
    </dl>
  )
}

type TargetPlanWorkspaceProps = {
  state: TargetPlanState
  targetConfirmed: boolean
  hypothesisConfirmed: boolean
  onConfirmTarget: () => void
  onConfirmHypothesis: () => void
  onFreeze: () => void
  onEnterValidation: () => void
}

function TargetPlanWorkspace({
  state,
  targetConfirmed,
  hypothesisConfirmed,
  onConfirmTarget,
  onConfirmHypothesis,
  onFreeze,
  onEnterValidation,
}: TargetPlanWorkspaceProps) {
  const frozen = state === 'frozen'
  const readyToFreeze = targetConfirmed && hypothesisConfirmed
  const changeRecords = frozen ? frozenChangeRecords : preFreezeChangeRecords
  const canvasRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    canvasRef.current?.scrollTo({ top: 0 })
  }, [state])

  return (
    <section className={`s04-page s04-page--${state}`} aria-label={frozen ? '目标与计划已冻结状态' : '目标与计划冻结前状态'}>
      {frozen ? (
        <div className="s04-frozen-header-status" aria-label="当前状态">
          <span><MdLockOutline aria-hidden="true" />主要状态：验证计划已冻结</span>
          <span><MdInfo aria-hidden="true" />结论属性：非最终结论</span>
        </div>
      ) : (
        <>
          <div className="s04-header-status" aria-label={readyToFreeze ? '当前状态：确认已完成' : '当前状态：需要人工确认'}><span aria-hidden="true" />{readyToFreeze ? '确认已完成' : '需要人工确认'}</div>
          <MdLockOutline className="s04-candidate-lock" aria-hidden="true" />
        </>
      )}

      {frozen && (
        <div className="s04-canvas s04-canvas--frozen-meta">
          <div className="s04-content">
            <ContextMetadata />
          </div>
        </div>
      )}

      <div ref={canvasRef} className={frozen ? 's04-canvas s04-canvas--frozen' : 's04-canvas'}>
        <div className={frozen ? 's04-content s04-content--frozen' : 's04-content'}>
          {!frozen && <ContextMetadata />}
          {!frozen && (
            <header className="s04-state">
              <div className="s04-state__title"><span aria-hidden="true" /><h1>验证计划待冻结</h1></div>
              <dl><div><dt>结论属性:</dt><dd>非最终结论</dd></div><div><dt>当前阻断:</dt><dd>{readyToFreeze ? '无 · 可冻结验证计划' : '人工目标与优化假设尚未完成确认'}</dd></div></dl>
            </header>
          )}

          <div className={frozen ? 's04-sections s04-sections--frozen' : 's04-sections'}>
            <section className={frozen ? 's04-targets s04-targets--frozen' : 's04-targets'} aria-label="目标确认">
              <div className="s04-target-column">
                {frozen ? (
                  <>
                    <div className="s04-frozen-eyebrow"><MdSmartToy aria-hidden="true" />AI 建议目标</div>
                    <p className="s04-frozen-target-name">退款资格判断准确性</p>
                    <div className="s04-frozen-recommendation">
                      <span>推荐依据</span>
                      <div><code>P-REFUND-01</code><strong>优先级 #1</strong><span>（6 个受影响案例）</span></div>
                      <button className="s04-text-action" type="button">查看 6 个目标案例与证据</button>
                    </div>
                  </>
                ) : (
                  <>
                    <h2><MdPsychology aria-hidden="true" />AI 推荐目标</h2>
                    <div className="s04-target-value">退款资格判断准确性</div>
                    <div className="s04-target-tags" aria-label="目标相关信息"><span>P-REFUND-01</span><span className="s04-target-tags__priority">优先级 #1</span><span>6 个受影响案例</span></div>
                    <button className="s04-text-action" type="button">查看 6 个目标案例与证据<MdArrowForward aria-hidden="true" /></button>
                  </>
                )}
              </div>

              <div className={frozen ? 's04-target-column s04-target-column--frozen-human' : 's04-target-column s04-target-column--human'}>
                {frozen ? (
                  <>
                    <MdCheckCircle className="s04-frozen-confirmed-icon" aria-label="已确认" />
                    <div className="s04-frozen-eyebrow s04-frozen-eyebrow--confirmed"><MdPersonOutline aria-hidden="true" />人工目标确认</div>
                    <p className="s04-frozen-confirmed-target">已确认目标： 退款资格判断准确性</p>
                    <div className="s04-frozen-confirmation-meta"><span>确认人： Analyst 04</span><span>确认时间： 2024-05-24 14:10 UTC</span></div>
                    <div className="s04-frozen-contract"><button className="s04-text-action" type="button"><MdDescription aria-hidden="true" />查看目标定义契约</button></div>
                  </>
                ) : (
                  <>
                    <div className="s04-section-heading"><h2><MdPersonOutline aria-hidden="true" />人工目标确认</h2><span className={targetConfirmed ? 's04-confirmation-status--complete' : undefined}>{targetConfirmed ? '已确认' : '待人工确认'}</span></div>
                    <div className={targetConfirmed ? 's04-empty-target s04-empty-target--confirmed' : 's04-empty-target'}>{targetConfirmed ? '退款资格判断准确性' : '尚未形成人工确认目标'}</div>
                    <button className="s04-outline-action" type="button" onClick={onConfirmTarget} disabled={targetConfirmed}>{targetConfirmed ? '目标已确认' : '确认目标'}</button>
                  </>
                )}
              </div>
            </section>

            <section className={frozen ? 's04-hypothesis s04-hypothesis--frozen' : 's04-hypothesis'} aria-labelledby="s04-hypothesis-title">
              {frozen ? (
                <><h2 id="s04-hypothesis-title" className="s04-frozen-section-label"><span aria-hidden="true" />优化假设</h2><p>若 Agent 能明确获得退款 / 退货资格的适用条件、例外条件与必要事实，退款规则误用可能减少。</p><em>待验证假设，不代表已证明根因（Root Cause）</em></>
              ) : (
                <><div className="s04-section-heading"><h2 id="s04-hypothesis-title"><MdLightbulbOutline aria-hidden="true" />优化假设</h2><span className={hypothesisConfirmed ? 's04-confirmation-status--complete' : undefined}>{hypothesisConfirmed ? '已确认 · 不代表已证明根因' : '待确认 · 不代表已证明根因'}</span></div><p>若 Agent 能明确获得退款 / 退货资格的适用条件、例外条件与必要事实，退款规则误用可能减少。</p><button className="s04-outline-action" type="button" onClick={onConfirmHypothesis} disabled={hypothesisConfirmed}>{hypothesisConfirmed ? '优化假设已确认' : '确认优化假设'}</button></>
              )}
            </section>

            <section className={frozen ? 's04-changes s04-changes--frozen' : 's04-changes'} aria-labelledby="s04-changes-title">
              {frozen ? <h2 id="s04-changes-title">变更记录</h2> : <h2 id="s04-changes-title"><MdHistory aria-hidden="true" />变更记录</h2>}
              <div className={frozen ? 's04-table-frame s04-table-frame--frozen' : 's04-table-frame'}>
                <table><thead><tr><th>{frozen ? '记录项' : '范围'}</th><th>状态</th><th>详情</th></tr></thead><tbody>
                  {changeRecords.map((record) => <tr key={record.scope}><td>{record.scope}</td><td className={!frozen && record.tone === 'warning' ? 's04-table-status--warning' : undefined}>{frozen ? <span className={`s04-record-badge s04-record-badge--${record.tone}`}>{record.status}</span> : record.status}</td><td>{record.detail}</td></tr>)}
                </tbody></table>
              </div>
            </section>

            {frozen ? (
              <section className="s04-frozen-validation" aria-label="已冻结验证计划">
                <div className="s04-frozen-plan">
                  <header className="s04-frozen-plan__header">
                    <div><h2><MdLockOutline aria-hidden="true" />验证计划</h2><span>原始冻结计划：只读</span></div>
                    <div><button type="button">创建新计划版本</button><p><strong>VALIDATION-PLAN-V1</strong><span>计划哈希： 7A92-C18F-04D7</span></p></div>
                  </header>
                  <p className="s04-frozen-plan__notice">Candidate 暴露前如需修改，必须创建新版本并重新冻结；不得覆盖原始冻结计划。</p>
                  <div className="s04-frozen-plan__body">
                    <div className="s04-frozen-count"><span>目标案例</span><strong>6 个案例</strong><button type="button">查看</button></div>
                    <div className="s04-frozen-count"><span>回归案例</span><strong>8 个案例</strong><button type="button">查看</button></div>
                    <div className="s04-frozen-capabilities"><div><span>受保护能力</span><button type="button">查看纳入原因与关联案例</button></div><p><span>物流</span><span>商品咨询</span><span>售后</span></p></div>
                    <div className="s04-frozen-config"><span>技术配置</span><ul><li>评测配置： EVAL-CONFIG-V1-FINAL <button type="button">查看配置</button> | <strong>兼容性：通过</strong>（与基线验证快照兼容）</li><li>候选决策策略： V1 <button type="button">查看策略</button></li><li>基线快照： <code>SNAPSHOT-S03-FINAL-FROZEN</code> <button type="button">查看快照</button></li></ul></div>
                  </div>
                  <footer className="s04-frozen-plan__footer"><span>冻结人：Analyst 04</span><span>2024-05-24 14:30 UTC</span></footer>
                </div>

                <aside className="s04-frozen-integrity">
                  <div><h3><MdRule aria-hidden="true" />实验完整性规则</h3><p>Baseline 与 Candidate 必须使用相同的 Agent 生成机制和运行环境，仅允许声明的变更集（Change Set）变量不同。实验一旦进入 Compromised 状态，不可原地恢复；恢复方式：开始新的验证。</p><div className="s04-frozen-warning"><MdWarningAmber aria-hidden="true" /><p>Candidate 在计划冻结前被生成、导入或查看，将导致实验完整性受损，且不可原地恢复。必须开始新的验证。</p></div></div>
                  <footer><span>完整性状态</span><strong><MdCheckCircle aria-hidden="true" />Candidate 暴露状态：未暴露</strong></footer>
                </aside>
              </section>
            ) : (
              <section className="s04-validation" aria-label="验证计划草稿">
                <div className="s04-validation-plan"><h2><MdRule aria-hidden="true" />验证计划草稿</h2><dl className="s04-plan-grid"><div><dt>目标案例</dt><dd>6 个 <button type="button">查看</button></dd></div><div><dt>回归案例</dt><dd>8 个 <button type="button">查看</button></dd></div><div className="s04-plan-grid__wide"><dt>受保护能力</dt><dd>物流、商品咨询、售后 <button type="button">查看纳入原因与关联案例</button></dd></div><div><dt>配置 ID</dt><dd className="s04-mono-value">EVAL-CONFIG-V1-FINAL</dd></div><div><dt>策略</dt><dd>V1</dd></div><div className="s04-plan-grid__wide"><dt>基线快照</dt><dd className="s04-mono-value">BASELINE-VALIDATION-SNAPSHOT-V1</dd></div><div className="s04-plan-grid__wide"><dt>计划哈希</dt><dd className="s04-plan-pending">冻结后生成</dd></div></dl></div>
                <div className="s04-integrity">
                  <h3>实验完整性规则</h3>
                  <ul>
                    <li className={targetConfirmed ? 's04-integrity__complete' : 's04-integrity__warning'}>{targetConfirmed ? <MdCheckCircle aria-hidden="true" /> : <MdRadioButtonUnchecked aria-hidden="true" />}人工确认目标：{targetConfirmed ? '已完成' : '未完成'}</li>
                    <li className={hypothesisConfirmed ? 's04-integrity__complete' : 's04-integrity__warning'}>{hypothesisConfirmed ? <MdCheckCircle aria-hidden="true" /> : <MdRadioButtonUnchecked aria-hidden="true" />}确认优化假设：{hypothesisConfirmed ? '已完成' : '未完成'}</li>
                    <li><MdRadioButtonUnchecked aria-hidden="true" />核对验证计划：{readyToFreeze ? '已完成' : '待完成'}</li>
                    <li><MdRadioButtonUnchecked aria-hidden="true" />冻结验证计划：未完成</li>
                  </ul>
                  <p className="s04-lock-note"><MdLockOutline aria-hidden="true" />候选版本验证保持锁定，直到验证计划完成冻结。</p>
                  <p className="s04-warning-note"><MdWarningAmber aria-hidden="true" />验证计划冻结前不得生成、导入或查看 Candidate 结果；如发生结果暴露，实验将进入 Compromised 状态，且必须开始新的验证。</p>
                </div>
              </section>
            )}
          </div>
        </div>
      </div>

      {frozen ? (
        <footer className="s04-action-rail s04-action-rail--frozen"><div><strong>候选版本门槛：已就绪</strong><span>验证计划已冻结、实际变更已验证、Candidate 结果未暴露、当前为非最终结论。</span></div><button type="button" onClick={onEnterValidation}>进入候选版本验证<MdArrowForward aria-hidden="true" /></button></footer>
      ) : (
        <footer className="s04-action-rail"><p>{readyToFreeze ? '所有必要确认已完成，可以冻结验证计划。' : '完成目标与优化假设确认，并冻结验证计划后解锁。'}</p><div><button className={readyToFreeze ? 's04-freeze-action--ready' : undefined} type="button" onClick={onFreeze} disabled={!readyToFreeze}>冻结验证计划</button><button type="button" disabled>进入候选版本验证<MdArrowForward aria-hidden="true" /></button></div></footer>
      )}

      <div className={frozen ? 's04-analyst-dock s04-analyst-dock--frozen' : 's04-analyst-dock'}><img src="/s04-analyst.jpg" alt="Analyst 04" /><div><strong>{frozen ? 'Analyst 04' : '分析员 04'}</strong>{frozen && <span>ID: AN-8842</span>}</div></div>
    </section>
  )
}

function TargetPlanPage() {
  const navigate = useNavigate()
  const [state, setState] = useState<TargetPlanState>('pre-freeze')
  const [targetConfirmed, setTargetConfirmed] = useState(false)
  const [hypothesisConfirmed, setHypothesisConfirmed] = useState(false)

  return (
    <TargetPlanWorkspace
      state={state}
      targetConfirmed={targetConfirmed}
      hypothesisConfirmed={hypothesisConfirmed}
      onConfirmTarget={() => setTargetConfirmed(true)}
      onConfirmHypothesis={() => setHypothesisConfirmed(true)}
      onFreeze={() => {
        if (targetConfirmed && hypothesisConfirmed) setState('frozen')
      }}
      onEnterValidation={() => navigate('/validation')}
    />
  )
}

export default TargetPlanPage
