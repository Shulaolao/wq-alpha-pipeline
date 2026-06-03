'use client';

interface PipelineStatsProps {
  generated: number;
  isPassed: number;
  isFail: number;
  scPassed: number;
  scFail: number;
  submitted: number;
  failed: number;
  iterations: number;
  lastUpdated: string;
  duration?: string;
}

const passCards = [
  { key: 'generated', label: 'Generated', color: 'text-white', bg: 'bg-zinc-500', icon: '✦' },
  { key: 'isPassed', label: 'IS Passed', color: 'text-emerald-400', bg: 'bg-emerald-500', icon: '◉' },
  { key: 'scPassed', label: 'SC Passed', color: 'text-indigo-400', bg: 'bg-indigo-500', icon: '◆' },
  { key: 'submitted', label: 'Submitted', color: 'text-amber-400', bg: 'bg-amber-500', icon: '⬆' },
] as const;

const failCards = [
  { key: 'isFail', label: 'IS Failed', color: 'text-rose-400', bg: 'bg-rose-500', icon: '✖' },
  { key: 'scFail', label: 'SC Failed', color: 'text-rose-400', bg: 'bg-rose-500', icon: '✖' },
  { key: 'failed', label: 'Submit Failed', color: 'text-red-400', bg: 'bg-red-500', icon: '⚠' },
] as const;

function StatCard({ label, icon, color, bg, value, total }: {
  label: string; icon: string; color: string; bg: string; value: number; total: number;
}) {
  const pct = total > 0 ? (value / total) * 100 : 0;
  return (
    <div className="group relative bg-zinc-900/60 border border-white/[0.03] rounded-lg p-2
                    hover:border-white/[0.06] transition-all duration-200">
      <div className="flex items-center gap-1 mb-1">
        <span className="text-[10px]">{icon}</span>
        <span className="text-[8px] text-gray-500">{label}</span>
      </div>
      <div className={`text-lg font-bold tabular-nums leading-none ${color}`}>{value}</div>
      <div className="mt-1 h-0.5 bg-zinc-800/80 rounded-full overflow-hidden">
        <div className={`h-full ${bg} rounded-full transition-all duration-1000`}
          style={{ width: `${Math.max(pct, 2)}%` }} />
      </div>
    </div>
  );
}

export default function PipelineStats(props: PipelineStatsProps) {
  const total = props.generated;
  const now = props.lastUpdated ? new Date(props.lastUpdated).toLocaleTimeString() : '';
  const get = (k: keyof PipelineStatsProps) => props[k];

  return (
    <div className="card p-2 md:p-3">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-[9px] font-semibold uppercase tracking-[0.12em] text-gray-500">Pipeline Stats</h2>
        {props.duration && <span className="text-[8px] text-zinc-600 font-mono">⏱ {props.duration}</span>}
      </div>

      {/* Success funnel */}
      <div className="grid grid-cols-4 gap-1.5">
        {passCards.map(c => (
          <StatCard key={c.key} label={c.label} icon={c.icon} color={c.color} bg={c.bg}
            value={get(c.key as keyof PipelineStatsProps) as number} total={total} />
        ))}
      </div>

      {/* Failure stats */}
      <div className="grid grid-cols-3 gap-1.5 mt-1.5">
        {failCards.map(c => (
          <StatCard key={c.key} label={c.label} icon={c.icon} color={c.color} bg={c.bg}
            value={get(c.key as keyof PipelineStatsProps) as number} total={total} />
        ))}
      </div>

      {/* Conversion bar */}
      {total > 0 && (
        <div className="mt-1.5">
          <div className="flex items-center justify-between text-[8px] text-zinc-600 mb-0.5">
            <span>转化</span>
            <span className="text-zinc-500 font-mono">{props.submitted}/{total} · {((props.submitted / total) * 100).toFixed(1)}%</span>
          </div>
          <div className="h-0.5 bg-zinc-800/70 rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-indigo-600 to-emerald-500 rounded-full transition-all duration-1000"
              style={{ width: `${(props.submitted / total) * 100}%` }} />
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between mt-2 pt-1.5 border-t border-white/[0.03]">
        <span className="text-[8px] text-zinc-700">{now ? `🕐 ${now}` : ''}</span>
        <span className="text-[8px] text-zinc-700">iter {props.iterations || 0}</span>
      </div>
    </div>
  );
}
