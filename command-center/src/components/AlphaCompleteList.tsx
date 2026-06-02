'use client';

import { useState, useEffect, useMemo } from 'react';
import type { AlphaSummary } from '@/services/api';

interface Props {
  alphas: AlphaSummary[];
  total: number;
}

const STATUS_ORDER: Record<string, number> = {
  generated: 0,
  is_fail: 1,
  is_pass: 2,
  sc_timeout_pending: 3,
  sc_fail: 4,
  sc_pass: 5,
  submitted: 6,
  failed: 7,
};

const STATUS_COLORS: Record<string, string> = {
  generated: 'text-gray-400',
  is_fail: 'text-rose-400',
  is_pass: 'text-emerald-400',
  sc_timeout_pending: 'text-yellow-400',
  sc_fail: 'text-rose-400',
  sc_pass: 'text-indigo-400',
  submitted: 'text-amber-400',
  failed: 'text-red-400',
};

const STATUS_LABELS: Record<string, string> = {
  generated: 'Generated',
  is_fail: 'IS Failed',
  is_pass: 'IS Passed',
  sc_timeout_pending: 'SC Timeout',
  sc_fail: 'SC Failed',
  sc_pass: 'SC Passed',
  submitted: 'Submitted',
  failed: 'Submit Failed',
};

