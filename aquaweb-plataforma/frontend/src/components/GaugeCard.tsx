import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { Line, LineChart, ResponsiveContainer } from "recharts";

interface GaugeCardProps {
  label: string;
  unit: string;
  value: number;
  prevValue?: number;
  minOptimal: number;
  maxOptimal: number;
  minPhysical: number;
  maxPhysical: number;
  color: string;
  sparkline: Array<{ v: number }>;
}

export function GaugeCard({
  label,
  unit,
  value,
  prevValue,
  minOptimal,
  maxOptimal,
  minPhysical,
  maxPhysical,
  color,
  sparkline,
}: GaugeCardProps) {
  const span = Math.max(maxOptimal - minOptimal, 0.1);
  let status: "Óptimo" | "Advertencia" | "Crítico" = "Óptimo";
  if (value < minOptimal || value > maxOptimal) {
    const dist = value < minOptimal ? minOptimal - value : value - maxOptimal;
    status = dist >= 0.15 * span ? "Crítico" : "Advertencia";
  }

  const badgeStyles = {
    Óptimo: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    Advertencia: "bg-amber-50 text-amber-700 ring-amber-200",
    Crítico: "bg-rose-50 text-rose-700 ring-rose-200",
  }[status];

  const gaugeColor = {
    Óptimo: "#10b981",
    Advertencia: "#f59e0b",
    Crítico: "#e11d48",
  }[status];

  const pct = Math.min(1, Math.max(0, (value - minPhysical) / Math.max(maxPhysical - minPhysical, 1)));
  const arcLen = 126; // semicirculo radio 40 (pi * 40 ≈ 125.6)
  const dashOffset = arcLen * (1 - pct);

  const delta = prevValue !== undefined ? Number((value - prevValue).toFixed(2)) : 0;

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm transition hover:shadow-md print-break-avoid">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
          <div className="mt-1 flex items-baseline gap-1.5">
            <span className="text-2xl font-bold text-slate-900">
              {value >= 1000 ? value.toLocaleString("es-PA", { maximumFractionDigits: 0 }) : value.toFixed(2)}
            </span>
            <span className="text-xs font-medium text-slate-500">{unit}</span>
          </div>
        </div>
        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${badgeStyles}`}>
          {status}
        </span>
      </div>

      {/* Gauge semicircular */}
      <div className="my-2 flex items-center justify-between gap-3">
        <svg viewBox="0 0 100 58" className="h-16 w-28 shrink-0">
          <path
            d="M 10 50 A 40 40 0 0 1 90 50"
            fill="none"
            stroke="#e2e8f0"
            strokeWidth="9"
            strokeLinecap="round"
          />
          <path
            d="M 10 50 A 40 40 0 0 1 90 50"
            fill="none"
            stroke={gaugeColor}
            strokeWidth="9"
            strokeLinecap="round"
            strokeDasharray={arcLen}
            strokeDashoffset={dashOffset}
          />
          <text x="50" y="48" textAnchor="middle" className="fill-slate-500 text-[9px] font-medium">
            {minOptimal}–{maxOptimal}
          </text>
        </svg>

        <div className="h-14 flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={sparkline}>
              <Line type="monotone" dataKey="v" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="flex items-center justify-between border-t border-slate-100 pt-2 text-xs text-slate-500">
        <span>
          Óptimo: {minOptimal.toLocaleString("es-PA")} – {maxOptimal.toLocaleString("es-PA")} {unit}
        </span>
        <span className="inline-flex items-center gap-0.5 font-medium text-slate-700">
          {delta > 0 ? (
            <ArrowUpRight className="h-3.5 w-3.5 text-amber-600" />
          ) : delta < 0 ? (
            <ArrowDownRight className="h-3.5 w-3.5 text-sky-600" />
          ) : (
            <Minus className="h-3.5 w-3.5 text-slate-400" />
          )}
          {delta > 0 ? `+${delta}` : delta}
        </span>
      </div>
    </div>
  );
}
