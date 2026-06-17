import { useEffect, useState } from "react";
import apiClient from "../api/client";

const selectClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm focus:border-ghaf-400 focus:outline-none focus:ring-1 focus:ring-ghaf-400";

const labelClass = "mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500";

export default function FilterBar({ filters, onChange }) {
  const [options, setOptions] = useState({
    facilities: [],
    receivers: [],
    payers: [],
    encounter_types: [],
    departments: [],
  });

  useEffect(() => {
    apiClient
      .get("/analytics/filters")
      .then((res) => setOptions(res.data))
      .catch(() => {});
  }, []);

  const update = (key, value) => {
    onChange({ ...filters, [key]: value || undefined });
  };

  const reset = () => {
    onChange({});
  };

  return (
    <div className="rounded-xl bg-white p-4 shadow-sm">
      {/* Row 1: Entity filters */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
        <div>
          <label className={labelClass}>Facility</label>
          <select
            className={selectClass}
            value={filters.facility_id || ""}
            onChange={(e) => update("facility_id", e.target.value)}
          >
            <option value="">All Facilities</option>
            {options.facilities.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={labelClass}>Receiver</label>
          <select
            className={selectClass}
            value={filters.receiver_id || ""}
            onChange={(e) => update("receiver_id", e.target.value)}
          >
            <option value="">All Receivers</option>
            {options.receivers.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={labelClass}>Payer</label>
          <select
            className={selectClass}
            value={filters.payer_id || ""}
            onChange={(e) => update("payer_id", e.target.value)}
          >
            <option value="">All Payers</option>
            {options.payers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={labelClass}>Encounter Type</label>
          <select
            className={selectClass}
            value={filters.encounter_type || ""}
            onChange={(e) => update("encounter_type", e.target.value)}
          >
            <option value="">All Encounter Types</option>
            {options.encounter_types.map((et) => (
              <option key={et} value={et}>
                {et}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={labelClass}>Department</label>
          <select
            className={selectClass}
            value={filters.department || ""}
            onChange={(e) => update("department", e.target.value)}
          >
            <option value="">All Departments</option>
            {options.departments.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Row 2: Date filters */}
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        {/* Date search criteria */}
        <div>
          <label className={labelClass}>Search Criteria</label>
          <select
            className={selectClass}
            value={filters.date_field || "treatment_date"}
            onChange={(e) => update("date_field", e.target.value)}
          >
            <option value="treatment_date">Treatment Date</option>
            <option value="remittance_date">Remittance Transaction Date</option>
          </select>
        </div>

        <div>
          <label className={labelClass}>
            {filters.date_field === "remittance_date"
              ? "Remittance Date From"
              : "Treatment Date From"}
          </label>
          <input
            type="date"
            className={selectClass}
            value={filters.date_from || ""}
            onChange={(e) => update("date_from", e.target.value)}
          />
        </div>

        <div>
          <label className={labelClass}>
            {filters.date_field === "remittance_date"
              ? "Remittance Date To"
              : "Treatment Date To"}
          </label>
          <input
            type="date"
            className={selectClass}
            value={filters.date_to || ""}
            onChange={(e) => update("date_to", e.target.value)}
          />
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between">
        {/* Active filter summary */}
        <p className="text-xs text-slate-400">
          {filters.date_field === "remittance_date"
            ? "📅 Filtering by Remittance Transaction Date"
            : "📅 Filtering by Treatment Date"}
        </p>
        <button
          type="button"
          onClick={reset}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
        >
          Clear filters
        </button>
      </div>
    </div>
  );
}