export default function AlphaCompleteList({ alphas, total }: Props) {
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [sortBy, setSortBy] = useState<'name' | 'sharpe' | 'sc_value' | 'status'>('status');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [expandedAlpha, setExpandedAlpha] = useState<string | null>(null);
  const [minSharpe, setMinSharpe] = useState('');
  const [minScValue, setMinScValue] = useState('');

  const filtered = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    const minS = minSharpe ? parseFloat(minSharpe) : null;
    const minSc = minScValue ? parseFloat(minScValue) : null;

    let list = alphas.filter((a) => {
      if (statusFilter !== 'all' && a.status !== statusFilter) return false;
      if (q && !a.name.toLowerCase().includes(q) && !(a.expr || '').toLowerCase().includes(q)) return false;
      if (minS !== null && (a.sharpe == null || a.sharpe < minS)) return false;
      if (minSc !== null && (a.sc_value == null || a.sc_value < minSc)) return false;
      return true;
    });

    list.sort((a, b) => {
      let cmp = 0;
      if (sortBy === 'name') cmp = a.name.localeCompare(b.name);
      else if (sortBy === 'sharpe') cmp = (a.sharpe ?? -99) - (b.sharpe ?? -99);
      else if (sortBy === 'sc_value') cmp = (a.sc_value ?? -99) - (b.sc_value ?? -99);
      else if (sortBy === 'status') cmp = (STATUS_ORDER[a.status] ?? 0) - (STATUS_ORDER[b.status] ?? 0);
      return sortDir === 'asc' ? cmp : -cmp;
    });

    return list;
  }, [alphas, searchQuery, statusFilter, sortBy, sortDir, minSharpe, minScValue]);

  const toggleSort = (col: typeof sortBy) => {
    if (sortBy === col) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortBy(col); setSortDir('desc'); }
  };

  // Status filter options derived from data
  const statuses = useMemo(() => {
    const s = new Set(alphas.map((a) => a.status));
    return ['all', ...Array.from(s).sort((a, b) => (STATUS_ORDER[a] ?? 0) - (STATUS_ORDER[b] ?? 0))];
  }, [alphas]);

  return (
    <div className="card p-4">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 mb-3">
        Alpha List <span className="text-gray-600">({total})</span>
      </h2>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 mb-3">
        <input
          type="text"
          placeholder="Search name/expr..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="flex-1 min-w-[160px] bg-dark-800/60 border border-white/[0.06] rounded-lg px-3 py-1.5
                     text-xs text-gray-300 placeholder-gray-600 outline-none focus:border-indigo-500/30
                     transition-colors"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="bg-dark-800/60 border border-white/[0.06] rounded-lg px-2.5 py-1.5
                     text-[10px] text-gray-400 outline-none focus:border-indigo-500/30"
        >
          {statuses.map((s) => (
            <option key={s} value={s}>{s === 'all' ? 'All Status' : STATUS_LABELS[s] || s}</option>
          ))}
        </select>
        <input
          type="number"
          step="0.1"
          placeholder="Min Sharpe"
          value={minSharpe}
          onChange={(e) => setMinSharpe(e.target.value)}
          className="w-24 bg-dark-800/60 border border-white/[0.06] rounded-lg px-2.5 py-1.5
                     text-[10px] text-gray-300 placeholder-gray-600 outline-none focus:border-indigo-500/30"
        />
        <input
          type="number"
          step="0.1"
          placeholder="Min SC Value"
          value={minScValue}
          onChange={(e) => setMinScValue(e.target.value)}
          className="w-24 bg-dark-800/60 border border-white/[0.06] rounded-lg px-2.5 py-1.5
                     text-[10px] text-gray-300 placeholder-gray-600 outline-none focus:border-indigo-500/30"
        />
      </div>

      {/* Count badge */}
      <div className="text-[10px] text-gray-600 mb-2">
        Showing {filtered.length} of {alphas.length}
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[1fr_2fr_64px_64px_72px_100px] gap-2 text-[9px] text-gray-600 uppercase tracking-wider px-2 pb-1.5 border-b border-white/[0.04]">
        <button onClick={() => toggleSort('name')} className="text-left hover:text-gray-400 transition-colors">
          Name {sortBy === 'name' && (sortDir === 'asc' ? '↑' : '↓')}
        </button>
        <div>Expression</div>
        <button onClick={() => toggleSort('sharpe')} className="text-right hover:text-gray-400 transition-colors">
          Sharpe {sortBy === 'sharpe' && (sortDir === 'asc' ? '↑' : '↓')}
        </button>
        <button onClick={() => toggleSort('sc_value')} className="text-right hover:text-gray-400 transition-colors">
          SC {sortBy === 'sc_value' && (sortDir === 'asc' ? '↑' : '↓')}
        </button>
        <div className="text-center">Attempts</div>
        <button onClick={() => toggleSort('status')} className="text-right hover:text-gray-400 transition-colors">
          Status {sortBy === 'status' && (sortDir === 'asc' ? '↑' : '↓')}
        </button>
      </div>

      {/* Rows */}
      <div className="max-h-[420px] overflow-y-auto scrollbar-thin">
        {filtered.length === 0 ? (
          <div className="text-center text-gray-600 text-xs py-8">No alphas match filters</div>
        ) : (
          filtered.map((a) => (
            <div key={a.name}>
              <button
                onClick={() => setExpandedAlpha(expandedAlpha === a.name ? null : a.name)}
                className="w-full grid grid-cols-[1fr_2fr_64px_64px_72px_100px] gap-2 px-2 py-2
                           text-xs border-b border-white/[0.02] hover:bg-white/[0.02] transition-colors text-left"
              >
                <span className="text-gray-200 font-mono text-[11px] truncate">{a.name}</span>
                <span className="text-gray-400 font-mono text-[10px] truncate" title={a.expr || ''}>
                  {a.expr || '-'}
                </span>
                <span className="text-right tabular-nums font-mono text-[11px]">
                  {a.sharpe != null ? (
                    <span className={a.sharpe >= 1.25 ? 'text-emerald-400' : a.sharpe >= 1.0 ? 'text-yellow-400' : 'text-gray-400'}>
                      {a.sharpe.toFixed(3)}
                    </span>
                  ) : (
                    <span className="text-gray-600">-</span>
                  )}
                </span>
                <span className="text-right tabular-nums font-mono text-[11px]">
                  {a.sc_value != null ? (
                    <span className={a.sc_value >= 5 ? 'text-emerald-400' : a.sc_value >= 3 ? 'text-yellow-400' : a.sc_value >= 1 ? 'text-gray-400' : 'text-rose-400'}>
                      {a.sc_value.toFixed(2)}
                    </span>
                  ) : (
                    <span className="text-gray-600">-</span>
                  )}
                </span>
                <span className="text-center text-gray-500 text-[10px]">{a.total_attempts}</span>
                <span className={`text-right text-[10px] font-medium ${STATUS_COLORS[a.status] || 'text-gray-400'}`}>
                  {STATUS_LABELS[a.status] || a.status}
                </span>
              </button>

              {/* Expanded state chain */}
              {expandedAlpha === a.name && (
                <div className="px-4 pb-2 pt-0.5 bg-white/[0.01] border-b border-white/[0.02]">
                  <div className="text-[9px] text-gray-600 mb-1.5">State Chain</div>
                  <div className="flex flex-wrap gap-1.5">
                    {a.state_chain.map((e, i) => (
                      <div
                        key={i}
                        className="px-2 py-0.5 rounded-md border border-white/[0.04] text-[9px] font-mono"
                        title={e.created_at}
                      >
                        <span className={STATUS_COLORS[e.event_type] || 'text-gray-400'}>{e.event_type}</span>
                        {e.sharpe != null && (
                          <span className="text-gray-500 ml-1">
                            S{'>'}{e.sharpe.toFixed(2)}
                          </span>
                        )}
                        {e.sc_value != null && (
                          <span className="text-gray-500 ml-1">
                            SC{'>'}{e.sc_value.toFixed(2)}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                  {a.first_generated_at && (
                    <div className="text-[9px] text-gray-600 mt-1.5">
                      First: {new Date(a.first_generated_at).toLocaleString()} · Last: {a.last_milestone_at ? new Date(a.last_milestone_at).toLocaleString() : '-'}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
