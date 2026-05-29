'use client';

interface PipelineStatsProps {
  generated: number;
  isPassed: number;
  scPassed: number;
  submitted: number;
  iterations: number;
  lastUpdated: string;
  duration?: string;
}

const statCards = [
  { key: 'generated', label: 'Generated', color: 'text-white', icon: '✦' },
  { key: 'isPassed', label: 'IS Passed', color: 'text-emerald-400', icon: '◉' },
  { key: 'scPassed', label: 'SC Passed', color: 'text-indigo-400', icon: '◆' },
  { key: 'submitted', label: 'Submitted', color: 'text-amber-400', icon: '⬆' },
] as const;

export default function PipelineStats(props: PipelineStatsProps) {
  return (
    <div className="card p-4">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 mb-3">
        Pipeline Stats
      </h2>
      <div className="grid grid-cols-2 gap-2.5">
        {statCards.map(({ key, label, color, icon }) => (
          <div
            key={key}
            className="bg-dark-800/60 border border-white/[0.04] rounded-xl p-4 text-center
                       hover:border-indigo-500/10 hover:-translate-y-[1px] transition-all duration-200"
          >
            <div className={`text-lg font-bold tabular-nums tracking-tight ${color}`}>
              {props[key as keyof PipelineStatsProps] ?? 0}
            </div>
            <div className="flex items-center justify-center gap-1.5 text-[10px] text-gray-500 mt-1">
              <span>{icon}</span>
              <span>{label}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="flex justify-between text-[10px] text-gray-600 mt-2.5">
        <span suppressHydrationWarning>
          {props.lastUpdated ? new Date(props.lastUpdated).toLocaleTimeString() : ''}
        </span>
        <span>iter {props.iterations || 0}</span>
      </div>
    </div>
  );
}
