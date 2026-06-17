import { useState, useEffect, useCallback } from "react";
import FilterBar from "../components/FilterBar";
import Submissions from "./analytics/Submissions";
import Resubmissions from "./analytics/Resubmissions";
import Remittance from "./analytics/Remittance";
import Denials from "./analytics/Denials";
import Clinicians from "./analytics/Clinicians";
import Operations from "./analytics/Operations";
import Insurance from "./analytics/Insurance";
import Department from "./analytics/Department";
import apiClient from "../api/client";

const TABS = [
  { key: "submissions",   label: "Submissions",   component: Submissions },
  { key: "resubmissions", label: "Resubmissions", component: Resubmissions },
  { key: "remittance",    label: "Remittance",    component: Remittance },
  { key: "denials",       label: "Denials",       component: Denials },
  { key: "clinicians",    label: "Clinicians",    component: Clinicians },
  { key: "operations",    label: "Operations",    component: Operations },
  { key: "insurance",     label: "Insurance",     component: Insurance },
  { key: "department",    label: "Department",    component: Department },
];

const REPORTS = [
  {
    key: "claim-summary",
    label: "Claim Summary",
    description: "One row per claim with financials & RA",
    icon: "📋",
  },
  {
    key: "claim-activity",
    label: "Claim Activity",
    description: "Service-line (CPT) detail per claim",
    icon: "🔬",
  },
  {
    key: "denial-analysis",
    label: "Denial Analysis",
    description: "Denial breakdown by payer & code",
    icon: "🚫",
  },
  {
    key: "resubmission-aging",
    label: "Resubmission & Aging",
    description: "AR aging with bucket classification",
    icon: "📆",
  },
  {
    key: "remittance-activity",
    label: "Remittance Activity",
    description: "Activity-level remittance detail",
    icon: "💳",
  },
  {
    key: "denial-query",
    label: "Denial Query",
    description: "Denied claims with CPT code and RA info",
    icon: "🔍",
  },
];

function buildQueryString(filters, extra = {}) {
  const params = new URLSearchParams();
  const all = { ...filters, ...extra };
  Object.entries(all).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") params.append(k, v);
  });
  return params.toString();
}

function fmtDatetime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-GB", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function fmtFilterSummary(filters = {}) {
  const parts = [];
  if (filters.date_from || filters.date_to) {
    const from = filters.date_from || "—";
    const to   = filters.date_to   || "—";
    const field = filters.date_field === "remittance_date" ? "RA Date" : "Treatment";
    parts.push(`${field}: ${from} → ${to}`);
  }
  return parts.join(" | ") || "No date filter";
}

