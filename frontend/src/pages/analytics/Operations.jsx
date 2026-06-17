import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import useAnalyticsReport, { CHART_COLORS } from "../../hooks/useAnalyticsReport";
import KpiCard from "../../components/KpiCard";
import ChartCard from "../../components/ChartCard";
import { currency, number } from "../../utils/format";

export default function Operations({ filters }) {
  const { data, error, loading } = useAnalyticsReport("operations", filters);

  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return null;

  const { kpis, by_encounter_type, by_status, monthly_trend } = data;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <KpiCard label="Total Claims" value={number(kpis.total_claims)} />
        <KpiCard label="Avg. Turnaround (days)" value={kpis.avg_turnaround_days} />
      </div>

      <ChartCard title="Submission Volume Trend" description="Claim count by month.">
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={monthly_trend}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="month" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Line type="monotone" dataKey="claim_count" name="Claims" stroke="#0ea5a4" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <ChartCard title="By Encounter Type">
          {by_encounter_type && by_encounter_type.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie data={by_encounter_type} dataKey="claim_count" nameKey="encounter_type" outerRadius={100} label={(d) => d.encounter_type}>
                  {by_encounter_type.map((_, idx) => (
                    <Cell key={idx} fill={CHART_COLORS[idx % CHART_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v, n, p) => [`${number(v)} claims / ${currency(p.payload.amount)}`, p.payload.encounter_type]} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-sm text-slate-500">No encounter type data available.</p>
          )}
        </ChartCard>

        <ChartCard title="By Claim Status">
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={by_status}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="status" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="count" name="Claims" fill="#6366f1" />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  );
}
