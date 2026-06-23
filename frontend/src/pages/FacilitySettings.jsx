import { useEffect, useState } from "react";
import apiClient from "../api/client";

const PLACEHOLDER_PREFIXES = ["user-", "cred-", "LIC-"];
const isPlaceholder = (val) =>
  !val || PLACEHOLDER_PREFIXES.some((p) => val.startsWith(p));

function Badge({ live }) {
  return live ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Live
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
      <span className="h-1.5 w-1.5 rounded-full bg-amber-500" /> Needs setup
    </span>
  );
}

function FacilityRow({ facility, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [form, setForm] = useState({
    facility_name: facility.facility_name,
    license_id: facility.license_id,
    eclaimlink_username: facility.eclaimlink_username,
    credential_key: facility.credential_key,
    dhpo_provider_id: facility.dhpo_provider_id || "",
    is_active: facility.is_active,
  });

  const isLive =
    facility.has_credential &&
    !isPlaceholder(facility.eclaimlink_username) &&
    !isPlaceholder(facility.license_id) &&
    facility.is_active;

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setForm((f) => ({ ...f, [name]: type === "checkbox" ? checked : value }));
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await apiClient.put(`/facilities/${facility.id}`, form);
      onSaved(res.data);
      setEditing(false);
    } catch (err) {
      setError(err.response?.data?.detail || "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="truncate font-semibold text-slate-900">{facility.facility_name}</h3>
            <Badge live={isLive} />
            {!facility.is_active && (
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                Inactive
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-slate-400">Code: {facility.facility_code}</p>
        </div>
        <button
          onClick={() => setEditing((e) => !e)}
          className="shrink-0 rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50"
        >
          {editing ? "Cancel" : "Edit"}
        </button>
      </div>

      {!editing && (
        <div className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
          <Field label="License ID" value={facility.license_id} placeholder={isPlaceholder(facility.license_id)} />
          <Field label="eClaimLink Username" value={facility.eclaimlink_username} placeholder={isPlaceholder(facility.eclaimlink_username)} />
          <Field label="Credential Key" value={facility.credential_key} secret placeholder={isPlaceholder(facility.credential_key)} />
          <Field label="DHPO Provider ID" value={facility.dhpo_provider_id || "—"} />
        </div>
      )}

      {editing && (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Input label="Facility Name" name="facility_name" value={form.facility_name} onChange={handleChange} />
            <Input label="License ID" name="license_id" value={form.license_id} onChange={handleChange} />
            <Input label="eClaimLink Username" name="eclaimlink_username" value={form.eclaimlink_username} onChange={handleChange} />
            <Input label="Credential Key" name="credential_key" value={form.credential_key} onChange={handleChange} type="password" showToggle />
            <Input label="DHPO Provider ID (optional)" name="dhpo_provider_id" value={form.dhpo_provider_id} onChange={handleChange} />
            <label className="flex items-center gap-2 text-sm text-slate-700 self-end pb-1">
              <input
                type="checkbox"
                name="is_active"
                checked={form.is_active}
                onChange={handleChange}
                className="h-4 w-4 rounded border-slate-300 text-emerald-600"
              />
              Active facility
            </label>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setEditing(false)}
              className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, value, placeholder, secret }) {
  const display = secret && !placeholder ? "••••••••••••" : value;
  return (
    <div>
      <span className="text-xs font-medium text-slate-400">{label}</span>
      <p className={`mt-0.5 truncate text-sm ${placeholder ? "italic text-amber-600" : "text-slate-800"}`}>
        {display}
      </p>
    </div>
  );
}

function Input({ label, name, value, onChange, type = "text", showToggle }) {
  const [show, setShow] = useState(false);
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-slate-500">{label}</label>
      <div className="relative">
        <input
          type={showToggle && !show ? "password" : "text"}
          name={name}
          value={value}
          onChange={onChange}
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-emerald-400 focus:outline-none focus:ring-1 focus:ring-emerald-400"
        />
        {showToggle && (
          <button
            type="button"
            onClick={() => setShow((s) => !s)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-slate-600"
          >
            {show ? "Hide" : "Show"}
          </button>
        )}
      </div>
    </div>
  );
}

export default function FacilitySettings() {
  const [facilities, setFacilities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    apiClient
      .get("/facilities")
      .then((res) => setFacilities(res.data))
      .catch((err) => setError(err.response?.data?.detail || "Failed to load facilities."))
      .finally(() => setLoading(false));
  }, []);

  const handleSaved = (updated) =>
    setFacilities((prev) => prev.map((f) => (f.id === updated.id ? updated : f)));

  const liveCount = facilities.filter(
    (f) =>
      f.has_credential &&
      !isPlaceholder(f.eclaimlink_username) &&
      !isPlaceholder(f.license_id) &&
      f.is_active
  ).length;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Facility Settings</h1>
          <p className="text-sm text-slate-500">
            Manage eClaimLink credentials for live data sync. Fields shown in amber need real values.
          </p>
        </div>
        {!loading && (
          <div className="rounded-xl bg-white px-4 py-3 shadow-sm border border-slate-200 text-center">
            <p className="text-2xl font-bold text-slate-900">{liveCount}/{facilities.length}</p>
            <p className="text-xs text-slate-500">Facilities live</p>
          </div>
        )}
      </div>

      {loading && <p className="text-sm text-slate-500">Loading facilities…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="space-y-4">
        {facilities.map((f) => (
          <FacilityRow key={f.id} facility={f} onSaved={handleSaved} />
        ))}
      </div>
    </div>
  );
}
