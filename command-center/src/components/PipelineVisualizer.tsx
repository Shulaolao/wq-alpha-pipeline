'use client';

import React from 'react';

const PHASES = [
  { id: 'orthogonality', label: 'Orthogonality', abbr: 'Ortho', icon: '⧉' },
  { id: 'generate', label: 'Generate', abbr: 'Gen', icon: '✦' },
  { id: 'quick_test', label: 'Quick', abbr: 'QTest', icon: '⚡' },
  { id: 'full_sim', label: 'Sim / IS', abbr: 'IS', icon: '▸' },
  { id: 'tune_is', label: 'Tune IS', abbr: 'Tune', icon: '⚙' },
  { id: 'sc_submit', label: 'SC Check', abbr: 'SC', icon: '◉' },
  { id: 'submit', label: 'Submit', abbr: 'Submit', icon: '⬆' },
];

const COLORS: Record<string, string> = {
  orthogonality: '#a1a1aa', generate: '#22d3ee', quick_test: '#fbbf24',
  full_sim: '#818cf8', tune_is: '#fb7185', sc_submit: '#f472b6', submit: '#34d399',
};

interface Props { phase: string }

// Responsive pipeline progress bar — integrated into header area
export default function PipelineVisualizer({ phase }: Props) {
  const activeIdx = PHASES.findIndex(p => p.id === phase);

  // SVG viewBox: 7 phases → 7 nodes + 6 segments
  // viewBox="0 0 500 64" gives room for labels
  return (
    <div className="w-full bg-zinc-900/60 border border-zinc-800/60 rounded-xl px-3 md:px-5 py-2 md:py-3">
      {/* Top row: phase label + compact SVG */}
      <div className="flex items-center justify-between mb-1.5 md:mb-2">
        <div className="flex items-center gap-2">
          <span className="text-indigo-400 text-[9px] font-semibold uppercase tracking-[0.12em] hidden sm:inline">
            Pipeline Stage
          </span>
          {activeIdx >= 0 && (
            <span className="text-[10px] md:text-[11px] text-indigo-300 font-mono">
              {PHASES[activeIdx].icon} {PHASES[activeIdx].label}
            </span>
          )}
        </div>
        {/* Mobile: show compact step indicator */}
        <span className="text-[10px] text-zinc-500 font-mono sm:hidden">
          {activeIdx >= 0 ? `${activeIdx + 1}/${PHASES.length}` : '0/7'}
        </span>
      </div>

      <div className="max-w-3xl mx-auto">
        <svg
          viewBox="0 0 500 64"
          className="w-full"
          preserveAspectRatio="xMidYMid meet"
        >
          <defs>
            <marker id="pvArr" markerWidth="3" markerHeight="2.5" refX="2.5" refY="1.25" orient="auto">
              <path d="M0,0 L3,1.25 L0,2.5Z" fill="rgba(255,255,255,0.1)" />
            </marker>
            <marker id="pvArrAct" markerWidth="3" markerHeight="2.5" refX="2.5" refY="1.25" orient="auto">
              <path d="M0,0 L3,1.25 L0,2.5Z" fill="rgba(129,140,248,0.5)" />
            </marker>
            <filter id="pvGlow">
              <feGaussianBlur stdDeviation="2" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>

          {/* Background connecting line */}
          <line x1={32} y1={24} x2={468} y2={24} stroke="rgba(255,255,255,0.04)" strokeWidth={1.2} />

          {/* Segments with arrows */}
          {[0, 1, 2, 3, 4, 5].map(i => {
            const a = 32 + i * 69.5;
            const b = 32 + (i + 1) * 69.5;
            const done = i < activeIdx;
            const active = i === activeIdx;
            return (
              <line
                key={i}
                x1={a} y1={24} x2={b} y2={24}
                stroke={done ? '#34d399' : active ? '#818cf8' : 'rgba(255,255,255,0.06)'}
                strokeWidth={done || active ? 1.8 : 0.8}
                strokeOpacity={done || active ? 0.8 : 0.4}
                markerEnd={done || active ? 'url(#pvArrAct)' : 'url(#pvArr)'}
              />
            );
          })}

          {/* Nodes */}
          {PHASES.map((p, i) => {
            const x = 32 + i * 69.5;
            const done = i < activeIdx;
            const active = i === activeIdx;
            const color = COLORS[p.id];
            const dim = 'rgba(113,113,122,0.35)';
            const r = active ? 12 : 10;

            return (
              <g key={p.id}>
                {/* Active glow */}
                {active && (
                  <circle cx={x} cy={24} r={r + 6} fill="none" stroke={`${color}30`}
                    strokeWidth={2} opacity={0.3} filter="url(#pvGlow)" />
                )}

                {/* Outer ring */}
                <circle cx={x} cy={24} r={r}
                  fill={done ? 'rgba(52,211,153,0.1)' : active ? `${color}18` : 'rgba(39,39,42,0.8)'}
                  stroke={done ? '#34d399' : active ? color : dim}
                  strokeWidth={active ? 2.5 : done ? 2 : 1.2}
                />

                {/* Inner dot */}
                <circle cx={x} cy={24} r={3.5}
                  fill={active ? `${color}15` : done ? 'rgba(52,211,153,0.08)' : 'rgba(39,39,42,0.9)'}
                />

                {/* Icon or check */}
                {done ? (
                  <text x={x} y={25} textAnchor="middle" dominantBaseline="central"
                    fill="#34d399" fontSize={14} fontWeight="bold">✓</text>
                ) : (
                  <text x={x} y={25} textAnchor="middle" dominantBaseline="central"
                    fill={active ? '#fff' : dim} fontSize={active ? 16 : 14}>
                    {p.icon}
                  </text>
                )}

                {/* Label above */}
                <text x={x} y={7} textAnchor="middle" dominantBaseline="central"
                  fill={active ? '#e0e7ff' : done ? '#34d399' : dim}
                  fontSize={10} fontFamily="'JetBrains Mono',monospace" fontWeight={active ? 'bold' : 400}>
                  {p.abbr}
                </text>

                {/* Small label below */}
                <text x={x} y={44} textAnchor="middle" dominantBaseline="central"
                  fill={active ? 'rgba(224,231,255,0.6)' : 'rgba(113,113,122,0.35)'}
                  fontSize={8} fontFamily="'JetBrains Mono',monospace">
                  {p.label}
                </text>
              </g>
            );
          })}

          {/* Play indicator (left of first node) */}
          {activeIdx >= 0 && (
            <text x={20} y={29} textAnchor="middle"
              fill="#818cf8" fontSize={14} fontFamily="monospace" filter="url(#pvGlow)">▶</text>
          )}
        </svg>
      </div>
    </div>
  );
}
