import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import AppShell from './components/AppShell'
import BaselineAnalysisPage from './pages/BaselineAnalysisPage'
import CandidateValidationPage from './pages/CandidateValidationPage'
import DatasetPage from './pages/DatasetPage'
import StartQualityReviewPage from './pages/StartQualityReviewPage'
import TargetPlanPage from './pages/TargetPlanPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/review" replace />} />
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
