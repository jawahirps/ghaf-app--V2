import { useEffect, useRef, useState } from "react";
import apiClient from "../api/client";

/**
 * Renders a Metabase static-embed dashboard inside an <iframe>.
 *
 * Fetches a freshly signed embed URL from
 * GET /api/analytics/embed/{dashboardKey} and refreshes it shortly before
 * the signed token expires.
 */
export default function MetabaseEmbed({ dashboardKey, title, description, height = 520 }) {
  const [iframeUrl, setIframeUrl] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const refreshTimer = useRef(null);

  const fetchEmbed = async () => {
    try {
      const { data } = await apiClient.get(`/analytics/embed/${dashboardKey}`);
      setIframeUrl(data.iframe_url);
      setError(null);

      if (refreshTimer.current) clearTimeout(refreshTimer.current);
      const refreshInMs = Math.max((data.expires_in - 30) * 1000, 5000);
      refreshTimer.current = setTimeout(fetchEmbed, refreshInMs);
    } catch (err) {
      setError(
        err.response?.data?.detail ||
          "Unable to load this dashboard. Confirm Metabase embedding is configured."
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEmbed();
    return () => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardKey]);

  return (
    <div className="rounded-xl bg-white p-4 shadow-sm">
      <div className="mb-3">
        <h3 className="font-semibold text-slate-900">{title}</h3>
        {description && <p className="text-sm text-slate-500">{description}</p>}
      </div>

      {loading && <div className="flex h-40 items-center justify-center text-sm text-slate-400">Loading dashboard…</div>}

      {!loading && error && (
        <div className="flex h-40 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-slate-300 bg-slate-50 text-center text-sm text-slate-500">
          <p>{error}</p>
          <p className="text-xs text-slate-400">dashboard key: {dashboardKey}</p>
        </div>
      )}

      {!loading && !error && iframeUrl && (
        <iframe
          title={title}
          src={iframeUrl}
          width="100%"
          height={height}
          className="rounded-lg border border-slate-200"
          allowTransparency="true"
        />
      )}
    </div>
  );
}
