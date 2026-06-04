'use client';

import React from 'react';

const PHASES = [
  { id: 'orthogonality', label: '正交分析', abbr: 'Ortho', icon: '⧉', desc: '字段频率 + AST结构分析', color: '#a1a1ca' },
  { id: 'generate', label: '候选生成', abbr: 'Gen', icon: '✦', desc: 'v3.19 骨架进化', color: '#22d3ee' },
  { id: 'quick_test', label: 'Quick Test', abbr: 'QTest', icon: '⚡', desc: 'P1Y快速验证', color: '#fbbf24' },
  { id: 'full_sim', label: 'Full IS', abbr: 'IS', icon: '▸', desc: '5Y全量回测', color: '#818cf8' },
  { id: 'tune_is', label: '调参优化', abbr: 'Tune', icon: '⚙', desc: '网格搜索 + 动量', color: '#fb7185' },
  { id: 'sc_submit', label: 'SC提交', abbr: 'SC', icon: '◉', desc: 'SELF_CORR验证', color: '#f472b6' },
  { id: 'submit', label: '提交上线', abbr: '✓', icon: '⬆', desc: '提交至BRAIN', color: '#34d399' },
];

const STAGE_COLORS: Record<string, { bg: string; border: string; glow: string }> = {
  orthogonality: { bg: 'rgba(161,161,202,0.06)', border: 'rgba(161,161,202,0.25)', glow: 'rgba(161,161,202,0.4)' },
  generate: { bg: 'rgba(34,211,238,0.06)', border: 'rgba(34,211,238,0.25)', glow: 'rgba(34,211,238,0.4)' },
  quick_test: { bg: 'rgba(251,191,36,0.06)', border: 'rgba(251,191,36,0.25)', glow: 'rgba(251,191,36,0.4)' },
  full_sim: { bg: 'rgba(129,140,248,0.06)', border: 'rgba(129,140,248,0.25)', glow: 'rgba(129,140,248,0.4)' },
  tune_is: { bg: 'rgba(251,113,133,0.06)', border: 'rgba(251,113,133,0.25)', glow: 'rgba(251,113,133,0.4)' },
  sc_submit: { bg: 'rgba(244,114,182,0.06)', border: 'rgba(244,114,182,0.25)', glow: 'rgba(244,114,182,0.4)' },
  submit: { bg: 'rgba(52,211,153,0.06)', border: 'rgba(52,211,153,0.25)', glow: 'rgba(52,211,153,0.4)' },
};

interface Props { phase: string }

