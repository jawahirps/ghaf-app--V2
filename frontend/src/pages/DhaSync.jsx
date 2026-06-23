import { useEffect, useState } from "react";
import apiClient from "../api/client";
import { useAuth } from "../context/AuthContext";

const statusColors = {
  pending: "bg-amber-100 text-amber-700",
  parsed: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
  quarantined: "bg-red-100 text-red-700",
  running: "bg-blue-100 text-blue-700",
  success: "bg-emerald-100 text-emerald-700",
  partial: "bg-amber-100 text-amber-700",
};

function StatusBadge({ status }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusColors[status] || "bg-slate-200 text-slate-600"}`}>
      {status}
    </span>
  );
}

export default function DhaSync() {
  const { user } = useAuth();
  const [xmlType, setXmlType] = useState("ClaimSubmission");
  const [submissionDate, setSubmissionDate] = useState("");
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  const [rawXml, setRawXml] = useState([]);
  const [fetchLogs, setFetchLogs] = useState([]);

  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [fetching, setFetching] = useState(false);
  const [loadingTables, setLoadingTables] = useState(false);

  // Facility selector — admins can pick any facility; persisted across refreshes
  const [facilities, setFacilities] = useState([]);
  const [selectedFacilityId, setSelectedFacilityId] = useState(() => {
    const saved = localStorage.getItem("ghaf_dha_facility_id");
    return saved ? Number(saved) : (user?.facility_id || 13);
  });
  const [facilitiesError, setFacilitiesError] = useState(null);

  // Resolved facility_id: user selection takes priority, then user's own facility
  const activeFacilityId = selectedFacilityId || user?.facility_id;

  const loadTables = async (facilityId) => {
    const fid = facilityId ?? activeFacilityId;
    setLoadingTables(true);
    setError(null);
    try {
      const params = fid ? { facility_id: fid } : {};
      const [rawRes, logRes] = await Promise.all([
        apiClient.get("/dha-sync/raw-xml", { params }),
        apiClient.get("/dha-sync/fetch-logs", { params }),
      ]);
      setRawXml(rawRes.data);
      setFetchLogs(logRes.data);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to load DHA sync history");
    } finally {
      setLoadingTables(false);
    }
  };

  const handleFacilityChange = (id) => {
    setSelectedFacilityId(id);
    localStorage.setItem("ghaf_dha_facility_id", id);
  };

  useEffect(() => {
    // Load facility list for the selector
    fetch("/api/facilities", {
      headers: { Authorization: `Bearer ${localStorage.getItem("ghaf_token")}` },
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setFacilities(Array.isArray(data) ? data : []);
      })
      .catch((err) => {
        setFacilitiesError(err.message);
        console.error("Facilities fetch failed:", err);
      });
    loadTables(selectedFacilityId);
  }, []);

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!file) {
      setError("Choose an XML file to upload first");
      return;
    }
    setUploading(true);
    setError(null);
    setMessage(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const params = { facility_id: activeFacilityId, xml_type: xmlType };
      if (submissionDate) params.submission_date = submissionDate;

      const { data } = await apiClient.post("/dha-sync/upload", formData, {
        params,
        headers: { "Content-Type": "multipart/form-data" },
      });
      setMessage(`Staged ${data.source_filename} as ${data.xml_type} (status: ${data.parse_status}).`);
      setFile(null);
      await loadTables();
    } catch (err) {
      setError(err.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handleTrigger = async () => {
    setTriggering(true);
    setError(null);
    setMessage(null);
    try {
      const { data } = await apiClient.post("/dha-sync/trigger", null, {
        params: { facility_id: activeFacilityId },
      });
      setMessage(data.message);
      await loadTables();
    } catch (err) {
      setError(err.response?.data?.detail || "DHA sync trigger failed");
    } finally {
      setTriggering(false);
    }
  };

  const handleFetch = async (e) => {
    e.preventDefault();
    if (!dateFrom || !dateTo) {
      setError("Choose a from and to date for the eClaimLink fetch");
      return;
    }
    setFetching(true);
    setError(null);
    setMessage(null);
    try {
      const { data } = await apiClient.post("/dha-sync/fetch", {
        facility_id: activeFacilityId,
        date_from: dateFrom,
        date_to: dateTo,
      });
      setMessage(
        `eClaimLink fetch run #${data.id}: ${data.status} — fetched ${data.records_fetched}, ` +
          `parsed ${data.records_parsed}, failed ${data.records_failed}.`
      );
      await loadTables();
    } catch (err) {
      setError(err.response?.data?.detail || "eClaimLink fetch failed");
    } finally {
      setFetching(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">DHA XML Sync</h1>
        <p className="text-sm text-slate-500">
          Stage ClaimSubmission / RemittanceAdvice XML (DHA Shafafiya / eClaimLink format) and run the sync pipeline.
        </p>
      </div>

      {/* Facility selector */}
      <div className="rounded-xl bg-white p-4 shadow-sm">
        <label className="mb-1 block text-xs font-medium text-slate-600">Facility</label>
        {facilitiesError && (
          <p className="mb-2 text-xs text-red-600">Could not load facilities list: {facilitiesError} — enter facility ID manually below.</p>
        )}
        <div className="flex items-center gap-2">
          {facilities.length > 0 ? (
            <select
              value={selectedFacilityId}
              onChange={(e) => handleFacilityChange(Number(e.target.value))}
              className="w-full max-w-sm rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-ghaf-500 focus:outline-none focus:ring-1 focus:ring-ghaf-500"
            >
              {facilities.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.facility_name} ({f.dhpo_provider_id || "no provider ID"})
                </option>
              ))}
            </select>
          ) : (
            <input
              type="number"
              placeholder="Facility ID (e.g. 13 for Apollo Clinics)"
              value={selectedFacilityId}
              onChange={(e) => handleFacilityChange(Number(e.target.value))}
              className="w-full max-w-sm rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-ghaf-500 focus:outline-none focus:ring-1 focus:ring-ghaf-500"
            />
          )}
          <button
            onClick={() => loadTables(selectedFacilityId)}
            disabled={loadingTables}
            className="rounded-lg bg-ghaf-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-ghaf-700 disabled:opacity-60"
          >
            {loadingTables ? "Loading…" : "Load Data"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl bg-white p-5 shadow-sm">
          <h2 className="mb-3 font-semibold text-slate-900">1. Upload XML</h2>
          <form onSubmit={handleUpload} className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">XML Type</label>
              <select
                value={xmlType}
                onChange={(e) => setXmlType(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-ghaf-500 focus:outline-none focus:ring-1 focus:ring-ghaf-500"
              >
                <option value="ClaimSubmission">ClaimSubmission</option>
                <option value="RemittanceAdvice">RemittanceAdvice</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">Submission Date</label>
              <input
                type="date"
                value={submissionDate}
                onChange={(e) => setSubmissionDate(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-ghaf-500 focus:outline-none focus:ring-1 focus:ring-ghaf-500"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">XML File</label>
              <input
                type="file"
                accept=".xml"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="w-full text-sm"
              />
            </div>
            <button
              type="submit"
              disabled={uploading}
              className="rounded-lg bg-ghaf-600 px-4 py-2 text-sm font-semibold text-white hover:bg-ghaf-700 disabled:opacity-60"
            >
              {uploading ? "Uploading…" : "Upload to Raw XML Store"}
            </button>
          </form>
        </div>

        <div className="rounded-xl bg-white p-5 shadow-sm">
          <h2 className="mb-3 font-semibold text-slate-900">2. Trigger Sync Pipeline</h2>
          <p className="mb-4 text-sm text-slate-500">
            Parses all <span className="font-medium">pending</span> raw XML records into normalized claims and
            remittances, recording a fetch log entry.
          </p>
          <button
            onClick={handleTrigger}
            disabled={triggering}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
          >
            {triggering ? "Running pipeline…" : "Trigger DHA XML Sync"}
          </button>
        </div>

        <div className="rounded-xl bg-white p-5 shadow-sm lg:col-span-2">
          <h2 className="mb-3 font-semibold text-slate-900">3. Live eClaimLink Fetch</h2>
          <p className="mb-4 text-sm text-slate-500">
            Pull ClaimSubmission / RemittanceAdvice transactions directly from eClaimLink (DHPO) for a date range,
            stage them, and run the sync pipeline in one step.
          </p>
          <form onSubmit={handleFetch} className="flex flex-wrap items-end gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">From</label>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-ghaf-500 focus:outline-none focus:ring-1 focus:ring-ghaf-500"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">To</label>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-ghaf-500 focus:outline-none focus:ring-1 focus:ring-ghaf-500"
              />
            </div>
            <button
              type="submit"
              disabled={fetching}
              className="rounded-lg bg-ghaf-600 px-4 py-2 text-sm font-semibold text-white hover:bg-ghaf-700 disabled:opacity-60"
            >
              {fetching ? "Fetching…" : "Fetch from eClaimLink"}
            </button>
          </form>
        </div>
      </div>

      {message && <p className="text-sm text-emerald-700">{message}</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="rounded-xl bg-white p-5 shadow-sm">
        <h2 className="mb-3 font-semibold text-slate-900">Raw XML Store</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left font-semibold text-slate-600">File</th>
                <th className="px-3 py-2 text-left font-semibold text-slate-600">Type</th>
                <th className="px-3 py-2 text-left font-semibold text-slate-600">Submission Date</th>
                <th className="px-3 py-2 text-left font-semibold text-slate-600">Fetched</th>
                <th className="px-3 py-2 text-left font-semibold text-slate-600">Status</th>
                <th className="px-3 py-2 text-left font-semibold text-slate-600">Records Parsed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rawXml.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-4 text-center text-slate-400">No XML files staged yet.</td>
                </tr>
              )}
              {rawXml.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50">
                  <td className="px-3 py-2 text-slate-800">{r.source_filename || "—"}</td>
                  <td className="px-3 py-2 text-slate-600">{r.xml_type}</td>
                  <td className="px-3 py-2 text-slate-600">{r.submission_date || "—"}</td>
                  <td className="px-3 py-2 text-slate-600">{new Date(r.fetched_at).toLocaleString()}</td>
                  <td className="px-3 py-2"><StatusBadge status={r.parse_status} /></td>
                  <td className="px-3 py-2 text-slate-600">{r.records_parsed ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Coverage Summary */}
      {fetchLogs.length > 0 && (
        <div className="rounded-xl bg-white p-5 shadow-sm">
          <h2 className="mb-1 font-semibold text-slate-900">Fetch Coverage</h2>
          <p className="mb-3 text-xs text-slate-500">
            Each row = one fetch run. Green = success, amber = partial, red = failed.
            Use this to verify every requested date window was fully captured.
          </p>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-3 py-2 text-left font-semibold text-slate-600">#</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-600">Date Range Fetched</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-600">Result</th>
                  <th className="px-3 py-2 text-right font-semibold text-slate-600">Files</th>
                  <th className="px-3 py-2 text-right font-semibold text-slate-600">Records</th>
                  <th className="px-3 py-2 text-right font-semibold text-slate-600">Failed</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-600">Completed</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {fetchLogs.map((f) => {
                  const rowBg =
                    f.status === "success" ? "bg-emerald-50" :
                    f.status === "partial" ? "bg-amber-50" :
                    f.status === "failed"  ? "bg-red-50" : "";
                  const icon =
                    f.status === "success" ? "✅" :
                    f.status === "partial" ? "⚠️" :
                    f.status === "failed"  ? "❌" :
                    f.status === "running" ? "⏳" : "—";
                  const duration = f.completed_at
                    ? Math.round((new Date(f.completed_at) - new Date(f.started_at)) / 1000)
                    : null;
                  return (
                    <tr key={f.id} className={`${rowBg} hover:brightness-95`}>
                      <td className="px-3 py-2 text-slate-500 text-xs">#{f.id}</td>
                      <td className="px-3 py-2 font-mono text-slate-800">
                        {f.date_from} → {f.date_to}
                      </td>
                      <td className="px-3 py-2">
                        <span className="flex items-center gap-1">
                          {icon} <StatusBadge status={f.status} />
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right text-slate-700">{f.records_fetched ?? "—"}</td>
                      <td className="px-3 py-2 text-right text-slate-700">{f.records_parsed ?? "—"}</td>
                      <td className="px-3 py-2 text-right text-slate-700">
                        {f.records_failed > 0
                          ? <span className="text-red-600 font-medium">{f.records_failed}</span>
                          : <span className="text-slate-400">0</span>}
                      </td>
                      <td className="px-3 py-2 text-slate-500 text-xs">
                        {f.completed_at
                          ? `${new Date(f.completed_at).toLocaleString()} (${duration}s)`
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Full Sync Run History */}
      <div className="rounded-xl bg-white p-5 shadow-sm">
        <h2 className="mb-3 font-semibold text-slate-900">Sync Run History</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left font-semibold text-slate-600">#</th>
                <th className="px-3 py-2 text-left font-semibold text-slate-600">Date From</th>
                <th className="px-3 py-2 text-left font-semibold text-slate-600">Date To</th>
                <th className="px-3 py-2 text-left font-semibold text-slate-600">Started</th>
                <th className="px-3 py-2 text-left font-semibold text-slate-600">Status</th>
                <th className="px-3 py-2 text-left font-semibold text-slate-600">Files</th>
                <th className="px-3 py-2 text-left font-semibold text-slate-600">Records</th>
                <th className="px-3 py-2 text-left font-semibold text-slate-600">Failed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {fetchLogs.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-4 text-center text-slate-400">No sync runs yet.</td>
                </tr>
              )}
              {fetchLogs.map((f) => (
                <tr key={f.id} className="hover:bg-slate-50">
                  <td className="px-3 py-2 text-slate-400 text-xs">#{f.id}</td>
                  <td className="px-3 py-2 font-mono text-slate-700">{f.date_from}</td>
                  <td className="px-3 py-2 font-mono text-slate-700">{f.date_to}</td>
                  <td className="px-3 py-2 text-slate-600">{new Date(f.started_at).toLocaleString()}</td>
                  <td className="px-3 py-2"><StatusBadge status={f.status} /></td>
                  <td className="px-3 py-2 text-slate-600">{f.records_fetched}</td>
                  <td className="px-3 py-2 text-slate-600">{f.records_parsed}</td>
                  <td className="px-3 py-2 text-slate-600">{f.records_failed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
