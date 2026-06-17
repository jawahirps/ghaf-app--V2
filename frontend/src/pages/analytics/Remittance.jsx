import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import useAnalyticsReport from "../../hooks/useAnalyticsReport";
import KpiCard from "../../components/KpiCard";
import ChartCard from "../../components/ChartCard";
import DataTable from "../../components/DataTable";
import { currency, number } from "../../utils/format";

export default function Remittance({ filters }) {
  const { data, error, loading } = useAnalyticsReport("remittance", filters);

  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return null;

  const { kpis, monthly_trend, aging_buckets, by_payer } = data;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <KpiCard label="Total Paid" value={currency(kpis.total_paid_amount)} accent="text-emerald-600" />
        <KpiCard label="Total Denied" value={currency(kpis.total_denied_amount)} accent="text-red-600" />
        <KpiCard label="Total Discount" value={currency(kpis.total_discount_amount)} accent="text-amber-600" />
        <KpiCard label="Remitted Claims" value={number(kpis.remitted_claims)} />
        <KpiCard label="Avg. Turnaround (days)" value={kpis.avg_turnaround_days} />
      </div>

      <ChartCard title="Remittance Trend" description="Paid, denied, and discount amounts by month.">
        <ResponsiveContainer width="100%" height={320}>
          <AreaChart data={monthly_trend}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="month" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => currency(v)} width={90} />
            <Tooltip formatter={(v) => currency(v)} />
            <Legend />
            <Area type="monotone" dataKey="paid_amount" name="Paid" stackId="1" stroke="#10b981" fill="#a7f3d0" />
            <Area type="monotone" dataKey="denied_amount" name="Denied" stackId="1" stroke="#ef4444" fill="#fecaca" />
            <Area type="monotone" dataKey="discount_amount" name="Discount" stackId="1" stroke="#f59e0b" fill="#fde68a" />
          </AreaChart>
        </ResponsiveContainer>
      </ChartCard>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <ChartCard title="Aging Buckets" description="Paid amount by remittance turnaround time.">
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={aging_buckets}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => currency(v)} width={90} />
              <Tooltip formatter={(v) => currency(v)} />
              <Bar dataKey="amount" name="Amount" fill="#0ea5a4" />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="By Payer">
          <DataTable
            columns={[
              { key: "payer", label: "Payer" },
              { key: "paid_amount", label: "Paid", render: currency },
              { key: "denied_amount", label: "Denied", render: currency },
            ]}
            rows={by_payer}
          />
        </ChartCard>
      </div>
    </div>
  );
}
