import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import useAnalyticsReport from "../../hooks/useAnalyticsReport";
import KpiCard from "../../components/KpiCard";
import ChartCard from "../../components/ChartCard";
import DataTable from "../../components/DataTable";
import { currency, number, percent } from "../../utils/format";

export default function Denials({ filters }) {
  const { data, error, loading } = useAnalyticsReport("denials", filters);

  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return null;

  const { kpis, monthly_trend, by_code, by_payer, by_clinician } = data;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <KpiCard label="Total Denial Amount" value={currency(kpis.total_denial_amount)} accent="text-red-600" />
        <KpiCard label="Denied Claims" value={number(kpis.denied_claims)} />
        <KpiCard label="Denial Rate" value={percent(kpis.denial_rate_pct)} />
      </div>

      <ChartCard title="Denial Trend" description="Denied amount and claim count by month.">
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={monthly_trend}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="month" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => currency(v)} width={90} />
            <Tooltip formatter={(v) => currency(v)} />
            <Legend />
            <Line type="monotone" dataKey="amount" name="Denied Amount" stroke="#ef4444" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <ChartCard title="By Denial Code">
          <DataTable
            columns={[
              { key: "code", label: "Code" },
              { key: "description", label: "Description" },
              { key: "amount", label: "Amount", render: currency },
              { key: "count", label: "Count", render: number },
            ]}
            rows={by_code}
          />
        </ChartCard>

        <ChartCard title="By Payer">
          <DataTable
            columns={[
              { key: "payer", label: "Payer" },
              { key: "amount", label: "Amount", render: currency },
            ]}
            rows={by_payer}
          />
        </ChartCard>

        <ChartCard title="By Clinician">
          <DataTable
            columns={[
              { key: "clinician", label: "Clinician" },
              { key: "amount", label: "Amount", render: currency },
            ]}
            rows={by_clinician}
          />
        </ChartCard>
      </div>
    </div>
  );
}
