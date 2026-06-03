'use client';

import React from 'react';

const PHASES = [
  { id: 'orthogonality', label: '正交分析', abbr: 'Ortho', icon: '⧉', desc: '字段频率 + AST结构分析' },
  { id: 'generate', label: '候选生成', abbr: 'Gen', icon: '✦', desc: 'v3.19 骨架进化' },
  { id: 'quick_test', label: 'Quick Test', abbr: 'QTest', icon: '⚡', desc: 'P1Y快速验证' },
  { id: 'full_sim', label: 'Full IS', abbr: 'IS', icon: '▸', desc: '5Y全量回测' },
  { id: 'tune_is', label: '调参优化', abbr: 'Tune', icon: '⚙', desc: '网格搜索 + 动量' },
  { id: 'sc_submit', label: 'SC提交', abbr: 'SC', icon: '◉', desc: 'SELF_CORR验证' },
  { id: 'submit', label: '提交上线', abbr: '✓', icon: '⬆', desc: '提交至BRAIN' },
];

const COLORS: Record<string, string> = {
  orthogonality: '#a1a1aa',
  generate: '#22d3ee',
  quick_test: '#fbbf24',
  full_sim: '#818cf8',
  tune_is: '#fb7185',
  sc_submit: '#f472b6',
  submit: '#34d399',
};

interface Props { phase: string }

