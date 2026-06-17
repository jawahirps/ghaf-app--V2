import { NavLink } from "react-router-dom";

const navItems = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/clinical-profiles", label: "Clinical Profiles" },
  { to: "/dha-sync", label: "DHA XML Sync" },
  { to: "/analytics", label: "Analytics & Financial Insights" },
  { to: "/facility-settings", label: "Facility Settings" },
  { to: "/login-activity", label: "Login Activity" },
];

const linkClasses = ({ isActive }) =>
  `block rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
    isActive ? "bg-ghaf-600 text-white" : "text-slate-300 hover:bg-slate-800 hover:text-white"
  }`;

export default function Sidebar() {
  return (
    <aside className="flex h-full w-64 flex-col bg-slate-900 px-4 py-6">
      <div className="mb-8 px-2">
        <p className="text-lg font-bold tracking-wide text-white">Ghaf App</p>
        <p className="text-xs text-slate-400">RCM &amp; Clinical Platform</p>
      </div>
      <nav className="flex flex-1 flex-col gap-1">
        {navItems.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end} className={linkClasses}>
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
