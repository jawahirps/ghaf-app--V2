import useAnalyticsReport from "../../hooks/useAnalyticsReport";
import KpiCard from "../../components/KpiCard";
import ChartCard from "../../components/ChartCard";
import DataTable from "../../components/DataTable";
import { currency, number, percent } from "../../utils/format";

export default function Clinicians({ filters }) {
  const { data, error, loading } = useAnalyticsReport("clinicians", filters);

  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return null;

  const { kpis, clinicians } = data;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <KpiCard label="Total Claimed" value={currency(kpis.total_claimed_amount)} />
        <KpiCard label="Clinicians" value={number(kpis.clinician_count)} />
      </div>

      <ChartCard title="Clinician Performance" description="Claimed, paid, and denied amounts by clinician.">
        <DataTable
          columns={[
            { key: "clinician", label: "Clinician" },
            { key: "department", label: "Department" },
            { key: "claim_count", label: "Claims", render: number },
            { key: "claimed_amount", label: "Claimed", render: currency },
            { key: "paid_amount", label: "Paid", render: currency },
            { key: "denied_amount", label: "Denied", render: currency },
            { key: "pct_of_total", label: "% of Total", render: percent },
          ]}
          rows={clinicians}
        />
      </ChartCard>
    </div>
  );
}
