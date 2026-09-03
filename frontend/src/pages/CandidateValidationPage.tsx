import { useState } from 'react'
import {
  MdAnalytics,
  MdArrowForward,
  MdChatBubble,
  MdCheckCircle,
  MdFactCheck,
  MdForum,
  MdMenuBook,
  MdOpenInNew,
  MdPerson,
  MdSmartToy,
  MdVerified,
} from 'react-icons/md'

import './CandidateValidationPage.css'

const targetCases = [
  { id: 'T01', caseId: 'CASE-NM-T01', movement: '明确改善 IMPROVED', clear: true },
  { id: 'T02', caseId: 'CASE-NM-T02', movement: '明确改善 IMPROVED', clear: true },
  { id: 'T03', caseId: 'CASE-NM-T03', movement: '明确改善 IMPROVED', clear: true },
  { id: 'T04', caseId: 'CASE-NM-T04', movement: '部分改善 PARTIALLY IMPROVED', clear: false },
  { id: 'T05', caseId: 'CASE-NM-T05', movement: '明确改善 IMPROVED', clear: true },
  { id: 'T06', caseId: 'CASE-NM-T06', movement: '明确改善 IMPROVED', clear: true },
] as const

const lineage = [
  'VALIDATION-PLAN-V1 — FROZEN',
  'AGENT-GENERATION-CONTRACT-V1',
  'EVAL-CONFIG-V1-FINAL',
  'BASELINE-RUN-001',
  'CANDIDATE-RUN-001',
  'BASELINE-VALIDATION-SNAPSHOT-V1',
  'CHANGE-SET-V1',
  'CANDIDATE-DECISION-POLICY-V1',
]

const recommendationGates = [
  ['实验有效性', '有效 VALID'],
  ['目标门槛', 'PASS (5/6)'],
  ['目标变差', '0 (PASS)'],
  ['严重回归', '0 (PASS)'],
  ['重大回归', '0 (PASS)'],
  ['轻微回归', '1（符合政策 WITHIN POLICY）'],
  ['其他问题门槛', 'PASS'],
  ['剩余必需人工复核', '0 (PASS)'],
  ['实验完整性', '有效 VALID'],
  ['证据充分性', '有效 VALID'],
] as const

type ComparisonNodeProps = {
  accent?: boolean
  icon: React.ReactNode
  label: string
  children: React.ReactNode
}

function ComparisonNode({ accent = false, icon, label, children }: ComparisonNodeProps) {
  return (
    <div className={accent ? 's05-node s05-node--candidate' : 's05-node'}>
      <span className="s05-node__icon" aria-hidden="true">{icon}</span>
      <div className="s05-node__content">
        <span className="s05-node__label">{label}</span>
        {children}
      </div>
    </div>
  )
}

