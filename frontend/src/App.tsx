import { BrowserRouter, Route, Routes } from 'react-router-dom'

import AppShell from './components/AppShell'
import BaselineAnalysisPage from './pages/BaselineAnalysisPage'
import CandidateValidationPage from './pages/CandidateValidationPage'
import DatasetPage from './pages/DatasetPage'
import LandingPage from './pages/LandingPage'
import StartQualityReviewPage from './pages/StartQualityReviewPage'
import TargetPlanPage from './pages/TargetPlanPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route element={<AppShell />}>
          <Route path="review" element={<StartQualityReviewPage />} />
          <Route path="dataset" element={<DatasetPage />} />
          <Route path="baseline" element={<BaselineAnalysisPage />} />
          <Route path="target-plan" element={<TargetPlanPage />} />
          <Route path="validation" element={<CandidateValidationPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
