import { useEffect, useState } from "react";
import apiClient from "../api/client";

export default function LoginActivity() {
  const [logs, setLogs] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient
      .get("/auth/login-logs")
      .then((res) => setLogs(res.data))
      .catch((err) => setError(err.response?.data?.detail || "Failed to load login activity"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Login Activity</h1>
        <p className="text-sm text-slate-500">Audit trail of authentication attempts across the platform.</p>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="overflow-hidden rounded-xl bg-white shadow-sm">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-2 text-left font-semibold text-slate-600">Time</th>
              <th className="px-4 py-2 text-left font-semibold text-slate-600">Email</th>
              <th className="px-4 py-2 text-left font-semibold text-slate-600">Result</th>
              <th className="px-4 py-2 text-left font-semibold text-slate-600">IP Address</th>
              <th className="px-4 py-2 text-left font-semibold text-slate-600">User Agent</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-400">Loading…</td>
              </tr>
            )}
            {!loading && logs.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-400">No login activity recorded yet.</td>
              </tr>
            )}
            {logs.map((log) => (
              <tr key={log.id} className="hover:bg-slate-50">
                <td className="px-4 py-2 text-slate-600">{new Date(log.created_at).toLocaleString()}</td>
                <td className="px-4 py-2 text-slate-800">{log.email_attempted}</td>
                <td className="px-4 py-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      log.success ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"
                    }`}
                  >
                    {log.success ? "Success" : log.failure_reason || "Failed"}
                  </span>
                </td>
                <td className="px-4 py-2 text-slate-600">{log.ip_address || "—"}</td>
                <td className="max-w-xs truncate px-4 py-2 text-slate-500" title={log.user_agent || ""}>
                  {log.user_agent || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
