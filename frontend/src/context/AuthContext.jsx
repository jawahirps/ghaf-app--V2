import { createContext, useContext, useState, useCallback } from "react";
import { startAuthentication } from "@simplewebauthn/browser";
import apiClient from "../api/client";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const raw = localStorage.getItem("ghaf_user");
    return raw ? JSON.parse(raw) : null;
  });
  const [token, setToken] = useState(() => localStorage.getItem("ghaf_token"));

  const storeSession = useCallback((data) => {
    localStorage.setItem("ghaf_token", data.access_token);
    localStorage.setItem("ghaf_user", JSON.stringify(data.user));
    setToken(data.access_token);
    setUser(data.user);
    return data.user;
  }, []);

  const login = useCallback(async (email, password) => {
    const form = new URLSearchParams();
    form.append("username", email);
    form.append("password", password);

    const { data } = await apiClient.post("/auth/login", form, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    return storeSession(data);
  }, [storeSession]);

  const loginWithPasskey = useCallback(async () => {
    const { data: opts } = await apiClient.post("/auth/passkeys/login/options");
    const credential = await startAuthentication({ optionsJSON: JSON.parse(opts.options) });
    const { data } = await apiClient.post("/auth/passkeys/login/verify", {
      challenge_id: opts.challenge_id,
      credential,
    });
    return storeSession(data);
  }, [storeSession]);

  const logout = useCallback(() => {
    localStorage.removeItem("ghaf_token");
    localStorage.removeItem("ghaf_user");
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, login, loginWithPasskey, logout, isAuthenticated: !!token }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
