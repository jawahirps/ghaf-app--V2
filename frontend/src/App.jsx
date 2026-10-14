import { Suspense, lazy } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import ProtectedRoute from "./components/ProtectedRoute";

const Login = lazy(() => import("./pages/Login"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const ClinicalProfiles = lazy(() => import("./pages/ClinicalProfiles"));
const DhaSync = lazy(() => import("./pages/DhaSync"));
const Analytics = lazy(() => import("./pages/Analytics"));
const LoginActivity = lazy(() => import("./pages/LoginActivity"));
const FacilitySettings = lazy(() => import("./pages/FacilitySettings"));

const routeFallback = (
  <div className="flex min-h-screen items-center justify-center bg-slate-50 text-sm text-slate-500">
    Loading page…
  </div>
);

export default function App() {
  return (
    <Suspense fallback={routeFallback}>
      <Routes>
        <Route path="/login" element={<Login />} />

        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/clinical-profiles" element={<ClinicalProfiles />} />
            <Route path="/dha-sync" element={<DhaSync />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/login-activity" element={<LoginActivity />} />
            <Route path="/facility-settings" element={<FacilitySettings />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
