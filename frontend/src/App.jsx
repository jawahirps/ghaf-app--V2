import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import ProtectedRoute from "./components/ProtectedRoute";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import ClinicalProfiles from "./pages/ClinicalProfiles";
import DhaSync from "./pages/DhaSync";
import Analytics from "./pages/Analytics";
import LoginActivity from "./pages/LoginActivity";
import FacilitySettings from "./pages/FacilitySettings";

export default function App() {
  return (
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
  );
}
