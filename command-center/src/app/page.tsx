'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import type { PipelineStatus } from '@/types/dashboard';
import type { HistoryEvent, AlphaSummary } from '@/services/api';
import { fetchStatus, fetchHistory, fetchOrthogonality, fetchCompleteAlphas } from '@/services/api';
import Header from '@/components/Header';
import PipelineVisualizer from '@/components/PipelineVisualizer';
import WorkflowGraph from '@/components/WorkflowGraph';
import PipelineStats from '@/components/PipelineStats';
import CandidateCard from '@/components/CandidateCard';
import ActivityLog from '@/components/ActivityLog';
import ActiveAlphas from '@/components/ActiveAlphas';
import FieldHeatmap from '@/components/FieldHeatmap';
import OrthogonalityGraph from '@/components/OrthogonalityGraph';
import Timeline from '@/components/Timeline';
import AlphaCompleteList from '@/components/AlphaCompleteList';
import PerformanceMonitor from '@/components/PerformanceMonitor';
import AlphaQuality from '@/components/AlphaQuality';

export default function DashboardPage() {
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [history, setHistory] = useState<HistoryEvent[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [orthData, setOrthData] = useState<{ nodes: any[]; edges: any[]; node_count: number; edge_count: number } | null>(null);
  const [completeAlphas, setCompleteAlphas] = useState<AlphaSummary[]>([]);
  const [completeAlphasTotal, setCompleteAlphasTotal] = useState(0);
  const [refreshMs, setRefreshMs] = useState(10000);
  const [errors, setErrors] = useState<string[]>([]);
  const phaseStartRef = useRef(Date.now());

  const loadData = useCallback(async () => {
    try {
      const [s, h, o, c] = await Promise.all([
        fetchStatus(),
        fetchHistory(),
        fetchOrthogonality(),
        fetchCompleteAlphas(),
      ]);
      setStatus(s);
      setHistory(h.events || []);
      setHistoryTotal(h.total || 0);
      setOrthData(o);
      setCompleteAlphas(c.alphas || []);
      setCompleteAlphasTotal(c.total || 0);
      if (s.errors?.length) setErrors(s.errors.slice(-3));
    } catch (err) {
      console.error('Poll failed:', err);
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadData();
  }, [loadData]);

  // Polling
  useEffect(() => {
    const timer = setInterval(loadData, refreshMs);
    return () => clearInterval(timer);
  }, [refreshMs, loadData]);

  // Phase change detection
  useEffect(() => {
    if (status?.phase) {
      phaseStartRef.current = Date.now();
    }
  }, [status?.phase]);

  return (
    <div className="max-w-7xl mx-auto p-3 md:p-5 space-y-4">
      {/* Header */}
      <Header
        status={(status?.status as 'running' | 'paused' | 'done' | 'idle') || 'idle'}
        phase={status?.phase || 'init'}
        activeCount={status?.active_count ?? 0}
        target={status?.target ?? 20}
        startedAt={status?.started_at || ''}
        duration={status?.duration || undefined}
        batch={`${status?.batch_index ?? 0}/${status?.batch_total ?? 0}`}
        system={status?.system ?? null}
        refreshInterval={refreshMs}
        onRefreshIntervalChange={setRefreshMs}
      />

      {/* Pipeline Visualizer — linear progress bar (always visible at top) */}
      <PipelineVisualizer phase={status?.phase || 'init'} />

      {/* WorkflowGraph — collapsible, shows rectangular loop when expanded */}
      <WorkflowGraph
        phase={status?.phase || 'init'}
        activeCount={status?.active_count}
        target={status?.target}
        batchIndex={status?.batch_index}
        batchTotal={status?.batch_total}
      />

      <div className="grid grid-cols-1 lg:grid-cols-7 gap-4">
        {/* LEFT: 4/7 */}
        <div className="lg:col-span-4 space-y-4">
          {/* Candidate Card */}
          <CandidateCard
            candidate={status?.current_candidate ?? null}
            batchIndex={status?.batch_index}
            batchTotal={status?.batch_total}
          />

          {/* Alpha Quality — 插入在 CandidateCard 和 ActivityLog 之间 */}
          <AlphaQuality
            alphas={(status?.actives || []).map((a: any) => ({
              id: a.id || a.name || 'unknown',
              expr: a.expr || '',
              sharpe: a.sharpe ?? undefined,
              fitness: a.fitness ?? undefined,
              sc_value: a.sc_value ?? undefined,
            }))}
            total={status?.active_count ?? 0}
            target={status?.target ?? 20}
          />

          {/* Activity Log */}
          <ActivityLog entries={status?.log || []} />

          {/* Active Alphas */}
          <ActiveAlphas
            alphas={(status?.actives || []).map((a: any) => ({
              id: a.id || a.name || 'unknown',
              expr: a.expr || '',
              sharpe: a.sharpe ?? undefined,
              fitness: a.fitness ?? undefined,
            }))}
            total={status?.active_count}
            target={status?.target}
          />
        </div>

        {/* RIGHT: 3/7 */}
        <div className="lg:col-span-3 space-y-4">
          {/* Pipeline Stats — now with failure counters */}
          <PipelineStats
            generated={status?.candidates_generated ?? 0}
            isPassed={status?.candidates_passed_is ?? 0}
            isFail={status?.candidates_is_fail ?? 0}
            scPassed={status?.candidates_passed_sc ?? 0}
            scFail={status?.candidates_sc_fail ?? 0}
            submitted={status?.candidates_submitted ?? 0}
            failed={status?.candidates_failed ?? 0}
            iterations={status?.iterations ?? 0}
            lastUpdated={status?.last_updated || ''}
            duration={status?.duration ?? undefined}
          />

          {/* Performance Monitor — 新：系统性能监控 */}
          <PerformanceMonitor stats={status?.system ?? null} />

          {/* Orthogonality Graph */}
          <OrthogonalityGraph data={orthData} />

          {/* Errors Panel */}
          {errors.length > 0 && (
            <div className="card p-4 border-red-500/10">
              <div className="flex items-center justify-between mb-2">
                <h2 className="text-[11px] font-semibold text-red-400 flex items-center gap-1.5">
                  <span>⚠</span> Errors
                  <span className="bg-red-500/15 text-red-400 text-[9px] px-1.5 py-0.5 rounded-full ml-1">
                    {errors.length}
                  </span>
                </h2>
              </div>
              <div className="space-y-1">
                {errors.map((err, i) => (
                  <div key={i} className="text-xs text-red-400/80 font-mono">✖ {err}</div>
                ))}
              </div>
            </div>
          )}

          {/* Field Usage Chart */}
          <FieldHeatmap data={status?.field_chart || []} />

          {/* Timeline */}
          <Timeline events={history} total={historyTotal} />
        </div>
      </div>

      {/* Alpha Complete List — full-width at bottom */}
      <AlphaCompleteList alphas={completeAlphas} total={completeAlphasTotal} />
    </div>
  );
}
