import { useEffect, useState } from "react";
import apiClient from "../api/client";

export default function useAnalyticsReport(endpoint, filters) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiClient
      .get(`/analytics/${endpoint}`, { params: filters })
      .then((res) => {
        if (!cancelled) {
          setData(res.data);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err.response?.data?.detail || "Failed to load report");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint, JSON.stringify(filters)]);

  return { data, error, loading };
}

export const CHART_COLORS = ["#0ea5a4", "#6366f1", "#f59e0b", "#ef4444", "#10b981", "#3b82f6", "#a855f7", "#ec4899", "#84cc16"];