export default function PipelineVisualizer({ phase }: Props) {
  const activeIdx = PHASES.findIndex(p => p.id === phase);
  const progress = activeIdx >= 0 ? ((activeIdx + 1) / PHASES.length) * 100 : 0;

  return (
    <div className="relative w-full bg-gradient-to-b from-zinc-900/70 to-zinc-950/70 border border-zinc-800/50 rounded-xl px-3 md:px-5 py-2 md:py-3 overflow-hidden group">
      {/* Background shimmer */}
      <div className="absolute inset-0 opacity-[0.015] bg-[radial-gradient(ellipse_at_top,rgba(129,140,248,0.3)_0%,transparent_70%)]" />

      {/* Top row */}
      <div className="relative z-10 flex items-center justify-between mb-2 md:mb-3">
        <div className="flex items-center gap-2">
          <span className="text-indigo-400/60 text-[9px] font-semibold uppercase tracking-[0.16em] hidden sm:inline">
            Pipeline
          </span>
          {activeIdx >= 0 && (
            <span
              className="text-[10px] md:text-[11px] font-mono font-medium transition-all duration-500"
              style={{ color: PHASES[activeIdx].color }}
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
                background: `linear-gradient(90deg, ${PHASES[0].color}, ${PHASES[activeIdx >= 0 ? activeIdx : 0].color}, #34d399)`,
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
        <svg viewBox="0 0 560 80" className="w-full" preserveAspectRatio="xMidYMid meet">
          <defs>
            <marker id="pvArrD" markerWidth="4" markerHeight="3" refX="3" refY="1.5" orient="auto">
              <path d="M0,0 L4,1.5 L0,3Z" fill="rgba(255,255,255,0.05)" />
            </marker>
            <marker id="pvArrAct" markerWidth="4" markerHeight="3" refX="3" refY="1.5" orient="auto">
              <path d="M0,0 L4,1.5 L0,3Z" fill="rgba(129,140,248,0.7)" />
            </marker>
            <marker id="pvArrDone" markerWidth="4" markerHeight="3" refX="3" refY="1.5" orient="auto">
              <path d="M0,0 L4,1.5 L0,3Z" fill="rgba(52,211,153,0.7)" />
            </marker>
            <filter id="pvGlow">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            <filter id="pvGlowSoft">
              <feGaussianBlur stdDeviation="2" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            <filter id="pvGlowStrong">
              <feGaussianBlur stdDeviation="5" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <linearGradient id="pvActiveGrad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#818cf8" stopOpacity="0.6" />
              <stop offset="100%" stopColor="#818cf8" stopOpacity="0.15" />
            </linearGradient>
            {/* Per-phase glow filters */}
            {PHASES.map(p => (
              <filter id={`pvGlow_${p.id}`} key={p.id}>
                <feGaussianBlur stdDeviation="4" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
            ))}
          </defs>

          {/* Background track */}
          <line x1={40} y1={36} x2={520} y2={36}
            stroke="rgba(255,255,255,0.04)" strokeWidth={1.5} strokeLinecap="round"
          />

          {/* Segments */}
          {[0, 1, 2, 3, 4, 5].map(i => {
            const a = 40 + i * 76;
            const b = 40 + (i + 1) * 76;
            const done = i < activeIdx;
            const active = i === activeIdx;
            const segColor = done ? '#34d399' : active ? 'url(#pvActiveGrad)' : 'rgba(255,255,255,0.05)';
            const segWidth = done || active ? 2.5 : 1;
            const marker = done ? 'url(#pvArrDone)' : active ? 'url(#pvArrAct)' : 'url(#pvArrD)';

            return (
              <line
                key={i}
                x1={a} y1={36} x2={b} y2={36}
                stroke={segColor} strokeWidth={segWidth} strokeLinecap="round"
                markerEnd={marker}
                className="transition-all duration-700"
                style={{
                  filter: active ? 'url(#pvGlow)' : done ? 'url(#pvGlowSoft)' : undefined,
                }}
              />
            );
          })}

          {/* Nodes */}
          {PHASES.map((p, i) => {
            const x = 40 + i * 76;
            const done = i < activeIdx;
            const active = i === activeIdx;
            const future = i > activeIdx;
            const color = p.color;
            const stageColors = STAGE_COLORS[p.id as keyof typeof STAGE_COLORS];
            const r = active ? 16 : 13;

            return (
              <g key={p.id} className="transition-all duration-500">
                {/* Active glow rings - triple layer */}
                {active && (
                  <>
                    <circle cx={x} cy={36} r={r + 12}
                      fill={`url(#pvGlow_${p.id})`} stroke={`${color}15`} strokeWidth={1}
                      opacity={0.6}
                      style={{ animation: 'pulse 2s ease-in-out infinite' }}
                    />
                    <circle cx={x} cy={36} r={r + 7}
                      fill="none" stroke={`${color}30`} strokeWidth={2}
                      opacity={0.5} filter="url(#pvGlow)"
                    />
                    <circle cx={x} cy={36} r={r + 3}
                      fill="none" stroke={`${color}20`} strokeWidth={1.5}
                    />
                  </>
                )}

                {/* Done outer glow */}
                {done && (
                  <circle cx={x} cy={36} r={r + 4}
                    fill="none" stroke="rgba(52,211,153,0.12)" strokeWidth={1}
                    filter="url(#pvGlowSoft)"
                  />
                )}

                {/* Background halo for hover */}
                <circle cx={x} cy={36} r={r + 8} fill="transparent" />

                {/* Ring */}
                <circle cx={x} cy={36} r={r}
                  fill={
                    done ? 'rgba(52,211,153,0.1)' :
                    active ? stageColors.bg :
                    'rgba(24,24,42,0.6)'
                  }
                  stroke={
                    done ? 'rgba(52,211,153,0.6)' :
                    active ? color :
                    'rgba(84,84,104,0.25)'
                  }
                  strokeWidth={active ? 3 : done ? 2 : 1.2}
                  className="transition-all duration-500"
                  style={{
                    filter: active ? `url(#pvGlow_${p.id})` : undefined,
                  }}
                />

                {/* Inner dot */}
                <circle cx={x} cy={36} r={active ? 5 : 3.5}
                  fill={
                    active ? `${color}25` :
                    done ? 'rgba(52,211,153,0.08)' :
                    'rgba(24,24,42,0.9)'
                  }
                  className="transition-all duration-500"
                />

                {/* Icon / check */}
                {done ? (
                  <text x={x} y={37} textAnchor="middle" dominantBaseline="central"
                    fill="#34d399" fontSize={14} fontWeight="bold"
                    className="transition-all duration-300">✓</text>
                ) : (
                  <text x={x} y={37} textAnchor="middle" dominantBaseline="central"
                    fill={active ? '#fff' : future ? 'rgba(113,113,122,0.2)' : 'rgba(113,113,122,0.5)'}
                    fontSize={active ? 16 : 13}
                    className="transition-all duration-500">
                    {p.icon}
                  </text>
                )}

                {/* Label above - phase name */}
                <text x={x} y={16} textAnchor="middle" dominantBaseline="central"
                  fill={
                    active ? '#e0e7ff' :
                    done ? 'rgba(52,211,153,0.6)' :
                    'rgba(113,113,122,0.25)'
                  }
                  fontSize={active ? 10 : 8}
                  fontFamily="'JetBrains Mono',monospace"
                  fontWeight={active ? 700 : 500}
                  className="transition-all duration-500"
                  style={{
                    paintOrder: 'stroke',
                    stroke: active ? '#08080e' : 'transparent',
                    strokeWidth: 0.3,
                  }}
                >
                  {p.abbr}
                </text>

                {/* Sub-label - full name */}
                <text x={x} y={52} textAnchor="middle" dominantBaseline="central"
                  fill={
                    active ? `${color}99` :
                    done ? 'rgba(113,113,122,0.3)' :
                    'rgba(113,113,122,0.15)'
                  }
                  fontSize={7}
                  fontFamily="'JetBrains Mono',monospace"
                  className="transition-all duration-500"
                >
                  {p.label}
                </text>

                {/* Status indicator */}
                {done && (
                  <circle cx={x + r - 2} cy={36 - r + 2} r={2.5}
                    fill="#34d399" stroke="#08080e" strokeWidth={0.8}
                  />
                )}
                {active && (
                  <circle cx={x + r - 2} cy={36 - r + 2} r={2.5}
                    fill={color} stroke="#08080e" strokeWidth={0.8}
                  />
                )}

                {/* Tooltip */}
                <circle cx={x} cy={36} r={r + 2} fill="transparent">
                  <title>{p.desc}</title>
                </circle>
              </g>
            );
          })}

          {/* Play indicator */}
          {activeIdx >= 0 && (
            <text x={24} y={40} textAnchor="middle"
              fill="rgba(129,140,248,0.6)" fontSize={10}
              fontFamily="monospace"
              className="transition-all duration-700">▶</text>
          )}

          {/* Progress bar fill */}
          {activeIdx >= 0 && (
            <>
              <rect x={40} y={56} width={76 * activeIdx} height={2}
                rx={1} fill="rgba(52,211,153,0.15)"
                className="transition-all duration-700"
              />
              <rect x={40 + 76 * activeIdx} y={56} width={76 * 0.3} height={2}
                rx={1} fill="#34d399" opacity={0.3}
                className="transition-all duration-300"
              />
            </>
          )}
        </svg>
      </div>
    </div>
  );
}
