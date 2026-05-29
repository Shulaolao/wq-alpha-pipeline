'use client';

import { useEffect, useRef, useMemo } from 'react';
import type { LogEntry } from '@/types/dashboard';

interface ActivityLogProps {
  entries: LogEntry[];
}

const LEVEL_COLORS: Record<string, string> = {
  ERROR: '#fb7185',
  WARN: '#fbbf24',
  INFO: '#6366f1',
};

export default function ActivityLog({ entries }: ActivityLogProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const prevLength = useRef(0);

  useEffect(() => {
    if (entries.length > prevLength.current && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
    prevLength.current = entries.length;
  }, [entries.length]);

  const rendered = useMemo(() => entries.slice(-100), [entries]);

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500">
          Activity Log
        </h2>
        <span className="text-[10px] text-gray-600">{entries.length} entries</span>
      </div>
      <div
        ref={containerRef}
        className="bg-dark-900/80 rounded-lg border border-white/[0.03] h-56 overflow-y-auto font-mono text-[11px] leading-relaxed"
      >
        {rendered.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-600 text-xs">
            Waiting for pipeline activity...
          </div>
        ) : (
          rendered.map((entry, i) => {
            const level = (entry.level || 'INFO').toUpperCase();
            const color = LEVEL_COLORS[level] || '#6b7280';
            return (
              <div
                key={`${entry.time}-${i}`}
                className="flex gap-2 px-2.5 py-1 border-b border-white/[0.015] hover:bg-white/[0.02] transition-colors"
              >
                <span className="w-7 shrink-0 font-medium" style={{ color }}>{level.slice(0, 4)}</span>
                {entry.time && (
                  <span className="text-gray-600 w-16 shrink-0">{entry.time}</span>
                )}
                <span className="text-gray-300">{entry.msg || entry.raw || ''}</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}