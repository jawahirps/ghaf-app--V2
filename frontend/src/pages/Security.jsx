import { useCallback, useEffect, useState } from "react";
import { browserSupportsWebAuthn, startRegistration } from "@simplewebauthn/browser";
import apiClient from "../api/client";

function formatDate(value) {
  return value ? new Date(value).toLocaleString() : "Never";
}

function defaultPasskeyName() {
  const ua = navigator.userAgent;
  if (/iPhone|iPad/.test(ua)) return "iPhone / iPad";
  if (/Android/.test(ua)) return "Android device";
  if (/Mac/.test(ua)) return "Mac";
  if (/Windows/.test(ua)) return "Windows PC";
  return "Passkey";
}

export default function Security() {
  const supported = browserSupportsWebAuthn();
  const [passkeys, setPasskeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState(defaultPasskeyName());
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    apiClient
      .get("/auth/passkeys")
      .then((res) => setPasskeys(res.data))
      .catch((err) => setError(err.response?.data?.detail || "Failed to load passkeys"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const addPasskey = async () => {
    setError(null);
    setNotice(null);
    setAdding(true);
    try {
      const { data: opts } = await apiClient.post("/auth/passkeys/register/options");
      const credential = await startRegistration({ optionsJSON: JSON.parse(opts.options) });
      await apiClient.post("/auth/passkeys/register/verify", {
        challenge_id: opts.challenge_id,
        credential,
        name,
      });
      setNotice("Passkey added. You can now sign in without a password on this device.");
      load();
    } catch (err) {
      if (err?.name === "InvalidStateError") {
        setError("This device already has a passkey for your account.");
      } else if (err?.name === "NotAllowedError" || err?.name === "AbortError") {
        setError("Passkey setup was cancelled.");
      } else {
        setError(err.response?.data?.detail || err.message || "Could not add passkey.");
      }
    } finally {
      setAdding(false);
    }
  };

  const renamePasskey = async (pk) => {
    const next = window.prompt("Rename passkey", pk.name);
    if (!next || next.trim() === pk.name) return;
    try {
      await apiClient.patch(`/auth/passkeys/${pk.id}`, { name: next.trim() });
      load();
    } catch (err) {
      setError(err.response?.data?.detail || "Could not rename passkey.");
    }
  };

  const removePasskey = async (pk) => {
    if (!window.confirm(`Remove passkey "${pk.name}"? You won't be able to sign in with it any more.`)) return;
    try {
      await apiClient.delete(`/auth/passkeys/${pk.id}`);
      setNotice(`Removed "${pk.name}".`);
      load();
    } catch (err) {
      setError(err.response?.data?.detail || "Could not remove passkey.");
    }
  };

  return (
    <div className="max-w-3xl space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Security</h1>
        <p className="text-sm text-slate-500">Manage how you sign in to Ghaf App.</p>
      </div>

      <section className="space-y-4 rounded-xl bg-white p-6 shadow-sm">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Passkeys</h2>
          <p className="text-sm text-slate-500">
            Sign in with Touch ID, Face ID, Windows Hello or your phone instead of a password. Passkeys can't be
            phished or reused on other sites.
          </p>
        </div>

        {!supported && (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
            This browser doesn't support passkeys. Try a recent version of Chrome, Safari, Edge or Firefox.
          </p>
        )}

        {supported && (
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={100}
              placeholder="Passkey name (e.g. Work laptop)"
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-ghaf-500 focus:outline-none focus:ring-1 focus:ring-ghaf-500"
            />
            <button
              onClick={addPasskey}
              disabled={adding}
              className="rounded-lg bg-ghaf-600 px-4 py-2 text-sm font-semibold text-white hover:bg-ghaf-700 disabled:opacity-60"
            >
              {adding ? "Waiting for device…" : "Add a passkey"}
            </button>
          </div>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}
        {notice && <p className="text-sm text-emerald-700">{notice}</p>}

        <div className="overflow-hidden rounded-lg border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-2 text-left font-semibold text-slate-600">Name</th>
                <th className="px-4 py-2 text-left font-semibold text-slate-600">Added</th>
                <th className="px-4 py-2 text-left font-semibold text-slate-600">Last used</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading && (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-slate-400">Loading…</td>
                </tr>
              )}
              {!loading && passkeys.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-slate-400">No passkeys yet.</td>
                </tr>
              )}
              {passkeys.map((pk) => (
                <tr key={pk.id} className="hover:bg-slate-50">
                  <td className="px-4 py-2 text-slate-800">
                    {pk.name}
                    {pk.backed_up && (
                      <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">synced</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-slate-600">{formatDate(pk.created_at)}</td>
                  <td className="px-4 py-2 text-slate-600">{formatDate(pk.last_used_at)}</td>
                  <td className="space-x-3 px-4 py-2 text-right">
                    <button onClick={() => renamePasskey(pk)} className="text-sm text-slate-600 hover:text-slate-900">
                      Rename
                    </button>
                    <button onClick={() => removePasskey(pk)} className="text-sm text-red-600 hover:text-red-700">
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
