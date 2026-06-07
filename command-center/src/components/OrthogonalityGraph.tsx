'use client';

import { useMemo, useState } from 'react';

interface NodeData { id: string; expr: string; fields: string[]; field_count: number }
interface EdgeData { source: string; target: string; similarity: number; shared_fields: string[] }
interface OrthogonalityData {
  nodes: NodeData[]; edges: EdgeData[]; node_count: number; edge_count: number;
  sim_min?: number; sim_max?: number; sim_avg?: number;
}
interface Props { data: OrthogonalityData | null; loading?: boolean }

const FIELD_COLORS: Record<string, string> = {
  revenue: '#818cf8', close: '#34d399', volume: '#f59e0b',
  high: '#22d3ee', low: '#22d3ee', open: '#22d3ee',
  vwap: '#67e8f9', returns: '#f472b6', adv20: '#fb923c',
  cap: '#f472b6', debt: '#a78bfa', equity: '#c084fc',
  enterprise_value: '#e879f9', operating_income: '#f0abfc',
  ebitda: '#d8b4fe', cash: '#fbcfe8', sales: '#fecdd3',
};

const SIM_COLORS = ['#1e1b4b', '#312e81', '#4338ca', '#6366f1', '#818cf8', '#a5b4fc'];

function getSimColor(sim: number): string {
  const idx = Math.min(SIM_COLORS.length - 1, Math.floor(sim * SIM_COLORS.length));
  return SIM_COLORS[idx] || '#1e1b4b';
}

