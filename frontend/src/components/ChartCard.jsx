export default function ChartCard({ title, description, children, className }) {
  return (
    <div className={`rounded-xl bg-white p-5 shadow-sm ${className || ""}`}>
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      {description && <p className="mt-1 text-xs text-slate-500">{description}</p>}
      <div className="mt-4">{children}</div>
    </div>
  );
}
