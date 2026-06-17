import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import apiClient from "../api/client";

const currency = (value) =>
  new Intl.NumberFormat("en-AE", { style: "currency", currency: "AED", maximumFractionDigits: 0 }).format(
    Number(value || 0)
  );

function StatCard({ label, value, accent }) {
  return (
    <div className="rounded-xl bg-white p-5 shadow-sm">
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className={`mt-2 text-2xl font-bold ${accent || "text-slate-900"}`}>{value}</p>
    </div>
  );
}

export default function Dashboard() {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    apiClient
      .get("/analytics/summary")
      .then((res) => setSummary(res.data))
      .catch((err) => setError(err.response?.data?.detail || "Failed to load dashboard summary"));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Overview</h1>
        <p className="text-sm text-slate-500">Live snapshot of claims, collections, and pipeline health.</p>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {summary && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Total Claims" value={summary.total_claims.toLocaleString()} />
          <StatCard label="Net Submitted" value={currency(summary.total_net_amount)} />
          <StatCard label="Total Collected" value={currency(summary.total_paid_amount)} accent="text-emerald-600" />
          <StatCard label="Total Denied" value={currency(summary.total_denial_amount)} accent="text-red-600" />
          <StatCard label="Active Clinical Profiles" value={summary.active_clinical_profiles.toLocaleString()} />
          <StatCard label="Pending DHA XML" value={summary.pending_raw_xml.toLocaleString()} accent="text-amber-600" />
          <StatCard label="Quarantined DHA XML" value={summary.quarantined_raw_xml.toLocaleString()} accent="text-red-600" />
          <StatCard label="Successful Logins (24h)" value={summary.recent_logins_24h.toLocaleString()} />
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Link
          to="/clinical-profiles"
          className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-ghaf-400 hover:shadow-md"
        >
          <h2 className="font-semibold text-slate-900">Clinical Profiles</h2>
          <p className="mt-1 text-sm text-slate-500">Set up and manage patient clinical profiles.</p>
        </Link>
        <Link
          to="/dha-sync"
          className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-ghaf-400 hover:shadow-md"
        >
          <h2 className="font-semibold text-slate-900">DHA XML Sync</h2>
          <p className="mt-1 text-sm text-slate-500">Upload and trigger the DHA Shafafiya sync pipeline.</p>
        </Link>
        <Link
          to="/analytics"
          className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-ghaf-400 hover:shadow-md"
        >
          <h2 className="font-semibold text-slate-900">Analytics &amp; Financial Insights</h2>
          <p className="mt-1 text-sm text-slate-500">Payer breakdowns, collections, and AR aging via Metabase.</p>
        </Link>
      </div>
    </div>
  );
}
