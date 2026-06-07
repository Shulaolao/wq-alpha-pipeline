'use client';

import { useEffect, useState } from 'react';

interface SystemStats {
  cpu_percent: number;
  memory_percent: number;
  memory_used_gb: number;
  memory_total_gb: number;
}

interface PerformanceMonitorProps {
  stats: SystemStats | null;
}

const CPU_COLORS = ['#22d3ee', '#67e8f9', '#3b82f6', '#1d4ed8'];
const MEM_COLORS = ['#34d399', '#10b981', '#059669', '#047857'];

export default function PerformanceMonitor({ stats }: PerformanceMonitorProps) {
  const [cpuHistory, setCpuHistory] = useState<number[]>(Array(20).fill(0));
  const [memHistory, setMemHistory] = useState<number[]>(Array(20).fill(0));

  useEffect(() => {
    if (!stats) return;
    setCpuHistory(prev => [...prev.slice(1), stats.cpu_percent]);
    setMemHistory(prev => [...prev.slice(1), stats.memory_percent]);
  }, [stats]);

  const isEmpty = !stats;

  const renderSparkline = (data: number[], color: string, height = 32) => {
    const max = 100;
    const points = data.map((val, i) => {
      const x = (i / (data.length - 1)) * 100;
      const y = 100 - (val / max) * 100;
      return `${x},${y}`;
    }).join(' ');

    return (
      <svg className="w-full h-8" viewBox="0 0 100 100" preserveAspectRatio="none">
        <polyline
          fill="none"
          stroke={color}
          strokeWidth="2"
          points={points}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <linearGradient id={`grad-${color}`} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={color} stopOpacity="0.2" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
        <polygon
          fill={`url(#grad-${color})`}
          points={`0,100 ${points} 100,100`}
        />
      </svg>
    );
  };

  return (
    <div className="card p-3 md:p-4 animate-[fade-in_0.3s_ease-out]">
      <div className="section-header mb-2">
        <span className="text-cyan-400 text-[10px] shrink-0">⚡</span>
        <h2 className="text-[10px] md:text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 shrink-0">
          Performance
        </h2>
      </div>

      {isEmpty ? (
        <div className="h-28 md:h-32 flex items-center justify-center text-gray-600 text-[10px] bg-black/10 rounded-lg">
          No system stats available
        </div>
      ) : (
        <div className="space-y-3">
          {/* CPU */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-[9px] text-cyan-400 font-mono">CPU</span>
                <span className="text-[11px] font-semibold text-gray-200">{stats.cpu_percent.toFixed(1)}%</span>
              </div>
              <span className="text-[8px] text-gray-600 font-mono">
                {stats.cpu_percent < 50 ? 'Normal' : stats.cpu_percent < 80 ? 'Elevated' : 'High'}
              </span>
            </div>
            {renderSparkline(cpuHistory, '#22d3ee', 28)}
          </div>

          {/* Memory */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-[9px] text-emerald-400 font-mono">MEM</span>
                <span className="text-[11px] font-semibold text-gray-200">{stats.memory_percent.toFixed(1)}%</span>
              </div>
              <span className="text-[8px] text-gray-600 font-mono">
                {stats.memory_used_gb.toFixed(1)} / {stats.memory_total_gb.toFixed(1)} GB
              </span>
            </div>
            {renderSparkline(memHistory, '#34d399', 28)}
          </div>

          {/* Memory Bar */}
          <div className="space-y-1">
            <div className="flex items-center justify-between text-[9px] text-gray-600">
              <span>Memory</span>
              <span>{((stats.memory_used_gb / stats.memory_total_gb) * 100).toFixed(0)}%</span>
            </div>
            <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400 transition-all duration-500"
                style={{ width: `${(stats.memory_used_gb / stats.memory_total_gb) * 100}%` }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