function CandidateValidationPage() {
  const [selectedId, setSelectedId] = useState('T01')
  const selectedCase = targetCases.find((item) => item.id === selectedId) ?? targetCases[0]

  return (
    <section className="s05-page" aria-label="候选版本验证工作区">
      <div className="s05-canvas">
        <section className="s05-metadata" aria-label="候选版本验证上下文">
          <div><span>数据集</span><strong>DS-NOVAMART-001 v1.0</strong></div>
          <div><span>基线版本</span><strong>Customer Support Agent V1 (v1.0)</strong></div>
          <div><span>候选版本</span><strong>PRODUCT-NOVAMART-CS-V2-CANDIDATE</strong></div>
          <div><span>结论范围</span><strong>仅限当前评测集</strong></div>
        </section>

        <section className="s05-status" aria-label="实验状态与追溯链">
          <div className="s05-status-chips">
            <span>运行：已完成 COMPLETED</span>
            <span>业务阻断：无 NONE</span>
            <span>实验完整性：有效 VALID</span>
            <span>人工最终决策：— / 暂无 NOT AVAILABLE</span>
          </div>
          <div className="s05-status-details">
            <div className="s05-lineage">
              <h2>实验追溯链</h2>
              {lineage.map((item) => <code key={item}>{item}</code>)}
            </div>
            <div className="s05-gates">
              <h2>状态门槛</h2>
              <div>
                <span>实际变更——已验证 VERIFIED</span>
                <span>候选版本生成门槛——通过 PASS</span>
                <span>基线版本 / 候选版本生成一致性——有效 VALID</span>
                <span>评测配置兼容性——兼容 COMPATIBLE</span>
                <span>目标 / 回归 / 核心必需结果——完整 COMPLETE</span>
              </div>
              <p>基线版本与候选版本使用相同的 Agent 生成机制、运行参数、输入组装、工具配置、生成策略和最终评测配置。唯一允许的差异：CHANGE-SET-V1。</p>
            </div>
          </div>
        </section>

        <section className="s05-outcomes" aria-label="目标与回归结果">
          <article className="s05-outcome-card">
            <MdCheckCircle className="s05-outcome-icon" aria-hidden="true" />
            <div>
              <h2>目标改善 (TARGET-PROBLEM-V1)</h2>
              <dl>
                <div><dt>TARGET-VALIDATION-SET-V1</dt><dd>6 个案例</dd></div>
                <div><dt>明确改善</dt><dd className="s05-positive">5 / 6 (83%)</dd></div>
                <div><dt>部分改善</dt><dd>1 / 6</dd></div>
                <div><dt>目标变差</dt><dd>0</dd></div>
                <div><dt>剩余目标高/严重等级 HIGH/CRITICAL</dt><dd>0</dd></div>
                <div><dt>无法得出结论的目标案例</dt><dd>0</dd></div>
                <div><dt>证据不足案例</dt><dd>0</dd></div>
              </dl>
            </div>
          </article>

          <article className="s05-outcome-card s05-regression-card">
            <MdVerified className="s05-outcome-icon" aria-hidden="true" />
            <div>
              <h2>回归检查 (REGRESSION-SET-V1：8 个案例)</h2>
              <div className="s05-regression-grid">
                <dl>
                  <div><dt>严重回归 CRITICAL</dt><dd>0 — PASS</dd></div>
                  <div><dt>重大回归 MAJOR</dt><dd>0 — PASS</dd></div>
                </dl>
                <dl>
                  <div className="s05-minor-regression"><dt>轻微回归 MINOR</dt><dd>1 — 符合政策 WITHIN POLICY <button type="button"><MdOpenInNew aria-hidden="true" />查看详情</button></dd></div>
                </dl>
                <dl>
                  <div><dt>新系统性问题</dt><dd>0 — PASS</dd></div>
                  <div><dt>受保护能力退化</dt><dd>0 — PASS</dd></div>
                  <div><dt>剩余必需人工复核</dt><dd>0 — PASS</dd></div>
                </dl>
              </div>
              <p>严重回归 CRITICAL 或重大回归 MAJOR 任一出现，均阻断接受。</p>
            </div>
          </article>
        </section>

        <section className="s05-case-tabs" aria-label="目标案例选择">
          <strong>目标案例（6）：</strong>
          <div>
            {targetCases.map((item) => (
              <button
                className={item.id === selectedCase.id ? 's05-case-tab s05-case-tab--active' : 's05-case-tab'}
                key={item.id}
                type="button"
                aria-pressed={item.id === selectedCase.id}
                onClick={() => setSelectedId(item.id)}
              >
                {item.id}{item.id === 'T04' ? '（部分改善）' : ''}
              </button>
            ))}
          </div>
        </section>

        <section className="s05-comparison" aria-labelledby="s05-comparison-title">
          <header className="s05-comparison-header">
            <h2 id="s05-comparison-title"><span>案例 ID：</span>{selectedCase.caseId}<em>相同案例 ID、会话与案例事实——已验证 VERIFIED</em></h2>
            <div><span><i />基线版本 V1</span><span><i />候选版本 V2</span></div>
          </header>

          <div className="s05-comparison-body">
            <ComparisonNode icon={<MdChatBubble />} label="会话 / 用户消息">
              <p>[{selectedCase.caseId}: User Message]</p>
            </ComparisonNode>

            <div className="s05-version-columns">
              <div className="s05-version-column">
                <ComparisonNode icon={<MdForum />} label="回复"><p>[{selectedCase.caseId}: Baseline Response]</p></ComparisonNode>
                <ComparisonNode icon={<MdSmartToy />} label="AI 原始判定"><p className="s05-node-box">[{selectedCase.caseId}: Baseline AI Original Judgment]</p></ComparisonNode>
                <ComparisonNode icon={<MdPerson />} label="人工复核"><p>[{selectedCase.caseId}: Baseline Human Review]</p></ComparisonNode>
                <ComparisonNode icon={<MdVerified />} label="最终生效结果"><p className="s05-node-box s05-effective-result"><span>判定：失败 FAILURE</span><em>已生效</em></p></ComparisonNode>
                <ComparisonNode icon={<MdAnalytics />} label="回复证据"><p>[{selectedCase.caseId}: Baseline Response Evidence]</p></ComparisonNode>
              </div>

              <div className="s05-movement">
                <span><MdArrowForward aria-hidden="true" /></span>
                <strong>案例变化：{selectedCase.movement}</strong>
                <dl>
                  <div><dt>明确改善</dt><dd>{selectedCase.clear ? 1 : 0}</dd></div>
                  <div><dt>目标变差</dt><dd>0</dd></div>
                  <div><dt>实质性问题</dt><dd>0</dd></div>
                </dl>
              </div>

              <div className="s05-version-column s05-version-column--candidate">
                <ComparisonNode accent icon={<MdForum />} label="回复"><p>[{selectedCase.caseId}: Candidate Response]</p></ComparisonNode>
                <ComparisonNode accent icon={<MdSmartToy />} label="AI 原始判定"><p className="s05-node-box">[{selectedCase.caseId}: Candidate AI Original Judgment]</p></ComparisonNode>
                <ComparisonNode accent icon={<MdPerson />} label="人工复核"><p>[{selectedCase.caseId}: Candidate Human Review]</p></ComparisonNode>
                <ComparisonNode accent icon={<MdVerified />} label="最终生效结果"><p className="s05-node-box s05-effective-result s05-effective-result--candidate"><span>判定：成功 SUCCESS</span><em>已生效</em></p></ComparisonNode>
                <ComparisonNode accent icon={<MdAnalytics />} label="回复证据"><p>[{selectedCase.caseId}: Candidate Response Evidence]</p></ComparisonNode>
              </div>
            </div>

            <div className="s05-shared-evidence">
              <ComparisonNode icon={<MdFactCheck />} label="案例事实"><p>[{selectedCase.caseId}: Case Facts]</p></ComparisonNode>
              <ComparisonNode icon={<MdMenuBook />} label="参考依据"><p>[{selectedCase.caseId}: Reference Evidence]</p></ComparisonNode>
            </div>
          </div>
        </section>

        <section className="s05-decision" aria-label="候选版本决策">
          <article className="s05-recommendation">
            <span className="s05-eyebrow">系统建议 · CANDIDATE-DECISION-POLICY-V1</span>
            <h2>接受 ACCEPT</h2>
            <dl>
              {recommendationGates.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
            </dl>
            <p><span aria-hidden="true" />非最终结论——等待人工最终决策</p>
          </article>

          <article className="s05-human-decision">
            <header><span className="s05-eyebrow">人工最终决策</span><div><img src="/s04-analyst.jpg" alt="分析员 04" /><span>分析员 04</span></div></header>
            <textarea aria-label="决策理由" placeholder="必须填写决策理由。仅当人工最终决策与系统建议不一致时，必须填写改判理由。" />
            <dl>
              <div><dt>决策状态</dt><dd>— / 暂无 NOT AVAILABLE</dd></div>
              <div><dt>系统建议最终性</dt><dd>非最终结论——等待人工最终决策</dd></div>
            </dl>
          </article>
        </section>

        <section className="s05-claim-boundary" aria-label="结论边界">
          <strong>相同案例 ID、会话与案例事实——已验证 VERIFIED。</strong>
          <em>合成的类生产评测样例；结论仅适用于当前评测集、配置、政策与运行追溯链。</em>
          <span>接受仅表示本轮候选版本验证通过，不代表上线、部署、发布或投产。</span>
        </section>
      </div>

      <footer className="s05-action-rail">
        <em>VALIDATION-PLAN-V1（状态：已冻结 FROZEN）</em>
        <div><button type="button">继续迭代</button><button type="button"><MdVerified aria-hidden="true" />接受候选版本</button></div>
      </footer>

      <div className="s05-analyst-dock"><img src="/s04-analyst.jpg" alt="" /><strong>分析员 04</strong></div>
    </section>
  )
}

export default CandidateValidationPage
