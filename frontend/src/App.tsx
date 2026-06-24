import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { Layout } from './Layout';
import { Dashboard } from './pages/Dashboard';
import { HowItWorks } from './pages/HowItWorks';
import { HowIWork } from './pages/HowIWork';

/**
 * App root: the router. The dashboard lives at `/`; the two static explainer pages hang off the
 * shared `Layout` (Epic 16). Routing is client-side, so the prod server must serve `index.html` for
 * any non-asset path (SPA fallback, Epic 19).
 */
export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/how-it-works" element={<HowItWorks />} />
          <Route path="/how-i-work" element={<HowIWork />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
