import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from "recharts";
import useAnalyticsReport, { CHART_COLORS } from "../../hooks/useAnalyticsReport";
import KpiCard from "../../components/KpiCard";
import ChartCard from "../../components/ChartCard";
import DataTable from "../../components/DataTable";
import { currency, number, percent } from "../../utils/format";

export default function Insurance({ filters }) {
  const { data, error, loading } = useAnalyticsReport("insurance", filters);

  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return null;

  const { kpis, by_payer, by_receiver } = data;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <KpiCard label="Total Claimed" value={currency(kpis.total_claimed_amount)} />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <ChartCard title="Claimed Amount by Payer">
          {by_payer && by_payer.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie data={by_payer} dataKey="claimed_amount" nameKey="payer" outerRadius={110} label={(d) => d.payer}>
                  {by_payer.map((_, idx) => (
                    <Cell key={idx} fill={CHART_COLORS[idx % CHART_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v) => currency(v)} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-sm text-slate-500">No payer data available.</p>
          )}
        </ChartCard>

        <ChartCard title="By Receiver">
          <DataTable
            columns={[
              { key: "receiver", label: "Receiver" },
              { key: "claim_count", label: "Claims", render: number },
              { key: "claimed_amount", label: "Claimed", render: currency },
            ]}
            rows={by_receiver}
          />
        </ChartCard>
      </div>

      <ChartCard title="Payer Detail">
        <DataTable
          columns={[
            { key: "payer", label: "Payer" },
            { key: "claim_count", label: "Claims", render: number },
            { key: "claimed_amount", label: "Claimed", render: currency },
            { key: "paid_amount", label: "Paid", render: currency },
            { key: "denied_amount", label: "Denied", render: currency },
            { key: "pct_of_total", label: "% of Total", render: percent },
          ]}
          rows={by_payer}
        />
      </ChartCard>
    </div>
  );
}
