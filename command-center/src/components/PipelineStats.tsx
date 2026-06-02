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

const statCards = [
  { key: 'generated', label: 'Generated', color: 'text-white', icon: '✦', group: 'pass' },
  { key: 'isPassed', label: 'IS Passed', color: 'text-emerald-400', icon: '◉', group: 'pass' },
  { key: 'scPassed', label: 'SC Passed', color: 'text-indigo-400', icon: '◆', group: 'pass' },
  { key: 'submitted', label: 'Submitted', color: 'text-amber-400', icon: '⬆', group: 'pass' },
  { key: 'isFail', label: 'IS Failed', color: 'text-rose-400', icon: '✖', group: 'fail' },
  { key: 'scFail', label: 'SC Failed', color: 'text-rose-400', icon: '✖', group: 'fail' },
  { key: 'failed', label: 'Submit Failed', color: 'text-red-400', icon: '⚠', group: 'fail' },
] as const;

export default function PipelineStats(props: PipelineStatsProps) {
  return (
    <div className="card p-4">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 mb-3">
        Pipeline Stats
      </h2>
      <div className="grid grid-cols-4 gap-2">
        {statCards.map(({ key, label, color, icon }) => (
          <div
            key={key}
            className="bg-dark-800/60 border border-white/[0.04] rounded-xl p-3 text-center
                       hover:border-indigo-500/10 hover:-translate-y-[1px] transition-all duration-200"
          >
            <div className={`text-lg font-bold tabular-nums tracking-tight ${color}`}>
              {props[key as keyof PipelineStatsProps] ?? 0}
            </div>
            <div className="flex items-center justify-center gap-1 text-[9px] text-gray-500 mt-1">
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
