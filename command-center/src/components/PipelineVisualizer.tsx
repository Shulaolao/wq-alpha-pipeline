'use client';

import React from 'react';

const PIPELINE_PHASES = [
  { id: 'orthogonality', label: 'Orthogonality', icon: '⧉' },
  { id: 'generate', label: 'Generate', icon: '✦' },
  { id: 'quick_test', label: 'Quick', icon: '⚡' },
  { id: 'full_sim', label: 'Sim / IS', icon: '▸' },
  { id: 'tune_is', label: 'Tune IS', icon: '⚙' },
  { id: 'sc_submit', label: 'SC Check', icon: '◉' },
  { id: 'submit', label: 'Submit', icon: '⬆' },
];

const PHASE_COLORS: Record<string, string> = {
  orthogonality: 'from-zinc-500 to-zinc-400',
  generate: 'from-cyan-500 to-blue-500',
  quick_test: 'from-amber-500 to-yellow-500',
  full_sim: 'from-indigo-500 to-violet-500',
  tune_is: 'from-orange-500 to-red-500',
  sc_submit: 'from-rose-500 to-pink-500',
  submit: 'from-emerald-500 to-teal-500',
};

interface PipelineVisualizerProps {
  phase: string;
  simProgress?: number | null;
}

export default function PipelineVisualizer({ phase, simProgress }: PipelineVisualizerProps) {
  const activeIdx = PIPELINE_PHASES.findIndex(p => p.id === phase);
  const isSimPhase = phase === 'quick_test' || phase === 'full_sim' || phase === 'tune_is';

  return (
    <div className="card p-4 md:p-5">
      <div className="flex items-center justify-center gap-0.5 md:gap-2 overflow-x-auto pb-1">
        {PIPELINE_PHASES.map((p, i) => {
          const isDone = i < activeIdx;
          const isActive = i === activeIdx;
          const color = PHASE_COLORS[p.id] || 'from-zinc-500 to-zinc-400';

          return (
            <React.Fragment key={p.id}>
              {/* Connector line */}
              {i > 0 && (
                <span
                  className={`hidden sm:block text-[10px] transition-all duration-500 ${
                    isDone ? 'text-emerald-500/60' : isActive ? 'text-indigo-400/40' : 'text-zinc-750'
                  }`}
                >
                  ┄
                </span>
              )}

              {/* Phase node */}
              <div
                className={`
                  relative flex flex-col items-center px-2 py-2.5 rounded-xl min-w-[48px] md:min-w-[64px]
                  transition-all duration-500
                  ${isActive
                    ? 'scale-105'
                    : isDone
                      ? 'opacity-90'
                      : 'opacity-35 grayscale'
                  }
                `}
              >
                {/* Icon circle */}
                <div
                  className={`
                    relative flex items-center justify-center
                    w-7 h-7 md:w-8 md:h-8 rounded-full
                    transition-all duration-500
                    ${isActive
                      ? `bg-gradient-to-br ${color} shadow-lg`
                      : isDone
                        ? 'bg-emerald-500/15 ring-1 ring-emerald-500/30'
                        : 'bg-zinc-800/60 ring-1 ring-zinc-700/40'
                    }
                  `}
                >
                  {/* Checkmark for done */}
                  {isDone ? (
                    <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <span className={`text-xs md:text-sm ${isActive ? 'text-white' : 'text-zinc-500'}`}>
                      {p.icon}
                    </span>
                  )}

                  {/* Pulse ring for active */}
                  {isActive && (
                    <span className="absolute inset-0 rounded-full animate-ping opacity-20 bg-indigo-400" />
                  )}

                  {/* SIM progress ring segment */}
                  {isActive && isSimPhase && simProgress != null && simProgress > 0 && (
                    <svg className="absolute inset-0 w-full h-full -rotate-90" viewBox="0 0 32 32">
                      <circle
                        cx="16" cy="16" r="14"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeDasharray={`${Math.PI * 28 * simProgress} ${Math.PI * 28 * (1 - simProgress)}`}
                        className="text-white/40"
                        strokeLinecap="round"
                      />
                    </svg>
                  )}
                </div>

                {/* Label */}
                <div
                  className={`
                    text-[9px] md:text-[10px] font-medium mt-1.5 whitespace-nowrap
                    transition-colors duration-300
                    ${isActive ? 'text-indigo-300' : isDone ? 'text-emerald-400' : 'text-zinc-600'}
                  `}
                >
                  {p.label}
                </div>
              </div>
            </React.Fragment>
          );
        })}
      </div>

      {/* Bottom status bar */}
      <div className="flex items-center justify-center gap-3 mt-1 pt-2 border-t border-white/[0.04] text-[10px] font-mono">
        <span className="text-zinc-600">
          phase: <span className="text-zinc-400">{phase}</span>
        </span>
        {isSimPhase && simProgress != null && simProgress !== undefined && (
          <>
            <span className="text-zinc-600">|</span>
            <span className="text-indigo-400">
              sim {Math.round(simProgress * 100)}%
            </span>
            {simProgress > 0 && (
              <span className="text-zinc-600">
                {Array.from({ length: 10 }, (_, i) =>
                  i / 10 < simProgress ? '█' : '░'
                ).join('')}
              </span>
            )}
          </>
        )}
      </div>
    </div>
  );
}