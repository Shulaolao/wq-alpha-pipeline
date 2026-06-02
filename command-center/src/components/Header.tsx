'use client';

import { useCallback } from 'react';

/* ── Types ─────────────────────────────────────────── */

type Status = 'running' | 'paused' | 'done' | 'idle';

export interface HeaderProps {
  status: Status;
  phase: string;
  activeCount: number;
  target: number;
  startedAt: string;
  duration?: string;
  batch?: string;
  refreshInterval?: number;
  onRefreshIntervalChange?: (ms: number) => void;
}

/* ── Sub-components ────────────────────────────────── */

function Logo() {
  return (
    <div className="flex items-center gap-1.5 md:gap-2 shrink-0">
      {/* WQ logomark — styled monogram */}
      <span className="flex h-7 w-7 md:h-8 md:w-8 items-center justify-center rounded-lg bg-gradient-to-br from-sky-500 to-indigo-600 text-[10px] md:text-xs font-bold tracking-tight text-white shadow-sm">
        WQ
      </span>
      <span className="hidden text-xs md:text-sm font-semibold tracking-tight text-zinc-100 sm:inline-block">
        Command Center
      </span>
    </div>
  );
}

function StatusDot({ status, label }: { status: Status; label?: boolean }) {
  const colors: Record<Status, string> = {
    running: 'bg-emerald-500 shadow-[0_0_6px_theme(colors.emerald.500/0.6)]',
    paused: 'bg-amber-400 shadow-[0_0_6px_theme(colors.amber.400/0.6)]',
    done: 'bg-zinc-500',
    idle: 'bg-zinc-500',
  };

  const labels: Record<Status, string> = {
    running: 'Running',
    paused: 'Paused',
    done: 'Done',
    idle: 'Idle',
  };

  return (
    <div className="flex items-center gap-1" title={labels[status]}>
      <span className={`inline-block h-2 w-2 md:h-2.5 md:w-2.5 rounded-full ${colors[status]}`} />
      {label !== false && (
        <span className="text-[10px] md:text-xs font-medium text-zinc-400">{labels[status]}</span>
      )}
    </div>
  );
}

function ActiveCount({ count, target, compact }: { count: number; target: number; compact?: boolean }) {
  const pct = target > 0 ? Math.min((count / target) * 100, 100) : 0;

  if (compact) {
    return (
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] font-semibold tabular-nums text-zinc-100 whitespace-nowrap">
          {count}<span className="font-normal text-zinc-500">/{target}</span>
        </span>
        <div className="h-1.5 w-16 overflow-hidden rounded-full bg-zinc-800">
          <div
            className="h-full rounded-full bg-gradient-to-r from-sky-500 to-indigo-500 transition-all duration-500 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-zinc-300">
          Active <span className="text-zinc-500">Alpha</span>
        </span>
        <span className="font-semibold tabular-nums text-zinc-100">
          {count}
          <span className="font-normal text-zinc-500">/{target}</span>
        </span>
      </div>
      <div className="h-1.5 w-28 overflow-hidden rounded-full bg-zinc-800">
        <div
          className="h-full rounded-full bg-gradient-to-r from-sky-500 to-indigo-500 transition-all duration-500 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function PhaseBadge({ phase }: { phase: string }) {
  if (!phase) return null;
  return (
    <span className="inline-flex items-center rounded-full border border-zinc-700/60 bg-zinc-800/60 px-1.5 md:px-2.5 py-0.5 text-[9px] md:text-[11px] font-medium tracking-wide text-zinc-300 backdrop-blur-sm whitespace-nowrap">
      {phase}
    </span>
  );
}

function RefreshSelect({
  value,
  onChange,
}: {
  value: number;
  onChange: (ms: number) => void;
}) {
  const options = [
    { label: '3s', value: 3000 },
    { label: '10s', value: 10000 },
    { label: '30s', value: 30000 },
  ];

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      onChange(Number(e.target.value));
    },
    [onChange],
  );

  return (
    <div className="flex items-center gap-1">
      <svg
        className="h-3 w-3 md:h-3.5 md:w-3.5 text-zinc-500 shrink-0"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
        />
      </svg>
      <select
        value={value}
        onChange={handleChange}
        className="appearance-none rounded-md border border-zinc-700 bg-zinc-800/80 px-1.5 md:px-2 py-0.5 md:py-1 text-[10px] md:text-[11px] font-medium text-zinc-300 outline-none ring-0 transition-colors hover:border-zinc-600 focus:border-zinc-500"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/* ── Main component ────────────────────────────────── */

export default function Header({
  status,
  phase,
  activeCount,
  target,
  startedAt,
  duration,
  batch,
  refreshInterval = 3000,
  onRefreshIntervalChange,
}: HeaderProps) {
  return (
    <header className="flex w-full items-center justify-between border-b border-zinc-800/80 bg-zinc-900/80 px-3 md:px-6 py-2 md:py-2.5 backdrop-blur-md gap-2">
      {/* Left: Logo */}
      <div className="flex items-center gap-2 md:gap-4 min-w-0">
        <Logo />

        {/* Desktop extras */}
        <div className="hidden md:flex items-center gap-3">
          <StatusDot status={status} />
          <PhaseBadge phase={phase} />
          {duration && (
            <span className="text-[11px] font-mono text-zinc-500" title="Elapsed time">
              ⏱ {duration}
            </span>
          )}
          {batch && (
            <span className="text-[11px] font-mono text-zinc-500" title="Batch progress">
              📦 Batch {batch}
            </span>
          )}
        </div>
        {startedAt && (
          <time
            className="hidden text-[11px] text-zinc-600 lg:block"
            dateTime={startedAt}
            title={`Started at ${startedAt}`}
          >
            {new Date(startedAt).toLocaleTimeString()}
          </time>
        )}
      </div>

      {/* Right: active count + refresh */}
      <div className="flex items-center gap-2 md:gap-5 shrink-0">
        {/* Active count — compact on mobile, full on desktop */}
        <div className="hidden sm:block">
          <ActiveCount count={activeCount} target={target} />
        </div>
        <div className="sm:hidden">
          <ActiveCount count={activeCount} target={target} compact />
        </div>

        {/* Refresh interval selector */}
        {onRefreshIntervalChange && (
          <RefreshSelect value={refreshInterval} onChange={onRefreshIntervalChange} />
        )}

        {/* Mobile-only status indicator */}
        <div className="flex items-center gap-1 md:hidden">
          <StatusDot status={status} label={false} />
          <PhaseBadge phase={phase} />
        </div>
      </div>
    </header>
  );
}