export default function PipelineVisualizer({ phase }: Props) {
  const activeIdx = PHASES.findIndex(p => p.id === phase);
  const progress = activeIdx >= 0 ? ((activeIdx + 1) / PHASES.length) * 100 : 0;

  return (
    <div className="relative w-full bg-gradient-to-b from-zinc-900/70 to-zinc-950/70 border border-zinc-800/50 rounded-xl px-3 md:px-5 py-2 md:py-3 overflow-hidden">
      {/* Background shimmer */}
      <div className="absolute inset-0 opacity-[0.015] bg-[radial-gradient(ellipse_at_top,rgba(129,140,248,0.3)_0%,transparent_70%)]" />

      {/* Top row */}
      <div className="relative z-10 flex items-center justify-between mb-1.5 md:mb-2">
        <div className="flex items-center gap-2">
          <span className="text-indigo-400/60 text-[9px] font-semibold uppercase tracking-[0.16em] hidden sm:inline">
            Pipeline
          </span>
          {activeIdx >= 0 && (
            <span
              className="text-[10px] md:text-[11px] font-mono font-medium transition-all duration-500"
              style={{ color: COLORS[PHASES[activeIdx].id] || '#818cf8' }}
            >
              <span className="mr-1">{PHASES[activeIdx].icon}</span>
              {PHASES[activeIdx].label}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[9px] font-mono text-zinc-600 tabular-nums hidden sm:inline">
            {activeIdx >= 0 ? `${activeIdx + 1}/${PHASES.length}` : '0/7'}
          </span>
          <div className="h-1 w-16 bg-zinc-800 rounded-full overflow-hidden hidden sm:block">
            <div
              className="h-full rounded-full transition-all duration-700 ease-out"
              style={{
                width: `${progress}%`,
                background: 'linear-gradient(90deg, #6366f1, #818cf8, #34d399)',
              }}
            />
          </div>
          <span className="text-[9px] text-zinc-600 font-mono sm:hidden">
            {activeIdx >= 0 ? `${activeIdx + 1}/${PHASES.length}` : '0/7'}
          </span>
        </div>
      </div>

      {/* SVG Pipeline */}
      <div className="relative max-w-3xl mx-auto">
        <svg viewBox="0 0 500 64" className="w-full" preserveAspectRatio="xMidYMid meet">
          <defs>
            <marker id="pvArrD" markerWidth="3" markerHeight="2.5" refX="2.5" refY="1.25" orient="auto">
              <path d="M0,0 L3,1.25 L0,2.5Z" fill="rgba(255,255,255,0.06)" />
            </marker>
            <marker id="pvArrAct" markerWidth="3" markerHeight="2.5" refX="2.5" refY="1.25" orient="auto">
              <path d="M0,0 L3,1.25 L0,2.5Z" fill="rgba(129,140,248,0.6)" />
            </marker>
            <marker id="pvArrDone" markerWidth="3" markerHeight="2.5" refX="2.5" refY="1.25" orient="auto">
              <path d="M0,0 L3,1.25 L0,2.5Z" fill="rgba(52,211,153,0.6)" />
            </marker>
            <filter id="pvGlow">
              <feGaussianBlur stdDeviation="2.5" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            <filter id="pvGlowSoft">
              <feGaussianBlur stdDeviation="1.5" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            <linearGradient id="pvActiveGrad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#818cf8" stopOpacity="0.6" />
              <stop offset="100%" stopColor="#818cf8" stopOpacity="0.15" />
            </linearGradient>
          </defs>

          {/* Background track */}
          <line x1={32} y1={24} x2={468} y2={24}
            stroke="rgba(255,255,255,0.03)" strokeWidth={1.2} strokeLinecap="round"
          />

          {/* Segments */}
          {[0, 1, 2, 3, 4, 5].map(i => {
            const a = 32 + i * 69.5;
            const b = 32 + (i + 1) * 69.5;
            const done = i < activeIdx;
            const active = i === activeIdx;
            const segColor = done ? '#34d399' : active ? 'url(#pvActiveGrad)' : 'rgba(255,255,255,0.04)';
            const segWidth = done || active ? 2 : 0.8;
            const marker = done ? 'url(#pvArrDone)' : active ? 'url(#pvArrAct)' : 'url(#pvArrD)';

            return (
              <line
                key={i}
                x1={a} y1={24} x2={b} y2={24}
                stroke={segColor} strokeWidth={segWidth} strokeLinecap="round"
                markerEnd={marker}
                className="transition-all duration-700"
              />
            );
          })}

          {/* Nodes */}
          {PHASES.map((p, i) => {
            const x = 32 + i * 69.5;
            const done = i < activeIdx;
            const active = i === activeIdx;
            const future = i > activeIdx;
            const color = COLORS[p.id];
            const r = active ? 13 : 11;

            return (
              <g key={p.id} className="transition-all duration-500">
                {/* Active glow rings */}
                {active && (
                  <>
                    <circle cx={x} cy={24} r={r + 8}
                      fill="none" stroke={`${color}25`} strokeWidth={2}
                      opacity={0.4} filter="url(#pvGlow)"
                    />
                    <circle cx={x} cy={24} r={r + 4}
                      fill="none" stroke={`${color}15`} strokeWidth={1.5} opacity={0.6}
                    />
                  </>
                )}

                {/* Done outer glow */}
                {done && (
                  <circle cx={x} cy={24} r={r + 3}
                    fill="none" stroke="rgba(52,211,153,0.15)" strokeWidth={1}
                    filter="url(#pvGlowSoft)"
                  />
                )}

                {/* Ring */}
                <circle cx={x} cy={24} r={r}
                  fill={
                    done ? 'rgba(52,211,153,0.12)' :
                    active ? `${color}15` :
                    future ? 'rgba(39,39,42,0.5)' :
                    'rgba(39,39,42,0.8)'
                  }
                  stroke={
                    done ? '#34d399' :
                    active ? color :
                    future ? 'rgba(113,113,122,0.2)' :
                    'rgba(113,113,122,0.35)'
                  }
                  strokeWidth={active ? 2.5 : done ? 2 : 1.2}
                />

                {/* Inner dot */}
                <circle cx={x} cy={24} r={4}
                  fill={
                    active ? `${color}20` :
                    done ? 'rgba(52,211,153,0.1)' :
                    'rgba(39,39,42,0.9)'
                  }
                />

                {/* Icon/check */}
                {done ? (
                  <text x={x} y={25} textAnchor="middle" dominantBaseline="central"
                    fill="#34d399" fontSize={15} fontWeight="bold"
                    className="transition-all duration-300">✓</text>
                ) : (
                  <text x={x} y={25} textAnchor="middle" dominantBaseline="central"
                    fill={active ? '#fff' : future ? 'rgba(113,113,122,0.25)' : 'rgba(113,113,122,0.5)'}
                    fontSize={active ? 17 : 14}
                    className="transition-all duration-300">
                    {p.icon}
                  </text>
                )}

                {/* Label above */}
                <text x={x} y={6} textAnchor="middle" dominantBaseline="central"
                  fill={
                    active ? '#e0e7ff' :
                    done ? '#34d399' :
                    future ? 'rgba(113,113,122,0.2)' :
                    'rgba(113,113,122,0.4)'
                  }
                  fontSize={10}
                  fontFamily="'JetBrains Mono',monospace"
                  fontWeight={active ? 700 : 500}
                  className="transition-all duration-500"
                >
                  {p.abbr}
                </text>

                {/* Label below */}
                <text x={x} y={45} textAnchor="middle" dominantBaseline="central"
                  fill={
                    active ? 'rgba(224,231,255,0.5)' :
                    future ? 'rgba(113,113,122,0.15)' :
                    'rgba(113,113,122,0.3)'
                  }
                  fontSize={7.5}
                  fontFamily="'JetBrains Mono',monospace"
                  className="transition-all duration-500"
                >
                  {p.label}
                </text>

                {/* Tooltip */}
                <circle cx={x} cy={24} r={r + 4} fill="transparent">
                  <title>{p.desc}</title>
                </circle>
              </g>
            );
          })}

          {/* Play indicator */}
          {activeIdx >= 0 && (
            <text x={18} y={28} textAnchor="middle"
              fill="rgba(129,140,248,0.7)" fontSize={12}
              fontFamily="monospace" filter="url(#pvGlow)"
              className="transition-all duration-700">▶</text>
          )}
        </svg>
      </div>
    </div>
  );
}
