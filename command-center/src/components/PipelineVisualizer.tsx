'use client';

import React from 'react';

const PIPELINE_PHASES = [
  { id: 'orthogonality', label: 'Orthogonality', icon: '⧉' },
  { id: 'generate', label: 'Generate', icon: '✦' },
  { id: 'full_sim', label: 'Sim / IS', icon: '▸' },
  { id: 'sc_submit', label: 'SC Check', icon: '◉' },
  { id: 'submit', label: 'Submit', icon: '⬆' },
];

interface PipelineVisualizerProps {
  phase: string;
  simProgress?: number | null;
}

export default function PipelineVisualizer({ phase, simProgress }: PipelineVisualizerProps) {
  const activeIdx = PIPELINE_PHASES.findIndex(p => p.id === phase);

  return (
    <div className="card p-4">
      <div className="flex items-center justify-center gap-1 md:gap-3">
        {PIPELINE_PHASES.map((p, i) => {
          const isDone = i < activeIdx;
          const isActive = i === activeIdx;
          return (
            <React.Fragment key={p.id}>
              {i > 0 && (
                <span className={`text-xs transition-colors ${isDone ? 'text-emerald-500' : 'text-gray-700'}`}>
                  →
                </span>
              )}
              <div
                className={`
                  relative px-3 py-2 rounded-lg text-center min-w-[60px] transition-all duration-300
                  ${isActive
                    ? 'bg-indigo-500/15 border border-indigo-500/30 shadow-lg shadow-indigo-500/10'
                    : isDone
                      ? 'bg-emerald-500/8 border border-emerald-500/15'
                      : 'opacity-40'
                  }
                `}
              >
                {isDone && (
                  <span className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-emerald-500 rounded-full 
                                   flex items-center justify-center text-[8px] text-white font-bold
                                   shadow-lg shadow-emerald-500/30">
                    ✓
                  </span>
                )}
                <div
                  className={`
                    w-6 h-6 rounded-full flex items-center justify-center text-xs mx-auto mb-1 transition-all
                    ${isActive
                      ? 'bg-gradient-to-br from-indigo-500 to-violet-500 shadow-lg shadow-indigo-500/30'
                      : isDone
                        ? 'bg-emerald-500/20'
                        : 'bg-dark-600'
                    }
                  `}
                >
                  <span className={isActive ? 'text-white' : isDone ? 'text-emerald-400' : 'text-gray-500'}>
                    {p.icon}
                  </span>
                </div>
                <div className={`text-[10px] font-medium transition-colors ${
                  isActive ? 'text-indigo-300' : isDone ? 'text-emerald-400' : 'text-gray-600'
                }`}>
                  {p.label}
                </div>
              </div>
            </React.Fragment>
          );
        })}
      </div>
      <div className="flex items-center justify-center gap-4 mt-2 text-[10px]">
        <span className="text-gray-600 font-mono" id="phaseElapsed">
          phase: {phase}
        </span>
        {phase === 'full_sim' && simProgress !== null && simProgress !== undefined && (
          <span className="text-indigo-400 font-mono">
            sim {Math.round(simProgress * 100)}%
          </span>
        )}
      </div>
    </div>
  );
}
