import {
  BarChart,
  Bar,
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
import DataTable from "../../components/DataTable";
import { currency, number, percent } from "../../utils/format";

export default function Resubmissions({ filters }) {
  const { data, error, loading } = useAnalyticsReport("resubmissions", filters);

  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return null;

  const { kpis, monthly_trend, by_payer, by_reason } = data;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="Resubmitted Claims" value={number(kpis.total_resubmitted_claims)} />
        <KpiCard label="Total Resubmissions" value={number(kpis.total_resubmissions)} />
        <KpiCard label="Resubmitted Amount" value={currency(kpis.resubmitted_amount)} accent="text-amber-600" />
        <KpiCard label="Resubmission Rate" value={percent(kpis.resubmission_rate_pct)} />
      </div>

      <ChartCard title="Resubmissions by Month" description="Number of resubmitted claims and amount per month.">
        <ResponsiveContainer width="100%" height={320}>
          <BarChart data={monthly_trend}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="month" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Legend />
            <Bar dataKey="claim_count" name="Claims" fill="#6366f1" />
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <ChartCard title="By Payer">
          <DataTable
            columns={[
              { key: "payer", label: "Payer" },
              { key: "claim_count", label: "Claims", render: number },
              { key: "amount", label: "Amount", render: currency },
            ]}
            rows={by_payer}
          />
        </ChartCard>

        <ChartCard title="Top Resubmission Reasons">
          {by_reason && by_reason.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie data={by_reason} dataKey="count" nameKey="description" outerRadius={100} label={(d) => d.code}>
                  {by_reason.map((_, idx) => (
                    <Cell key={idx} fill={CHART_COLORS[idx % CHART_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-sm text-slate-500">No resubmission reason data available.</p>
          )}
        </ChartCard>
      </div>
    </div>
  );
}
