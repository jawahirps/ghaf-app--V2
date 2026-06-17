import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import useAnalyticsReport from "../../hooks/useAnalyticsReport";
import KpiCard from "../../components/KpiCard";
import ChartCard from "../../components/ChartCard";
import DataTable from "../../components/DataTable";
import { currency, number, percent } from "../../utils/format";

export default function Submissions({ filters }) {
  const { data, error, loading } = useAnalyticsReport("submissions", filters);

  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return null;

  const { kpis, monthly_trend, by_clinician, by_service } = data;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <KpiCard label="Total Submitted" value={currency(kpis.total_submitted_amount)} />
        <KpiCard label="Submitted Claims" value={number(kpis.total_submitted_claims)} />
        <KpiCard label="Total Paid" value={currency(kpis.total_paid_amount)} accent="text-emerald-600" />
        <KpiCard label="Rejected Amount" value={currency(kpis.rejected_amount)} accent="text-red-600" />
        <KpiCard label="Remitted Amount" value={currency(kpis.remitted_amount)} />
        <KpiCard label="Not Yet Remitted" value={currency(kpis.not_remitted_amount)} accent="text-amber-600" />
      </div>

      <ChartCard title="Submission Trend" description="Claimed vs. paid vs. rejected amounts by month.">
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={monthly_trend}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="month" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => currency(v)} width={90} />
            <Tooltip formatter={(v) => currency(v)} />
            <Legend />
            <Line type="monotone" dataKey="claimed_amount" name="Claimed" stroke="#0ea5a4" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="paid_amount" name="Paid" stroke="#10b981" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="rejected_amount" name="Rejected" stroke="#ef4444" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <ChartCard title="Top Clinicians by Claimed Amount">
          <DataTable
            columns={[
              { key: "clinician", label: "Clinician" },
              { key: "department", label: "Department" },
              { key: "claimed_amount", label: "Claimed", render: currency },
              { key: "pct_of_total", label: "% of Total", render: percent },
            ]}
            rows={by_clinician}
          />
        </ChartCard>

        <ChartCard title="Top Services by Claimed Amount">
          <DataTable
            columns={[
              { key: "code", label: "Code" },
              { key: "description", label: "Description" },
              { key: "claimed_amount", label: "Claimed", render: currency },
            ]}
            rows={by_service}
          />
        </ChartCard>
      </div>
    </div>
  );
}
