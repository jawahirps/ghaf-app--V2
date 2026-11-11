import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { browserSupportsWebAuthn } from "@simplewebauthn/browser";
import { useAuth } from "../context/AuthContext";

export default function Login() {
  const { login, loginWithPasskey } = useAuth();
  const passkeysSupported = browserSupportsWebAuthn();
  const [passkeyLoading, setPasskeyLoading] = useState(false);

  const handlePasskey = async () => {
    setError(null);
    setPasskeyLoading(true);
    try {
      await loginWithPasskey();
      navigate("/", { replace: true });
    } catch (err) {
      // User closed the browser prompt — not an error worth shouting about.
      if (err?.name === "NotAllowedError" || err?.name === "AbortError") {
        setError("Passkey sign-in was cancelled.");
      } else {
        setError(err.response?.data?.detail || "Passkey sign-in failed.");
      }
    } finally {
      setPasskeyLoading(false);
    }
  };
  const navigate = useNavigate();

  const [email, setEmail] = useState("admin@ghafapp.local");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err.response?.data?.detail || "Login failed. Check your credentials.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-slate-900">
      <div className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-xl">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-bold text-slate-900">Ghaf App</h1>
          <p className="mt-1 text-sm text-slate-500">RCM &amp; Clinical Platform</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-ghaf-500 focus:outline-none focus:ring-1 focus:ring-ghaf-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">Password</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-ghaf-500 focus:outline-none focus:ring-1 focus:ring-ghaf-500"
            />
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-ghaf-600 px-4 py-2 text-sm font-semibold text-white hover:bg-ghaf-700 disabled:opacity-60"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>

        {passkeysSupported && (
          <>
            <div className="my-4 flex items-center gap-3 text-xs text-slate-400">
              <div className="h-px flex-1 bg-slate-200" />
              or
              <div className="h-px flex-1 bg-slate-200" />
            </div>
            <button
              type="button"
              onClick={handlePasskey}
              disabled={passkeyLoading || loading}
              className="w-full rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            >
              {passkeyLoading ? "Waiting for passkey…" : "Sign in with a passkey"}
            </button>
          </>
        )}

        <p className="mt-6 text-center text-xs text-slate-400">
          Default seeded admin: admin@ghafapp.local / ChangeMe123!
        </p>
      </div>
    </div>
  );
}
