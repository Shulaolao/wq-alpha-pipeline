'use client';

import { useMemo } from 'react';
import type { HistoryEvent } from '@/services/api';

interface TimelineProps {
  events: HistoryEvent[];
  total?: number;
}

const EVENT_CONFIG: Record<string, { icon: string; color: string }> = {
  generated:  { icon: '✦', color: '#6366f1' },
  is_pass:    { icon: '✅', color: '#34d399' },
  is_fail:    { icon: '❌', color: '#fb7185' },
  is_tune:    { icon: '🔧', color: '#f59e0b' },
  sc_pass:    { icon: '◆', color: '#818cf8' },
  sc_fail:    { icon: '◆', color: '#fb7185' },
  submitted:  { icon: '⬆', color: '#f59e0b' },
  failed:     { icon: '✖', color: '#fb7185' },
  optimized:  { icon: '🔄', color: '#a78bfa' },
  sc_timeout_pending: { icon: '⏸', color: '#fbbf24' },
  timeout:    { icon: '⏱', color: '#fb923c' },
};

function getEventLabel(type: string): string {
  const labels: Record<string, string> = {
    generated: 'Generated',
    is_pass: 'IS Pass',
    is_fail: 'IS Fail',
    is_tune: 'IS Tune',
    sc_pass: 'SC Pass',
    sc_fail: 'SC Fail',
    submitted: 'Submitted',
    failed: 'Failed',
    optimized: 'Optimized',
    sc_timeout_pending: 'SC Pending',
    timeout: 'Timeout',
    is_done: 'IS Done',
    sc_done: 'SC Done',
    phase_complete: 'Phase Complete',
    candidate_fail: 'Candidate Fail',
    sim_resolved: 'Sim Resolved',
  };
  return labels[type] || type;
}

export default function Timeline({ events, total }: TimelineProps) {
  const sorted = useMemo(() =>
    [...events]
      .sort((a, b) => {
        const ta = a.timestamp || a.created_at || '';
        const tb = b.timestamp || b.created_at || '';
        return new Date(tb).getTime() - new Date(ta).getTime();
      })
      .slice(0, 50),
    [events]
  );

  const header = (
    <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 mb-3 flex items-center gap-2">
      Alpha History
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
          const cfg = EVENT_CONFIG[evt.event_type] || { icon: '•', color: '#6b7280' };
          const time = (evt.timestamp || evt.created_at)
            ? new Date(evt.timestamp || evt.created_at || '').toLocaleTimeString()
            : '';
          
          // Build detail string
          const parts: string[] = [];
          if (evt.sharpe != null && evt.sharpe !== null) {
            parts.push(`S=${Number(evt.sharpe).toFixed(2)}`);
          }
          if (evt.fitness != null && evt.fitness !== null) {
            parts.push(`F=${Number(evt.fitness).toFixed(2)}`);
          }
          if (evt.sc_value != null && evt.sc_value !== null) {
            parts.push(`SC=${Number(evt.sc_value).toFixed(3)}`);
          }
          if (evt.is_status) {
            parts.push(evt.is_status);
          }
          if (evt.sc_result) {
            parts.push(evt.sc_result);
          }
          const desc = parts.join(' ');
          
          return (
            <div key={i} className="flex items-center gap-2 text-gray-400 hover:text-gray-300 transition-colors py-0.5">
              <span style={{ color: cfg.icon }}>{cfg.icon}</span>
              <span className="text-gray-600 w-16 shrink-0 font-mono text-[10px]">{time}</span>
              <span className="text-gray-500 truncate" title={evt.name}>{evt.name}</span>
              <span className="text-gray-400 capitalize text-[10px]">{getEventLabel(evt.event_type)}</span>
              {desc && <span className="text-gray-600 font-mono text-[10px]">{desc}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
