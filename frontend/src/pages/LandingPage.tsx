import { Link } from 'react-router-dom'

import './LandingPage.css'

const steps = [
  {
    id: '01',
    title: '上传对话',
    detail: '导入真实客服会话（CSV / JSON），形成可复用的评测数据集，同一套流程支持演示数据与你的真实数据。',
  },
  {
    id: '02',
    title: 'AI 评测与问题定位',
    detail: '逐条评测每一次应答，失败自动归因，聚合成有证据、有严重度、有优先级的问题，而不是一堆零散的坏例子。',
  },
  {
    id: '03',
    title: '优化建议与版本验证',
    detail: '为每个目标问题生成优化建议，候选版本在同一范围内回归验证——改善、持平还是回归，用数据说话，最终由人决策。',
  },
]

function LandingPage() {
  return (
    <div className="lp-page">
      <header className="lp-header">
        <Link className="lp-brand" to="/" aria-label="SupportLens 首页">
          <svg className="lp-brand-mark" viewBox="0 0 32 32" aria-hidden="true">
            <path d="M18 3H8a2 2 0 0 0-2 2v22a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9l-6-6Z" />
            <path d="M18 3v6h6M11 13h7M11 17h6M11 21h4" />
            <circle cx="21" cy="22" r="5" />
            <path d="m24.75 25.75 4.25 4.25" />
          </svg>
          <span>SupportLens</span>
        </Link>
        <Link className="lp-header-cta" to="/review">进入控制台</Link>
      </header>

      <main className="lp-main">
        <section className="lp-hero">
          <p className="lp-kicker">AI 客服质量评测与优化平台</p>
          <h1 className="lp-hero-title">
            AI 客服上线后，答得好不好，
            <br />
            不再靠人工抽检猜。
          </h1>
          <p className="lp-hero-sub">
            SupportLens 自动评测每一条客服对话，把零散的失败聚合成有证据的问题，
            给出可验证的优化建议——让每次优化都从「感觉要改」走到「证明变好了」。
          </p>
          <div className="lp-hero-actions">
            <Link className="lp-btn lp-btn--primary" to="/review">在线看演示</Link>
            <a
              className="lp-btn lp-btn--ghost"
              href="https://github.com/GoodnightXu2002/supportlens"
              target="_blank"
              rel="noopener noreferrer"
            >
              GitHub 源码
            </a>
          </div>
          <p className="lp-hero-note">内置 NovaMart 演示数据集 · 无需注册 · 打开即可查看完整评测报告</p>
        </section>

        <section className="lp-steps" aria-label="产品三步流程">
          {steps.map((step) => (
            <article className="lp-step" key={step.id}>
              <span className="lp-step-id">{step.id}</span>
              <h2>{step.title}</h2>
              <p>{step.detail}</p>
            </article>
          ))}
        </section>

        <section className="lp-sample" aria-label="评测报告示例">
          <h2 className="lp-section-title">一份评测报告长什么样</h2>
          <p className="lp-section-sub">以下内容节选自线上演示运行的真实评测结果（NovaMart 合成数据 · 真实模型判定）。</p>

          <div className="lp-report">
            <div className="lp-report-toolbar">
              <span className="lp-report-dot" aria-hidden="true" />
              <span>SupportLens · 基线分析</span>
              <span className="lp-report-run">运行 D4EE4971 · 已完成</span>
            </div>

            <div className="lp-report-stats">
              <div><strong>100</strong><span>评测案例</span></div>
              <div><strong>15</strong><span>问题聚类</span></div>
              <div><strong>8</strong><span>本轮核心案例</span></div>
            </div>

            <div className="lp-report-problem">
              <p className="lp-report-problem-title">
                退款 · 当前客服回复判定：<strong>失败（不完整 / 未解决）</strong>
              </p>
              <blockquote>
                <span>用户</span>
                订单号尾号4821那单我刚发过了，帮我看下退款卡在哪。
              </blockquote>
              <blockquote>
                <span>客服</span>
                请把完整订单号、付款截图、手机号和退款申请截图都再发一次，我才能处理。
              </blockquote>
              <p className="lp-report-verdict">
                AI 归因：要求用户重复提供系统内已有的信息，未告知退款卡在仓库验收环节，用户的核心查询未获解决。
              </p>
            </div>

            <div className="lp-report-suggest">
              <span>系统建议</span>
              <p>打通订单系统内的退款状态查询，话术改为主动告知退款进度，并冻结为候选版本的验证目标。</p>
            </div>
          </div>
        </section>
      </main>

      <footer className="lp-footer">
        <p>SupportLens · 个人独立开发项目（MVP）</p>
        <p>
          作者 许文龙 ·
          {' '}
          <a href="mailto:2749419902@qq.com">2749419902@qq.com</a>
          {' · '}
          <a href="https://github.com/GoodnightXu2002/supportlens" target="_blank" rel="noopener noreferrer">GitHub</a>
        </p>
      </footer>
    </div>
  )
}

export default LandingPage
