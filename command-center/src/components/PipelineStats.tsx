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

// 辅助函数：计算转化率
function calcRate(numerator: number, denominator: number, decimals = 1): string {
  if (denominator === 0) return '0.0%';
  return ((numerator / denominator) * 100).toFixed(decimals) + '%';
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

function StatCard({ label, icon, color, bg, value, total, isFailure }: {
  label: string; icon: string; color: string; bg: string; value: number; total: number; isFailure?: boolean;
}) {
  const pct = total > 0 ? (value / total) * 100 : 0;
  return (
    <div className={`group relative rounded-lg p-2
                    hover:border-white/[0.06] transition-all duration-200
                    ${isFailure
                      ? 'bg-gradient-to-br from-rose-950/20 to-zinc-900/60 border border-rose-500/[0.06]'
                      : 'bg-zinc-900/60 border border-white/[0.03]'}`}>
      <div className="flex items-center gap-1 mb-1">
        <span className="text-[10px]">{icon}</span>
        <span className="text-[8px] text-gray-500">{label}</span>
      </div>
      <div className={`text-lg font-bold tabular-nums leading-none ${color}`}>{value}</div>
      <div className="mt-1 h-0.5 bg-zinc-800/80 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-1000
          ${isFailure
            ? `bg-gradient-to-r from-rose-600 to-rose-500 ${color === 'text-red-400' ? '' : 'from-rose-700 to-rose-600'}`
            : bg}`}
          style={{ width: `${Math.max(pct, 2)}%` }} />
      </div>
      {isFailure && (
        <div className="absolute inset-0 rounded-lg bg-rose-500/[0.02] opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none" />
      )}
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

      <div className="grid grid-cols-4 gap-1.5">
        {passCards.map(c => (
          <StatCard key={c.key} label={c.label} icon={c.icon} color={c.color} bg={c.bg}
            value={get(c.key as keyof PipelineStatsProps) as number} total={total} />
        ))}
      </div>

      <div className="grid grid-cols-3 gap-1.5 mt-1.5">
        {failCards.map(c => (
          <StatCard key={c.key} label={c.label} icon={c.icon} color={c.color} bg={c.bg}
            value={get(c.key as keyof PipelineStatsProps) as number} total={total} isFailure />
        ))}
      </div>

      {/* 转化率指标组 - 新增 */}
      {total > 0 && (
        <div className="mt-1.5 space-y-1.5">
          {/* IS转化率 */}
          <div>
            <div className="flex items-center justify-between text-[8px] text-zinc-600 mb-0.5">
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500/50"></span>
                IS通过率
              </span>
              <span className="text-zinc-500 font-mono">
                {calcRate(props.isPassed, total)} ({props.isPassed}/{total})
              </span>
            </div>
            <div className="h-0.5 bg-zinc-800/70 rounded-full overflow-hidden">
              <div 
                className="h-full bg-gradient-to-r from-emerald-600 to-emerald-500 rounded-full transition-all duration-1000"
                style={{ width: `${(props.isPassed / total) * 100}%` }} 
              />
            </div>
          </div>

          {/* SC转化率 */}
          <div>
            <div className="flex items-center justify-between text-[8px] text-zinc-600 mb-0.5">
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-500/50"></span>
                SC通过率
              </span>
              <span className="text-zinc-500 font-mono">
                {calcRate(props.scPassed, props.isPassed)} ({props.scPassed}/{props.isPassed})
              </span>
            </div>
            <div className="h-0.5 bg-zinc-800/70 rounded-full overflow-hidden">
              <div 
                className="h-full bg-gradient-to-r from-indigo-600 to-indigo-500 rounded-full transition-all duration-1000"
                style={{ width: `${props.isPassed > 0 ? (props.scPassed / props.isPassed) * 100 : 0}%` }} 
              />
            </div>
          </div>

          {/* 总提交率 */}
          <div>
            <div className="flex items-center justify-between text-[8px] text-zinc-600 mb-0.5">
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500/50"></span>
                总提交率
              </span>
              <span className="text-zinc-500 font-mono">
                {calcRate(props.submitted, total)} ({props.submitted}/{total})
              </span>
            </div>
            <div className="h-0.5 bg-zinc-800/70 rounded-full overflow-hidden">
              <div 
                className="h-full bg-gradient-to-r from-amber-600 to-amber-500 rounded-full transition-all duration-1000"
                style={{ width: `${(props.submitted / total) * 100}%` }} 
              />
            </div>
          </div>

          {/* 失败率汇总 */}
          <div className="pt-1.5 border-t border-white/[0.03]">
            <div className="flex items-center justify-between text-[8px] text-zinc-600 mb-0.5">
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-rose-500/50"></span>
                失败率汇总
              </span>
              <span className="text-rose-400/80 font-mono">
                IS:{calcRate(props.isFail, total)} | SC:{calcRate(props.scFail, props.isPassed)}
              </span>
            </div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between mt-2 pt-1.5 border-t border-white/[0.03]">
        <span className="text-[8px] text-zinc-700">{now ? `🕐 ${now}` : ''}</span>
        <span className="text-[8px] text-zinc-700">iter {props.iterations || 0}</span>
      </div>
    </div>
  );
}