export default function OrthogonalityGraph({ data, loading }: Props) {
  const [showAll, setShowAll] = useState(false);

  const isEmpty = !data || data.nodes.length === 0;

  const sorted = useMemo(() => {
    if (isEmpty) return [];
    return [...data.nodes].sort(
      (a, b) => b.field_count - a.field_count || a.id.localeCompare(b.id)
    );
  }, [data, isEmpty]);

  const simMap = useMemo(() => {
    if (isEmpty) return new Map<string, number>();
    const m = new Map<string, number>();
    for (const e of data.edges) {
      m.set([e.source, e.target].sort().join('::'), e.similarity);
    }
    return m;
  }, [data, isEmpty]);

  const avgSim = useMemo(() => {
    if (!data || data.edges.length === 0) return 0;
    return data.edges.reduce((s, e) => s + e.similarity, 0) / data.edges.length;
  }, [data]);

  if (isEmpty || loading) {
    return (
      <div className="card p-2.5 md:p-4 animate-[fade-in_0.3s_ease-out]">
        <div className="section-header mb-1.5 md:mb-2">
          <span className="text-emerald-400 text-[10px] shrink-0">⧉</span>
          <h2 className="text-[10px] md:text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 shrink-0">Orthogonality</h2>
        </div>
        <div className="flex items-center justify-center rounded-lg bg-black/10" style={{ height: 160 }}>
          <div className="flex flex-col items-center gap-2">
            <div className="skeleton w-48 h-2" />
            <div className="skeleton w-32 h-2" />
            <div className="text-gray-600 text-[10px] mt-1">{loading ? 'Loading...' : 'No data'}</div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="card p-2.5 md:p-4 animate-[fade-in_0.3s_ease-out]">
      {/* Header */}
      <div className="section-header mb-2">
        <span className="text-emerald-400 text-[10px] shrink-0">⧉</span>
        <h2 className="text-[10px] md:text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 shrink-0">Orthogonality</h2>
        <span className="text-gray-600 font-normal text-[8px] md:text-[10px] truncate">
          {data.node_count}α · {data.edge_count}pairs
          <span className="ml-1 hidden sm:inline">avg {(avgSim * 100).toFixed(1)}%</span>
        </span>
      </div>

      {/* 相似度热力图 (SVG 实现) */}
      {sorted.length > 0 && (
        <div className="mb-2">
          <svg className="w-full" viewBox={`0 0 ${Math.max(sorted.length * 20 + 100, 200)} ${Math.max(sorted.length * 16 + 40, 180)}`} preserveAspectRatio="xMidYMid meet">
            {sorted.map((node, row) => (
              <g key={node.id}>
                {/* 行标签 */}
                <text
                  x={0} y={row * 16 + 10}
                  fill="#71717a" fontSize="7" fontFamily="JetBrains Mono, monospace"
                >
                  {node.id.length > 6 ? node.id.slice(0, 6) + '…' : node.id}
                </text>
                {/* 列标签（对角线下方） */}
                {row < sorted.length && (
                  <text
                    x={row * 16 + 10} y={sorted.length * 16 + 12}
                    fill="#71717a" fontSize="6" fontFamily="JetBrains Mono, monospace"
                    transform={`rotate(-45, ${row * 16 + 12}, ${sorted.length * 16 + 12})`}
                  />
                )}
                {/* 单元格 */}
                {Array.from({ length: row + 1 }, (_, col) => {
                  const id1 = sorted[row].id;
                  const id2 = sorted[col].id;
                  const key = [id1, id2].sort().join('::');
                  const sim = id1 === id2 ? 1 : (simMap.get(key) ?? 0);
                  const isSelf = id1 === id2;
                  return (
                    <rect
                      key={`${row}-${col}`}
                      x={col * 16 + 60} y={row * 16}
                      width={15} height={15} rx={1}
                      fill={isSelf ? '#312e81' : getSimColor(sim)}
                      opacity={isSelf ? 0.3 : Math.max(0.2, sim)}
                      stroke="#18181b" strokeWidth={0.5}
                    >
                      <title>
                        {isSelf
                          ? `${id1}\nFields: ${sorted.find(n => n.id === id1)?.fields.join(', ') || ''}`
                          : `${id1} ↔ ${id2}\nSimilarity: ${(sim * 100).toFixed(1)}%`}
                      </title>
                    </rect>
                  );
                })}
              </g>
            ))}
          </svg>
        </div>
      )}

      {/* Alpha details */}
      <div className={`space-y-px overflow-y-auto transition-all duration-200 ${
        showAll ? 'max-h-48' : 'max-h-24'
      }`}>
        {sorted.map(n => {
          const connected = data.edges.filter(e => e.source === n.id || e.target === n.id);
          const avg = connected.length > 0
            ? connected.reduce((s, e) => s + e.similarity, 0) / connected.length
            : 0;
          return (
            <div key={n.id} className="flex items-center gap-1 text-[8px] md:text-[10px] py-0.5 px-1 rounded hover:bg-white/[0.02] cursor-default">
              <span className="font-mono text-gray-400 w-14 md:w-20 truncate shrink-0">
                {n.id.length > 8 ? n.id.slice(0, 8) + '…' : n.id}
              </span>
              <span className="text-gray-600 w-4 md:w-6 text-right shrink-0">{n.field_count}</span>
              <div className="flex-1 flex flex-wrap gap-px min-w-0">
                {n.fields.slice(0, 6).map(f => (
                  <span key={f}
                    className="px-1 rounded-sm text-[6px] md:text-[8px] font-mono leading-tight"
                    style={{
                      backgroundColor: (FIELD_COLORS[f] || '#6b7280') + '18',
                      color: FIELD_COLORS[f] || '#6b7280'
                    }}
                  >{f}</span>
                ))}
                {n.fields.length > 6 && (
                  <span className="text-gray-700 text-[6px] md:text-[8px]">+{n.fields.length - 6}</span>
                )}
              </div>
              <span className="text-gray-700 w-8 md:w-10 text-right shrink-0 font-mono text-[8px] md:text-[10px]">
                {(avg * 100).toFixed(0)}%
              </span>
            </div>
          );
        })}
      </div>
      {sorted.length > 4 && (
        <button onClick={() => setShowAll(!showAll)}
          className="w-full mt-1 text-[8px] md:text-[9px] text-indigo-400/50 hover:text-indigo-400 transition-colors cursor-pointer">
          {showAll ? '▲ Less' : `▼ ${sorted.length} alphas`}
        </button>
      )}
    </div>
  );
}
