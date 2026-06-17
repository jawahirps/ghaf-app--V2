import { useEffect, useState } from "react";
import apiClient from "../api/client";
import { useAuth } from "../context/AuthContext";

const emptyForm = {
  member_id: "",
  emirates_id: "",
  full_name: "",
  date_of_birth: "",
  gender: "",
  nationality: "",
  payer_id: "",
  policy_number: "",
  plan_type: "",
  primary_clinician_id: "",
  blood_type: "",
  allergies: "",
  chronic_conditions: "",
  current_medications: "",
  notes: "",
  is_active: true,
};

function ProfileForm({ initial, onCancel, onSaved, facilityId }) {
  const [form, setForm] = useState(initial || emptyForm);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const isEdit = Boolean(initial?.id);

  const update = (field) => (e) => {
    const value = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [field]: value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = { ...form };
      // Drop empty strings for optional fields so backend coercion is clean
      Object.keys(payload).forEach((k) => {
        if (payload[k] === "") payload[k] = null;
      });

      if (isEdit) {
        const { data } = await apiClient.put(`/clinical-profiles/${initial.id}`, payload);
        onSaved(data);
      } else {
        const { data } = await apiClient.post("/clinical-profiles", { ...payload, facility_id: facilityId });
        onSaved(data);
      }
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to save clinical profile");
    } finally {
      setSaving(false);
    }
  };

  const field = (label, name, type = "text", extra = {}) => (
    <div>
      <label className="mb-1 block text-xs font-medium text-slate-600">{label}</label>
      <input
        type={type}
        value={form[name] ?? ""}
        onChange={update(name)}
        className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-ghaf-500 focus:outline-none focus:ring-1 focus:ring-ghaf-500"
        {...extra}
      />
    </div>
  );

  const textarea = (label, name) => (
    <div>
      <label className="mb-1 block text-xs font-medium text-slate-600">{label}</label>
      <textarea
        rows={2}
        value={form[name] ?? ""}
        onChange={update(name)}
        className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-ghaf-500 focus:outline-none focus:ring-1 focus:ring-ghaf-500"
      />
    </div>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-lg font-bold text-slate-900">
          {isEdit ? "Edit Clinical Profile" : "New Clinical Profile"}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {field("Full Name *", "full_name", "text", { required: true })}
            {field("Member ID *", "member_id", "text", { required: true, disabled: isEdit })}
            {field("Emirates ID", "emirates_id")}
            {field("Date of Birth", "date_of_birth", "date")}
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">Gender</label>
              <select
                value={form.gender ?? ""}
                onChange={update("gender")}
                className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-ghaf-500 focus:outline-none focus:ring-1 focus:ring-ghaf-500"
              >
                <option value="">—</option>
                <option value="Male">Male</option>
                <option value="Female">Female</option>
                <option value="Other">Other</option>
              </select>
            </div>
            {field("Nationality", "nationality")}
            {field("Payer ID", "payer_id")}
            {field("Policy Number", "policy_number")}
            {field("Plan Type", "plan_type")}
            {field("Primary Clinician ID", "primary_clinician_id")}
            {field("Blood Type", "blood_type")}
            {field("Height (cm)", "height_cm", "number", { step: "0.1" })}
            {field("Weight (kg)", "weight_kg", "number", { step: "0.1" })}
          </div>
          {textarea("Allergies", "allergies")}
          {textarea("Chronic Conditions", "chronic_conditions")}
          {textarea("Current Medications", "current_medications")}
          {textarea("Notes", "notes")}

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={!!form.is_active} onChange={update("is_active")} />
            Active
          </label>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onCancel}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-ghaf-600 px-4 py-2 text-sm font-semibold text-white hover:bg-ghaf-700 disabled:opacity-60"
            >
              {saving ? "Saving…" : "Save Profile"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function ClinicalProfiles() {
  const { user } = useAuth();
  const [profiles, setProfiles] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);
  const [showForm, setShowForm] = useState(false);

  const load = async (q = "") => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/clinical-profiles", { params: q ? { search: q } : {} });
      setProfiles(data);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to load clinical profiles");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleSearch = (e) => {
    e.preventDefault();
    load(search);
  };

  const handleSaved = () => {
    setShowForm(false);
    setEditing(null);
    load(search);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this clinical profile?")) return;
    await apiClient.delete(`/clinical-profiles/${id}`);
    load(search);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Clinical Profiles</h1>
          <p className="text-sm text-slate-500">Patient demographic, payer, and clinical setup.</p>
        </div>
        <button
          onClick={() => {
            setEditing(null);
            setShowForm(true);
          }}
          className="rounded-lg bg-ghaf-600 px-4 py-2 text-sm font-semibold text-white hover:bg-ghaf-700"
        >
          + New Profile
        </button>
      </div>

      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name, member ID, or Emirates ID"
          className="w-full max-w-sm rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-ghaf-500 focus:outline-none focus:ring-1 focus:ring-ghaf-500"
        />
        <button type="submit" className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50">
          Search
        </button>
      </form>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="overflow-hidden rounded-xl bg-white shadow-sm">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-2 text-left font-semibold text-slate-600">Name</th>
              <th className="px-4 py-2 text-left font-semibold text-slate-600">Member ID</th>
              <th className="px-4 py-2 text-left font-semibold text-slate-600">Emirates ID</th>
              <th className="px-4 py-2 text-left font-semibold text-slate-600">Payer</th>
              <th className="px-4 py-2 text-left font-semibold text-slate-600">Clinician</th>
              <th className="px-4 py-2 text-left font-semibold text-slate-600">Status</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-slate-400">Loading…</td>
              </tr>
            )}
            {!loading && profiles.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-slate-400">No clinical profiles found.</td>
              </tr>
            )}
            {profiles.map((p) => (
              <tr key={p.id} className="hover:bg-slate-50">
                <td className="px-4 py-2 font-medium text-slate-800">{p.full_name}</td>
                <td className="px-4 py-2 text-slate-600">{p.member_id}</td>
                <td className="px-4 py-2 text-slate-600">{p.emirates_id || "—"}</td>
                <td className="px-4 py-2 text-slate-600">{p.payer_id || "—"}</td>
                <td className="px-4 py-2 text-slate-600">{p.primary_clinician_id || "—"}</td>
                <td className="px-4 py-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      p.is_active ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-600"
                    }`}
                  >
                    {p.is_active ? "Active" : "Inactive"}
                  </span>
                </td>
                <td className="px-4 py-2 text-right">
                  <button
                    onClick={() => {
                      setEditing(p);
                      setShowForm(true);
                    }}
                    className="mr-3 text-sm font-medium text-ghaf-600 hover:underline"
                  >
                    Edit
                  </button>
                  <button onClick={() => handleDelete(p.id)} className="text-sm font-medium text-red-600 hover:underline">
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showForm && (
        <ProfileForm
          initial={editing}
          facilityId={user?.facility_id}
          onCancel={() => {
            setShowForm(false);
            setEditing(null);
          }}
          onSaved={handleSaved}
        />
      )}
    </div>
  );
}
