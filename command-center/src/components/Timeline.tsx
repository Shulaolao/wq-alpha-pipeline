'use client';

import { useMemo } from 'react';

interface Candidate {
  name?: string;
  expr?: string;
  skeleton?: string;
  alpha_id?: string;
  sharpe?: number | null;
  fitness?: number | null;
  sim_progress?: number | null;
  [key: string]: any;
}

interface TimelineProps {
  events: any[];
  total?: number;
  currentCandidate?: Candidate | null;
}

const EVENT_ICONS: Record<string, string> = {
  is_pass: '✅',
  is_fail: '❌',
  is_done: '◉',
  is_tune: '🔧',
  sc_pass: '✅',
  sc_fail: '❌',
  sc_done: '◆',
  submitted: '⬆',
  generated: '✦',
  optimized: '⚡',
  phase_complete: '✓',
};

const EVENT_COLORS: Record<string, string> = {
  is_pass: '#34d399',
  is_fail: '#fb7185',
  is_done: '#34d399',
  is_tune: '#fbbf24',
  sc_pass: '#818cf8',
  sc_fail: '#fb7185',
  sc_done: '#818cf8',
  submitted: '#f59e0b',
  generated: '#6366f1',
  optimized: '#a78bfa',
  phase_complete: '#6ee7b7',
};

function fmt(s: number | null | undefined, decimals = 2): string {
  if (s == null) return '';
  return s.toFixed(decimals);
}

export default function Timeline({ events, total, currentCandidate }: TimelineProps) {
  // Normalize: flatten SQLite nested format into flat event list with alpha metadata
  const flatEvents = useMemo(() => {
    if (!events?.length) return [];
    const first = events[0];
    if ('timestamp' in first && first.timestamp) {
      // Legacy flat format
      return events.map((evt: any) => ({
        timestamp: evt.timestamp,
        event: evt.event,
        alphaName: evt.alpha_name || '',
        alphaExpr: evt.alpha_expr || '',
        sharpe: evt.details?.sharpe,
        fitness: evt.details?.fitness,
        scValue: evt.details?.sc_value,
        scResult: evt.details?.sc_result,
      }));
    }
    // SQLite grouped format: {name, expr, alpha_id, events: [...]}
    const flat: any[] = [];
    for (const alpha of events) {
      const alphaName = alpha.name || '';
      const alphaExpr = alpha.expr || '';
      for (const subEvt of (alpha.events || [])) {
        flat.push({
          timestamp: subEvt.created_at || '',
          event: subEvt.event_type || '',
          alphaName,
          alphaExpr,
          sharpe: subEvt.sharpe,
          fitness: subEvt.fitness,
          scValue: subEvt.sc_value,
          scResult: subEvt.sc_result,
        });
      }
    }
    return flat;
  }, [events]);

  // Sort newest first, limit to 50
  const sorted = useMemo(() =>
    [...flatEvents]
      .sort((a: any, b: any) => {
        const ta = a.timestamp ? new Date(a.timestamp).getTime() : 0;
        const tb = b.timestamp ? new Date(b.timestamp).getTime() : 0;
        return tb - ta;
      })
      .slice(0, 50),
    [flatEvents]
  );

  const hasCurrent = currentCandidate && currentCandidate.expr;

  const header = (
    <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 mb-3 flex items-center gap-2">
      Recent Activity
      <span className="text-[10px] text-gray-600 font-mono font-normal normal-case">
        {total ?? sorted.length} events
      </span>
    </h2>
  );

  return (
    <div className="card p-4">
      {header}

      {/* Current Tuning Expression */}
      {hasCurrent && (
        <div className="mb-3 p-2.5 rounded-lg bg-indigo-500/8 border border-indigo-500/15">
          <div className="text-[10px] text-indigo-400 font-semibold uppercase tracking-wider mb-1">
            {currentCandidate!.name || 'Current'} · 正在调优
          </div>
          <div className="text-[11px] text-gray-200 font-mono leading-relaxed break-all">
            {currentCandidate!.expr}
          </div>
          {(currentCandidate!.sharpe != null || currentCandidate!.fitness != null) && (
            <div className="flex gap-3 mt-1 text-[10px] font-mono">
              {currentCandidate!.sharpe != null && (
                <span className="text-indigo-300">S={fmt(currentCandidate!.sharpe)}</span>
              )}
              {currentCandidate!.fitness != null && (
                <span className="text-indigo-300">F={fmt(currentCandidate!.fitness)}</span>
              )}
              {currentCandidate!.sim_progress != null && currentCandidate!.sim_progress > 0 && (
                <span className="text-amber-300">{(currentCandidate!.sim_progress * 100).toFixed(0)}%</span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Event List */}
      <div className="space-y-0.5 text-xs max-h-56 overflow-y-auto">
        {sorted.length === 0 ? (
          <div className="text-gray-600 text-xs text-center py-6">No activity yet</div>
        ) : (
          sorted.map((evt: any, i: number) => {
            const eventType = evt.event || '';
            const icon = EVENT_ICONS[eventType] || '•';
            const color = EVENT_COLORS[eventType] || '#6b7280';
            const desc = evt.sharpe != null
              ? `S=${fmt(evt.sharpe)}`
              : evt.scValue != null
                ? `SC=${fmt(evt.scValue, 3)}`
                : '';
            const time = evt.timestamp
              ? new Date(evt.timestamp).toLocaleTimeString()
              : '';
            return (
              <div
                key={`${evt.timestamp}-${i}`}
                className="flex items-start gap-2 text-gray-400 hover:text-gray-300 transition-colors py-1.5 px-1 rounded hover:bg-white/[0.02]"
              >
                <span className="text-xs shrink-0 mt-0.5" style={{ color }}>{icon}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-gray-600 text-[10px] font-mono shrink-0">{time}</span>
                    <span className="text-gray-500 capitalize text-[10px] shrink-0">
                      {eventType.replace(/_/g, ' ')}
                    </span>
                    {desc && (
                      <span className="text-gray-600 font-mono text-[10px] shrink-0">{desc}</span>
                    )}
                  </div>
                  {evt.alphaName && (
                    <div className="text-gray-500 text-[10px] font-mono truncate mt-0.5 leading-tight">
                      {evt.alphaName}{evt.alphaExpr ? `: ${evt.alphaExpr.slice(0, 80)}` : ''}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