// ---------------------------------------------------------------------------
// Report Queue Row
// ---------------------------------------------------------------------------
function JobRow({ job, onDownload }) {
  const statusColor =
    job.status === "completed" ? "text-green-700 bg-green-50"
    : job.status === "error"    ? "text-red-700 bg-red-50"
    :                             "text-slate-600 bg-slate-100";

  return (
    <tr className="border-t border-slate-100 hover:bg-slate-50">
      <td className="px-3 py-2.5 text-xs text-slate-500 font-mono">
        {String(job.id).padStart(4, "0")}
      </td>
      <td className="px-3 py-2.5">
        <span className="text-sm font-medium text-slate-800">{job.report_label}</span>
      </td>
      <td className="px-3 py-2.5 text-xs text-slate-500">
        {fmtFilterSummary(job.filters)}
      </td>
      <td className="px-3 py-2.5 text-xs text-slate-500 text-right tabular-nums">
        {job.row_count != null ? job.row_count.toLocaleString() : "—"}
      </td>
      <td className="px-3 py-2.5">
        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize ${statusColor}`}>
          {job.status}
        </span>
      </td>
      <td className="px-3 py-2.5 text-xs text-slate-500 whitespace-nowrap">
        {fmtDatetime(job.created_at)}
      </td>
      <td className="px-3 py-2.5 text-xs text-slate-500 whitespace-nowrap">
        {fmtDatetime(job.completed_at)}
      </td>
      <td className="px-3 py-2.5 text-right">
        {job.has_file ? (
          <button
            onClick={() => onDownload(job)}
            title={`Download ${job.filename}`}
            className="inline-flex items-center gap-1 rounded-lg bg-ghaf-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-ghaf-700 transition"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
            Download
          </button>
        ) : (
          <span className="text-xs text-slate-400 italic">
            {job.error ? "Error" : "No file"}
          </span>
        )}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main Analytics page
// ---------------------------------------------------------------------------
export default function Analytics() {
  const [activeTab, setActiveTab]     = useState("submissions");
  const [filters, setFilters]         = useState({});
  const [showReports, setShowReports] = useState(false);
  const [generating, setGenerating]   = useState(null);
  const [reportJobs, setReportJobs]   = useState([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [showQueue, setShowQueue]     = useState(true);   // always visible
  const [queueError, setQueueError]   = useState(null);

  const ActiveComponent = TABS.find((t) => t.key === activeTab)?.component || Submissions;

  // Load report job queue — returns a Promise so callers can await it
  const loadJobs = useCallback(() => {
    setJobsLoading(true);
    setQueueError(null);
    return apiClient
      .get("/reports/jobs")
      .then((res) => {
        setReportJobs(res.data);
      })
      .catch((err) => {
        const detail = err.response?.data?.detail || err.message || "Unknown error";
        setQueueError(
          detail.includes("report_jobs")
            ? "The report_jobs table does not exist yet. Please run the migration SQL in your psql terminal."
            : `Could not load report queue: ${detail}`
        );
      })
      .finally(() => setJobsLoading(false));
  }, []);

  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  // Generate a report — POSTs to /generate/{type}, saves to queue
  const generateReport = async (reportKey) => {
    setGenerating(reportKey);
    setShowReports(false);
    try {
      const qs = buildQueryString(filters);
      await apiClient.post(`/reports/generate/${reportKey}${qs ? "?" + qs : ""}`);
      // Refresh job list after successful generation
      await loadJobs();
    } catch (err) {
      const detail = err.response?.data?.detail || err.message;
      // Only show the first line of a traceback to keep the alert readable
      const firstLine = detail?.split("\n").find((l) => l.trim()) || detail;
      alert(`Report generation failed:\n${firstLine}`);
    } finally {
      setGenerating(null);
    }
  };

  // Download a completed job
  const downloadJob = async (job) => {
    try {
      const token = localStorage.getItem("ghaf_token");
      const res = await fetch(`/api/reports/jobs/${job.id}/download`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const href = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = href;
      a.download = job.filename || "report.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(href);
    } catch (err) {
      alert(`Download failed: ${err.message}`);
    }
  };

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Analytics &amp; Financial Insights</h1>
          <p className="text-sm text-slate-500">
            Submission, resubmission, remittance, and denial performance — filterable by facility,
            receiver, payer, encounter type, and department.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Report Queue button */}
          <button
            onClick={loadJobs}
            disabled={jobsLoading}
            className="flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 transition disabled:opacity-50"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
              <path d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" />
            </svg>
            {jobsLoading ? "Loading…" : `Report Queue${reportJobs.length ? ` (${reportJobs.length})` : ""}`}
          </button>

          {/* Generate Reports dropdown */}
          <div className="relative">
            <button
              onClick={() => setShowReports((v) => !v)}
              disabled={generating !== null}
              className="flex items-center gap-2 rounded-lg bg-ghaf-600 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-ghaf-700 transition disabled:opacity-60"
            >
              {generating ? (
                <>
                  <svg className="h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                  </svg>
                  Generating…
                </>
              ) : (
                <>
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                  Generate Report
                </>
              )}
            </button>

            {showReports && (
              <div className="absolute right-0 z-20 mt-2 w-72 rounded-xl border border-slate-200 bg-white shadow-xl">
                <div className="px-4 py-3 border-b border-slate-100">
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
                    Advanced Excel Reports
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">
                    Generates with current filters — saved to Report Queue
                  </p>
                </div>
                <ul className="py-2">
                  {REPORTS.map((r) => (
                    <li key={r.key}>
                      <button
                        onClick={() => generateReport(r.key)}
                        className="w-full flex items-start gap-3 px-4 py-3 hover:bg-slate-50 text-left transition"
                      >
                        <span className="text-xl leading-none mt-0.5">{r.icon}</span>
                        <span className="flex-1 min-w-0">
                          <span className="block text-sm font-medium text-slate-800">{r.label}</span>
                          <span className="block text-xs text-slate-400 truncate">{r.description}</span>
                        </span>
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-slate-400 mt-1 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
                          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-8.707l-3-3a1 1 0 00-1.414 1.414L10.586 9H7a1 1 0 100 2h3.586l-1.293 1.293a1 1 0 101.414 1.414l3-3a1 1 0 000-1.414z" clipRule="evenodd" />
                        </svg>
                      </button>
                    </li>
                  ))}
                </ul>
                <div className="px-4 py-2 border-t border-slate-100">
                  <button
                    onClick={() => setShowReports(false)}
                    className="text-xs text-slate-400 hover:text-slate-600"
                  >
                    Close
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <FilterBar filters={filters} onChange={setFilters} />

      {/* Report Job Queue */}
      {showQueue && (
        <div className="rounded-xl bg-white shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3 border-b border-slate-100">
            <div className="flex items-center gap-2">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-ghaf-600" viewBox="0 0 20 20" fill="currentColor">
                <path d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" />
              </svg>
              <h2 className="text-sm font-semibold text-slate-800">Report Queue</h2>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                {reportJobs.length} report{reportJobs.length !== 1 ? "s" : ""}
              </span>
            </div>
            <button
              onClick={() => setShowQueue(false)}
              className="text-xs text-slate-400 hover:text-slate-600"
            >
              Hide
            </button>
          </div>

          {queueError ? (
            <div className="px-5 py-6 text-center">
              <p className="text-sm text-red-600 font-medium">⚠️ {queueError}</p>
              <button
                onClick={loadJobs}
                className="mt-3 text-xs text-ghaf-600 hover:underline"
              >
                Retry
              </button>
            </div>
          ) : reportJobs.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-slate-400">
              No reports generated yet. Use &ldquo;Generate Report&rdquo; above to create one.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[700px] text-sm">
                <thead>
                  <tr className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2 text-left w-16">ID</th>
                    <th className="px-3 py-2 text-left">Report</th>
                    <th className="px-3 py-2 text-left">Date Filter</th>
                    <th className="px-3 py-2 text-right w-24">Rows</th>
                    <th className="px-3 py-2 text-left w-24">Status</th>
                    <th className="px-3 py-2 text-left w-40">Requested</th>
                    <th className="px-3 py-2 text-left w-40">Generated On</th>
                    <th className="px-3 py-2 text-right w-28">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {reportJobs.map((job) => (
                    <JobRow key={job.id} job={job} onDownload={downloadJob} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-slate-200">
        <nav className="-mb-px flex flex-wrap gap-x-6 gap-y-2">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`whitespace-nowrap border-b-2 px-1 py-3 text-sm font-medium transition ${
                activeTab === tab.key
                  ? "border-ghaf-500 text-ghaf-600"
                  : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      <ActiveComponent filters={filters} />
    </div>
  );
}
