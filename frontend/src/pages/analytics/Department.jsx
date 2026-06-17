import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import useAnalyticsReport, { CHART_COLORS } from "../../hooks/useAnalyticsReport";
import KpiCard from "../../components/KpiCard";
import ChartCard from "../../components/ChartCard";
import DataTable from "../../components/DataTable";
import { currency, number, percent } from "../../utils/format";

function pivotByMonth(rows) {
  const months = {};
  const departments = new Set();
  for (const row of rows || []) {
    departments.add(row.department);
    if (!months[row.month]) months[row.month] = { month: row.month };
    months[row.month][row.department] = row.claimed_amount;
  }
  return {
    data: Object.values(months).sort((a, b) => (a.month > b.month ? 1 : -1)),
    departments: Array.from(departments),
  };
}

export default function Department({ filters }) {
  const { data, error, loading } = useAnalyticsReport("department", filters);

  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return null;

  const { kpis, by_department, monthly_trend } = data;
  const { data: trendData, departments } = pivotByMonth(monthly_trend);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <KpiCard label="Total Claimed" value={currency(kpis.total_claimed_amount)} />
      </div>

      <ChartCard title="Claimed Amount by Department, by Month">
        <ResponsiveContainer width="100%" height={320}>
          <BarChart data={trendData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="month" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => currency(v)} width={90} />
            <Tooltip formatter={(v) => currency(v)} />
            <Legend />
            {departments.map((dept, idx) => (
              <Bar key={dept} dataKey={dept} name={dept} stackId="dept" fill={CHART_COLORS[idx % CHART_COLORS.length]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      <ChartCard title="Department Detail">
        <DataTable
          columns={[
            { key: "department", label: "Department" },
            { key: "claim_count", label: "Claims", render: number },
            { key: "claimed_amount", label: "Claimed", render: currency },
            { key: "paid_amount", label: "Paid", render: currency },
            { key: "denied_amount", label: "Denied", render: currency },
            { key: "pct_of_total", label: "% of Total", render: percent },
          ]}
          rows={by_department}
        />
      </ChartCard>
    </div>
  );
}
