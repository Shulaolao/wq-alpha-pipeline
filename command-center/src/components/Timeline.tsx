'use client';

import { useMemo } from 'react';
import type { HistoryEvent } from '@/types/dashboard';

interface TimelineProps {
  events: HistoryEvent[];
  total?: number;
}

const EVENT_ICONS: Record<string, string> = {
  is_done: '◉',
  sc_done: '◆',
  submitted: '⬆',
  generated: '✦',
  phase_complete: '✓',
};

const EVENT_COLORS: Record<string, string> = {
  is_done: '#34d399',
  sc_done: '#818cf8',
  submitted: '#f59e0b',
  generated: '#6366f1',
  phase_complete: '#6ee7b7',
};

export default function Timeline({ events, total }: TimelineProps) {
  const sorted = useMemo(() =>
    [...events]
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
      .slice(0, 30),
    [events]
  );

  const header = (
    <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 mb-3 flex items-center gap-2">
      Recent Activity
      {total != null && (
        <span className="text-[10px] text-gray-600 font-mono font-normal normal-case">{total} events</span>
      )}
    </h2>
  );

  if (sorted.length === 0) {
    return (
      <div className="card p-4">
        {header}
        <div className="text-gray-600 text-xs text-center py-6">No activity yet</div>
      </div>
    );
  }

  return (
    <div className="card p-4">
      {header}
      <div className="space-y-1 text-xs max-h-44 overflow-y-auto">
        {sorted.map((evt, i) => {
          const icon = EVENT_ICONS[evt.event] || '•';
          const color = EVENT_COLORS[evt.event] || '#6b7280';
          const desc = evt.details?.sharpe
            ? `S=${Number(evt.details.sharpe).toFixed(2)}`
            : evt.details?.sc_value
              ? `SC=${Number(evt.details.sc_value).toFixed(3)}`
              : evt.details?.count
                ? `count=${evt.details.count}`
                : '';
          const time = evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : '';
          return (
            <div key={i} className="flex items-center gap-2 text-gray-400 hover:text-gray-300 transition-colors py-0.5">
              <span style={{ color }}>{icon}</span>
              <span className="text-gray-600 w-16 shrink-0 font-mono text-[10px]">{time}</span>
              <span className="text-gray-500 capitalize">{evt.event.replace(/_/g, ' ')}</span>
              {desc && <span className="text-gray-600 font-mono">{desc}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
