'use client';

import { useRef, useState, useEffect } from 'react';

interface WorkflowGraphProps {
  phase: string;
  activeCount?: number;
  target?: number;
  batchIndex?: number;
  batchTotal?: number;
}

interface WorkflowNode {
  id: string;
  label: string;
  subtitle?: string;
  type: 'phase' | 'decision' | 'action' | 'end';
}

const NODES: WorkflowNode[] = [
  { id: 'org_ortho', label: '正交分析', subtitle: '字段频率 + AST', type: 'phase' },
  { id: 'dec_active20', label: '≥20 ACTIVE?', type: 'decision' },
  { id: 'done', label: '🏆 完成', subtitle: '20 ACTIVE', type: 'end' },
  { id: 'org_gen', label: '候选生成', subtitle: 'v3.19 骨架进化', type: 'phase' },
  { id: 'dec_mult', label: 'MULT枯竭?', subtitle: '≥50%失败', type: 'decision' },
  { id: 'act_phase0', label: 'Phase 0', subtitle: 'MULT', type: 'action' },
  { id: 'act_phase1', label: 'Phase 1', subtitle: 'DIRECT_RANK', type: 'action' },
  { id: 'act_phase2', label: 'Phase 2', subtitle: '混合', type: 'action' },
  { id: 'act_dedup', label: '去重', subtitle: '最优权重', type: 'action' },
  { id: 'act_sd_score', label: 'sd_score', subtitle: '拓扑距离加权', type: 'action' },
  { id: 'act_intra_div', label: '多样性保证', subtitle: '7种骨架各≥1', type: 'action' },
  { id: 'act_topn', label: 'Top-N', type: 'action' },
  { id: 'org_quick_test', label: 'Quick Test', subtitle: 'P1Y', type: 'phase' },
  { id: 'dec_s', label: 'Sharpe=?', type: 'decision' },
  { id: 'act_skip', label: '跳过', subtitle: 'S=None', type: 'action' },
  { id: 'act_fail', label: '丢弃', subtitle: 'S<1.0', type: 'action' },
  { id: 'act_pass_quick', label: '通过', subtitle: 'S≥1.0', type: 'action' },
  { id: 'org_full_is', label: 'Full IS', subtitle: '5Y回测', type: 'phase' },
  { id: 'act_adaptive', label: '轮询', subtitle: '15→120s', type: 'action' },
  { id: 'dec_is', label: 'IS结果?', type: 'decision' },
  { id: 'act_optimize', label: '优化', subtitle: '网格搜索', type: 'action' },
  { id: 'act_tune', label: '调参', subtitle: '权重+动量', type: 'action' },
  { id: 'dec_tune_ok', label: '调参成功?', type: 'decision' },
  { id: 'act_discard', label: '✖ 丢弃', subtitle: '飞书⚠️', type: 'action' },
  { id: 'org_sc', label: 'SC提交', subtitle: 'SELF_CORR', type: 'phase' },
  { id: 'dec_sc', label: 'SC<0.90?', type: 'decision' },
  { id: 'act_submit', label: '✅ 提交', subtitle: '飞书🎉', type: 'action' },
  { id: 'act_sc_tune', label: 'SC调参', subtitle: '换字段', type: 'action' },
  { id: 'dec_sc_ok', label: 'SC成功?', type: 'decision' },
  { id: 'act_sc_discard', label: '✖ SC耗尽', subtitle: '飞书⚠️', type: 'action' },
  { id: 'org_stuck', label: '卡死检测', type: 'phase' },
  { id: 'dec_stuck', label: '有产出?', type: 'decision' },
  { id: 'act_stuck_inc', label: 'stuck++', type: 'action' },
  { id: 'dec_stuck3', label: 'stuck≥3?', type: 'decision' },
  { id: 'act_stuck_mode', label: '⚠️ 卡死', subtitle: '跳零占用', type: 'action' },
  { id: 'act_loop', label: '🔄 Loop', subtitle: '回正交分析', type: 'action' },
];

// Rectangular closed-loop node positions (viewBox 0-100, scaled to container)
// Top edge: main generation pipeline (left→right)
// Right edge: IS/optimize pipeline (top→bottom)
// Bottom edge: SC→submit→stuck→loop (right→left)
// Inside: branch nodes
const NODE_LAYOUT: Record<string, { x: number; y: number }> = {
  // ── TOP EDGE (left→right, y=14) ──
  'org_ortho':      { x: 4.0, y: 14 },
  'dec_active20':   { x: 12.5, y: 14 },
  'org_gen':        { x: 21.0, y: 14 },
  'dec_mult':       { x: 29.5, y: 14 },
  'act_phase0':     { x: 38.0, y: 14 },
  'act_dedup':      { x: 46.5, y: 14 },
  'act_sd_score':   { x: 55.0, y: 14 },
  'act_intra_div':  { x: 63.5, y: 14 },
  'act_topn':       { x: 72.0, y: 14 },
  'org_quick_test': { x: 80.5, y: 14 },
  'dec_s':          { x: 89.0, y: 14 },

  // ── RIGHT EDGE (top→bottom, x=93) ──
  'act_pass_quick': { x: 93, y: 24 },
  'org_full_is':    { x: 93, y: 31.5 },
  'act_adaptive':   { x: 93, y: 39 },
  'dec_is':         { x: 93, y: 46.5 },
  'act_optimize':   { x: 93, y: 54 },

  // ── BOTTOM EDGE (right→left, y=64) ──
  'org_sc':         { x: 89.0, y: 64 },
  'dec_sc':         { x: 76.0, y: 64 },
  'act_submit':     { x: 63.0, y: 64 },
  'org_stuck':      { x: 50.0, y: 64 },
  'dec_stuck':      { x: 37.0, y: 64 },
  'act_loop':       { x: 20.0, y: 64 },

  // ── INSIDE (branch nodes) ──
  'done':           { x: 12.5, y: 5 },
  'act_phase1':     { x: 38.0, y: 26 },
  'act_phase2':     { x: 38.0, y: 36 },
  'act_skip':       { x: 91, y: 24 },
  'act_fail':       { x: 91, y: 34 },
  'act_tune':       { x: 91, y: 44 },
  'dec_tune_ok':    { x: 91, y: 52 },
  'act_discard':    { x: 76.0, y: 54 },
  'act_sc_tune':    { x: 63.0, y: 54 },
  'dec_sc_ok':      { x: 63.0, y: 44 },
  'act_sc_discard': { x: 50.0, y: 54 },
  'act_stuck_inc':  { x: 37.0, y: 52 },
  'dec_stuck3':     { x: 37.0, y: 42 },
  'act_stuck_mode': { x: 37.0, y: 32 },
};

const EDGES: { source: string; target: string; label?: string; style?: 'straight' | 'ortho' | 'loop' }[] = [
  // Main flow — top edge (left→right)
  { source: 'org_ortho', target: 'dec_active20' },
  { source: 'dec_active20', target: 'org_gen', label: '否' },
  { source: 'org_gen', target: 'dec_mult' },
  { source: 'dec_mult', target: 'act_phase0', label: '否' },
  { source: 'act_phase0', target: 'act_dedup' },
  { source: 'act_dedup', target: 'act_sd_score' },
  { source: 'act_sd_score', target: 'act_intra_div' },
  { source: 'act_intra_div', target: 'act_topn' },
  { source: 'act_topn', target: 'org_quick_test' },
  { source: 'org_quick_test', target: 'dec_s' },
  // Right edge (top→bottom)
  { source: 'dec_s', target: 'act_pass_quick', label: 'S≥1.0' },
  { source: 'act_pass_quick', target: 'org_full_is' },
  { source: 'org_full_is', target: 'act_adaptive' },
  { source: 'act_adaptive', target: 'dec_is' },
  { source: 'dec_is', target: 'act_optimize', label: '✅ PASS' },
  // Bottom edge (right→left) — optimized to SC→submit→stuck
  { source: 'act_optimize', target: 'org_sc', label: 'IS通过' },
  { source: 'org_sc', target: 'dec_sc' },
  { source: 'dec_sc', target: 'act_submit', label: '✅ ≥0.90' },
  { source: 'act_submit', target: 'org_stuck', label: 'batch完成' },
  { source: 'org_stuck', target: 'dec_stuck' },
  // Loop back
  { source: 'dec_stuck', target: 'act_loop', label: '✅ 有', style: 'ortho' },
  { source: 'act_loop', target: 'org_ortho', label: '🔄 Loop', style: 'loop' },
  // Branch: done
  { source: 'dec_active20', target: 'done', label: '✅ 是' },
  { source: 'done', target: 'org_ortho', label: '🏆', style: 'ortho' },
  // Branch: MULT phases
  { source: 'dec_mult', target: 'act_phase1', label: '✅ 是' },
  { source: 'act_phase1', target: 'act_sd_score' },
  { source: 'act_phase2', target: 'act_sd_score' },
  // Branch: Quick Test
  { source: 'dec_s', target: 'act_skip', label: 'S=None' },
  { source: 'dec_s', target: 'act_fail', label: 'S<1.0' },
  // Branch: Tune
  { source: 'dec_is', target: 'act_tune', label: 'TUNE/FAIL' },
  { source: 'act_tune', target: 'dec_tune_ok' },
  { source: 'dec_tune_ok', target: 'act_adaptive', label: '✅ 重试' },
  { source: 'dec_tune_ok', target: 'act_discard', label: '❌ 放弃' },
  { source: 'act_optimize', target: 'dec_tune_ok' },
  // Branch: SC
  { source: 'dec_sc', target: 'act_sc_tune', label: '❌ <0.90' },
  { source: 'act_sc_tune', target: 'dec_sc_ok' },
  { source: 'dec_sc_ok', target: 'org_sc', label: '✅ 重试' },
  { source: 'dec_sc_ok', target: 'act_sc_discard', label: '❌ 放弃' },
  { source: 'act_sc_discard', target: 'org_stuck' },
  { source: 'act_discard', target: 'org_stuck' },
  // Branch: Stuck
  { source: 'dec_stuck', target: 'act_stuck_inc', label: '全体失败' },
  { source: 'act_stuck_inc', target: 'dec_stuck3' },
  { source: 'dec_stuck3', target: 'act_stuck_mode', label: '✅ 3+' },
  { source: 'dec_stuck3', target: 'act_loop', label: '否' },
  { source: 'act_stuck_mode', target: 'act_loop' },
  { source: 'act_skip', target: 'act_loop' },
  { source: 'act_fail', target: 'act_loop' },
];

// Map phase name → set of active node IDs
const ACTIVE_IDS_FOR_PHASE: Record<string, Set<string>> = {
  init: new Set(['org_ortho']),
  orthogonality: new Set(['org_ortho', 'dec_active20']),
  generate: new Set(['org_gen', 'dec_mult', 'act_phase0', 'act_phase1', 'act_phase2', 'act_dedup', 'act_sd_score', 'act_intra_div']),
  quick_test: new Set(['org_quick_test', 'dec_s']),
  full_sim: new Set(['org_full_is', 'act_adaptive']),
  tune_is: new Set(['dec_is', 'act_optimize', 'act_tune', 'dec_tune_ok']),
  sc_submit: new Set(['org_sc', 'dec_sc', 'act_sc_tune', 'dec_sc_ok']),
  submit: new Set(['act_submit']),
  done: new Set(['done']),
};

const NODE_COLORS: Record<string, string> = {
  phase: '#6366f1',
  decision: '#f59e0b',
  action: '#34d399',
  end: '#34d399',
};

// Per-stage accent colors for edges and background
const STAGE_ACCENT: Record<string, { edge: string; glow: string; bg: string }> = {
  orthogonality: { edge: '#a1a1ca', glow: 'rgba(161,161,202,0.5)', bg: 'rgba(161,161,202,0.04)' },
  generate: { edge: '#22d3ee', glow: 'rgba(34,211,238,0.5)', bg: 'rgba(34,211,238,0.04)' },
  quick_test: { edge: '#fbbf24', glow: 'rgba(251,191,36,0.5)', bg: 'rgba(251,191,36,0.04)' },
  full_sim: { edge: '#818cf8', glow: 'rgba(129,140,248,0.5)', bg: 'rgba(129,140,248,0.04)' },
  tune_is: { edge: '#fb7185', glow: 'rgba(251,113,133,0.5)', bg: 'rgba(251,113,133,0.04)' },
  sc_submit: { edge: '#f472b6', glow: 'rgba(244,114,182,0.5)', bg: 'rgba(244,114,182,0.04)' },
  submit: { edge: '#34d399', glow: 'rgba(52,211,153,0.5)', bg: 'rgba(52,211,153,0.04)' },
};

function getPhaseEmoji(phase: string): string {
  const map: Record<string, string> = {
    init: '🔄', orthogonality: '📊', generate: '⚙️',
    quick_test: '🧪', full_sim: '🔬', tune_is: '🔧',
    sc_submit: '📋', submit: '📤', done: '🏆',
  };
  return map[phase] || '⏳';
}

function getPhaseName(phase: string): string {
  const map: Record<string, string> = {
    init: 'Initializing', orthogonality: '正交分析', generate: '生成候选',
    quick_test: 'Quick Test', full_sim: 'Full IS', tune_is: '调参',
    sc_submit: 'SC提交', submit: '提交', done: '完成',
  };
  return map[phase] || phase;
}

// Compute edge path between two nodes
function edgePath(
  sx: number, sy: number, tx: number, ty: number,
  style: 'straight' | 'ortho' | 'loop' = 'straight',
  vbW: number, vbH: number
): string {
  if (style === 'straight') {
    return `M${sx},${sy} L${tx},${ty}`;
  }
  if (style === 'loop') {
    // Draw loop along left/top edges of rectangle
    const mx = Math.min(sx, tx) - 4;
    const midX = (sx + tx) / 2;
    return `M${sx},${sy} L${sx + 2},${sy} Q${sx + 6},${sy} ${sx + 6},${sy - 3} L${sx + 6},${sy - 12} L${midX},${sy - 16} L${tx - 6},${sy - 12} L${tx - 6},${ty - 3} Q${tx - 6},${ty} ${tx - 2},${ty} L${tx},${ty}`;
  }
  // Ortho: right-angle path
  const mx = sx;
  const my = (sy + ty) / 2;
  return `M${sx},${sy} L${sx},${my} L${tx},${my} L${tx},${ty}`;
}

export default function WorkflowGraph({ phase, activeCount, target, batchIndex, batchTotal }: WorkflowGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [isMobile, setIsMobile] = useState(true);
  const [scale, setScale] = useState(1);

  // ViewBox dimensions
  const VB_W = 120;
  const VB_H = 78;

  useEffect(() => {
    setIsMobile(window.innerWidth < 768);
    setExpanded(window.innerWidth >= 768);
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      setIsMobile(window.innerWidth < 768);
      if (window.innerWidth >= 768) setExpanded(true);
      // Scale: container should fit within ~500px height on desktop
      const w = el.clientWidth;
      if (w > 0) setScale(Math.max(0.5, Math.min(2, (w - 32) / VB_W / 3)));
    };
    update();
    const obs = new ResizeObserver(update);
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const activeIds = ACTIVE_IDS_FOR_PHASE[phase] || new Set();
  // Determine if we're in stuck detection or loop-back area
  const isStuckOrLoop = ['org_stuck', 'dec_stuck', 'act_stuck_inc', 'dec_stuck3', 'act_stuck_mode', 'act_loop'].some(id => activeIds.has(id));

  return (
    <div ref={containerRef} className="card bg-zinc-900/50 border border-zinc-800/50 rounded-xl p-2 md:p-3 relative overflow-hidden group">
      {/* Subtle gradient overlay */}
      <div className="absolute inset-0 bg-gradient-to-b from-indigo-500/2 to-transparent opacity-[0.02]" />

      {/* Header */}
      <div
        className="relative z-10 flex items-center justify-between select-none"
        onClick={() => { if (isMobile) setExpanded(!expanded); }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-indigo-400/80 text-[10px] shrink-0">◈</span>
          <h2 className="text-[10px] md:text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500 shrink-0">
            Pipeline
          </h2>
          {activeCount != null && (
            <span className="text-zinc-600 font-normal text-[9px] md:text-[10px] tabular-nums shrink-0">
              {activeCount}/{target ?? 20}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 min-w-0 flex-1 justify-end">
          <span className="text-[8px] md:text-[9px] text-indigo-300/60 truncate hidden sm:block">
            {getPhaseEmoji(phase)} {getPhaseName(phase)}
          </span>
          {batchIndex != null && (
            <span className="bg-zinc-800/50 px-1.5 py-0.5 rounded text-[8px] md:text-[9px] text-zinc-500 font-mono shrink-0 border border-zinc-700/30">
              {batchIndex}/{batchTotal ?? '?'}
            </span>
          )}
          <span className={`px-1.5 py-0.5 rounded text-[8px] md:text-[9px] font-mono shrink-0 border ${
            phase === 'done'
              ? 'bg-emerald-500/10 text-emerald-400/80 border-emerald-500/20'
              : 'bg-indigo-500/10 text-indigo-400/80 border-indigo-500/20'
          }`}>
            {phase}
          </span>
          {isMobile && (
            <span className="text-zinc-600 text-[10px] ml-1 shrink-0 transition-transform duration-200"
              style={{ transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)' }}>
              ▼
            </span>
          )}
        </div>
      </div>

      {/* Collapsed mobile summary */}
      {isMobile && !expanded && (
        <div className="mt-2 flex items-center gap-1 text-[9px] text-zinc-500 overflow-x-auto pb-1">
          <span className="shrink-0">{getPhaseEmoji(phase)}</span>
          <span className="text-indigo-400 font-mono truncate">
            {NODES.filter(n => activeIds.has(n.id)).map(n => n.label).join(' → ') || phase}
          </span>
        </div>
      )}

      {/* Expanded: SVG rectangular closed loop */}
      {expanded && (
        <>
          {/* Legend */}
          <div className="hidden sm:flex items-center gap-4 mt-1.5 mb-2 text-[8px] text-zinc-600">
            <span className="flex items-center gap-1.5">
              <svg width="8" height="8"><polygon
                points="4,0.5 7.5,2 7.5,6 4,7.5 0.5,6 0.5,2" fill="transparent" stroke="#6366f1" strokeWidth="0.8" /></svg>
              <span className="uppercase tracking-wider">Phase</span>
            </span>
            <span className="flex items-center gap-1.5">
              <svg width="8" height="8"><polygon
                points="4,0.5 7.5,4 4,7.5 0.5,4" fill="transparent" stroke="#f59e0b" strokeWidth="0.8" /></svg>
              <span className="uppercase tracking-wider">Decision</span>
            </span>
            <span className="flex items-center gap-1.5">
              <svg width="8" height="8"><circle cx="4" cy="4" r="3.5" fill="transparent" stroke="#34d399" strokeWidth="0.8" /></svg>
              <span className="uppercase tracking-wider">Action</span>
            </span>
            <span className="flex items-center gap-1.5">
              <svg width="8" height="8"><circle cx="4" cy="4" r="4" fill="none" stroke="#818cf8" strokeWidth="1.2" strokeDasharray="1.5,1" /></svg>
              <span className="uppercase tracking-wider text-indigo-400/70">Active</span>
            </span>
            <span className="flex items-center gap-1.5">
              <svg width="8" height="8"><line x1="1" y1="4" x2="7" y2="4" stroke="#34d399" strokeWidth="1" /></svg>
              <span className="text-zinc-500">Loop</span>
            </span>
            <span className="text-zinc-700 ml-auto text-[7px] tracking-widest">矩形闭环 · 循环回流</span>
          </div>

          {/* SVG */}
          <div className="w-full overflow-auto">
            <svg
              viewBox={`0 0 ${VB_W} ${VB_H}`}
              className="w-full"
              preserveAspectRatio="xMidYMid meet"
              style={{ maxHeight: 520, minHeight: 260 }}
            >
              <defs>
                <marker id="wfArr" markerWidth="2" markerHeight="1.5" refX="1.5" refY="0.75" orient="auto">
                  <path d="M0,0 L2,0.75 L0,1.5Z" fill="rgba(255,255,255,0.08)" />
                </marker>
                <marker id="wfArrAct" markerWidth="2.5" markerHeight="2" refX="2" refY="1" orient="auto">
                  <path d="M0,0 L2.5,1 L0,2Z" fill="rgba(129,140,248,0.6)" />
                </marker>
                <marker id="wfArrGreen" markerWidth="2.5" markerHeight="2" refX="2" refY="1" orient="auto">
                  <path d="M0,0 L2.5,1 L0,2Z" fill="rgba(52,211,153,0.6)" />
                </marker>
                <marker id="wfArrAmber" markerWidth="2.5" markerHeight="2" refX="2" refY="1" orient="auto">
                  <path d="M0,0 L2.5,1 L0,2Z" fill="rgba(245,158,11,0.5)" />
                </marker>
                <filter id="wfGlow">
                  <feGaussianBlur stdDeviation="1.5" result="blur" />
                  <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
                <filter id="wfGlowStrong">
                  <feGaussianBlur stdDeviation="3" result="blur" />
                  <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
                <filter id="wfGlowSubtle">
                  <feGaussianBlur stdDeviation="1" result="blur" />
                  <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
                <linearGradient id="wfEdgeActive" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#818cf8" stopOpacity="0.5" />
                  <stop offset="100%" stopColor="#818cf8" stopOpacity="0.15" />
                </linearGradient>
                <linearGradient id="wfEdgeGreen" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#34d399" stopOpacity="0.5" />
                  <stop offset="100%" stopColor="#34d399" stopOpacity="0.15" />
                </linearGradient>
                <linearGradient id="wfEdgeAmber" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.5" />
                  <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.15" />
                </linearGradient>
                <radialGradient id="wfNodeBgActive" cx="40%" cy="35%" r="60%">
                  <stop offset="0%" stopColor="rgba(129,140,248,0.25)" />
                  <stop offset="100%" stopColor="rgba(49,46,129,0.05)" />
                </radialGradient>
                <radialGradient id="wfNodeBgDone" cx="40%" cy="35%" r="60%">
                  <stop offset="0%" stopColor="rgba(52,211,153,0.1)" />
                  <stop offset="100%" stopColor="rgba(49,129,82,0.02)" />
                </radialGradient>
              </defs>

              {/* Background: subtle rectangle outline with corner accents */}
              <rect x={2} y={10} width={93} height={56} rx={2}
                fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth={0.5} />
              {/* Corner accent marks */}
              <path d="M2,16 L2,12 Q2,10 4,10 L8,10" fill="none" stroke="rgba(99,102,241,0.15)" strokeWidth={0.8} />
              <path d="M95,10 L95,12 Q95,14 93,14 L89,14" fill="none" stroke="rgba(99,102,241,0.15)" strokeWidth={0.8} />
              <path d="M2,62 L2,66 Q2,68 4,68 L8,68" fill="none" stroke="rgba(99,102,241,0.15)" strokeWidth={0.8} />
              <path d="M95,68 L95,66 Q95,64 93,64 L89,64" fill="none" stroke="rgba(99,102,241,0.15)" strokeWidth={0.8} />

              {/* Layer 0: active/bright edges (rendered first, behind nodes) */}
              {EDGES.map(e => {
                const sp = NODE_LAYOUT[e.source];
                const tp = NODE_LAYOUT[e.target];
                if (!sp || !tp) return null;
                const sActive = activeIds.has(e.source);
                const tActive = activeIds.has(e.target);
                const pathActive = sActive || tActive || (isStuckOrLoop && (e.target === 'act_loop' || e.source === 'act_loop'));
                const isLoop = e.style === 'loop';

                if (!pathActive) return null;

                // Determine color scheme based on node types
                let markerId = 'url(#wfArrAct)';
                let edgeGrad = 'url(#wfEdgeActive)';
                let edgeWidth = 1.4;
                let edgeOpacity = 0.9;

                if (isLoop) {
                  markerId = 'url(#wfArrGreen)';
                  edgeGrad = 'url(#wfEdgeGreen)';
                  edgeWidth = 1.6;
                  edgeOpacity = 0.85;
                } else if (e.target === 'done' || e.source === 'done') {
                  markerId = 'url(#wfArrGreen)';
                  edgeGrad = 'url(#wfEdgeGreen)';
                  edgeWidth = 1.6;
                } else if (e.target === 'act_discard' || e.target === 'act_sc_discard' || e.target === 'act_fail' || e.target === 'act_skip') {
                  markerId = 'url(#wfArrAmber)';
                  edgeGrad = 'url(#wfEdgeAmber)';
                  edgeWidth = 1.2;
                  edgeOpacity = 0.7;
                }

                let d = '';
                if (isLoop) {
                  const lx = VB_W * 0.03;
                  d = `M${sp.x},${sp.y} L${lx},${sp.y} L${lx},${tp.y} L${tp.x - 2},${tp.y}`;
                } else if (e.style === 'ortho' || (e.source === 'dec_stuck' && e.target === 'act_loop')) {
                  const mx = (sp.x + tp.x) / 2;
                  d = `M${sp.x},${sp.y} L${mx},${sp.y} L${mx},${tp.y} L${tp.x},${tp.y}`;
                } else {
                  d = `M${sp.x},${sp.y} L${tp.x},${tp.y}`;
                }

                return (
                  <g key={`active-${e.source}→${e.target}`}>
                    <path d={d} fill="none" stroke={edgeGrad} strokeWidth={edgeWidth}
                      strokeDasharray={isLoop ? '1.5,1.5' : 'none'}
                      markerEnd={markerId} opacity={edgeOpacity} filter="url(#wfGlow)" />
                    {e.label && (
                      <text x={(sp.x + tp.x) / 2} y={(sp.y + tp.y) / 2 - 2.2}
                        textAnchor="middle" dominantBaseline="central"
                        fill="rgba(224,231,255,0.9)" fontSize={2.6}
                        fontFamily="'JetBrains Mono',monospace"
                        fontWeight={600}
                        style={{ paintOrder: 'stroke', stroke: '#0f0f12', strokeWidth: 0.7, strokeLinecap: 'round', strokeLinejoin: 'round' }}>
                        {e.label}
                      </text>
                    )}
                  </g>
                );
              })}

              {/* Layer 1: dim/inactive edges (thin, behind nodes) */}
              {EDGES.map(e => {
                const sp = NODE_LAYOUT[e.source];
                const tp = NODE_LAYOUT[e.target];
                if (!sp || !tp) return null;
                const sActive = activeIds.has(e.source);
                const tActive = activeIds.has(e.target);
                const pathActive = sActive || tActive || (isStuckOrLoop && (e.target === 'act_loop' || e.source === 'act_loop'));

                if (pathActive) return null;

                let d = '';
                const isLoop = e.style === 'loop';
                if (isLoop) {
                  const lx = VB_W * 0.03;
                  d = `M${sp.x},${sp.y} L${lx},${sp.y} L${lx},${tp.y} L${tp.x - 2},${tp.y}`;
                } else if (e.style === 'ortho' || (e.source === 'dec_stuck' && e.target === 'act_loop')) {
                  const mx = (sp.x + tp.x) / 2;
                  d = `M${sp.x},${sp.y} L${mx},${sp.y} L${mx},${tp.y} L${tp.x},${tp.y}`;
                } else {
                  d = `M${sp.x},${sp.y} L${tp.x},${tp.y}`;
                }

                return (
                  <g key={`dim-${e.source}→${e.target}`}>
                    <path d={d} fill="none" stroke="rgba(255,255,255,0.03)" strokeWidth={0.3}
                      strokeDasharray={isLoop ? '1.5,1.5' : 'none'}
                      markerEnd="url(#wfArr)" />
                  </g>
                );
              })}

              {/* Nodes */}
              {NODES.map(n => {
                const pos = NODE_LAYOUT[n.id];
                if (!pos) return null;
                const isActive = activeIds.has(n.id);
                const isEnd = n.type === 'end';
                const color = NODE_COLORS[n.type] || '#6366f1';
                const fill = isActive ? 'url(#wfNodeBgActive)' : isEnd ? 'url(#wfNodeBgDone)' : n.type === 'end' ? '#065f46' : '#1e293b';
                const stroke = isActive ? '#818cf8' : color;
                const labelColor = isActive ? '#e0e7ff' : n.type === 'end' ? '#a7f3d0' : n.type === 'phase' ? '#e2e8f0' : n.type === 'decision' ? '#fbbf24' : '#6ee7b7';
                const dimColor = isActive ? 'rgba(199,210,254,0.7)' : 'rgba(113,113,122,0.35)';

                const r = isEnd ? 2.8 : isActive ? 4 : 3.2;
                const isDecision = n.type === 'decision';
                const isPhase = n.type === 'phase';

                return (
                  <g key={n.id}>
                    {/* Active glow - triple layer */}
                    {isActive && (
                      <>
                        {/* Outer ambient glow */}
                        <circle cx={pos.x} cy={pos.y} r={r + 5} fill={`${stroke}08`}
                          filter="url(#wfGlowStrong)" />
                        {/* Mid ring */}
                        <circle cx={pos.x} cy={pos.y} r={r + 3} fill="none" stroke={`${stroke}25`}
                          strokeWidth={1.5} filter="url(#wfGlowStrong)" />
                        {/* Inner ring */}
                        <circle cx={pos.x} cy={pos.y} r={r + 1.5} fill="none" stroke={`${stroke}40`}
                          strokeWidth={0.8} filter="url(#wfGlow)" />
                      </>
                    )}

                    {/* Node body */}
                    {isDecision ? (
                      <g>
                        <polygon
                          points={`${pos.x},${pos.y - r * 1.5} ${pos.x + r * 1.5},${pos.y} ${pos.x},${pos.y + r * 1.5} ${pos.x - r * 1.5},${pos.y}`}
                          fill={fill} stroke={stroke} strokeWidth={isActive ? 1.8 : 0.8}
                          opacity={isActive ? 0.95 : 0.5}
                          style={{
                            filter: isActive ? 'url(#wfGlow)' : undefined,
                          }}
                        />
                        {/* Inner question mark */}
                        <text x={pos.x} y={pos.y + 0.4} textAnchor="middle" dominantBaseline="central"
                          fill={isActive ? 'rgba(255,255,255,0.95)' : dimColor} fontSize={2.2} fontFamily="monospace"
                          fontWeight={700}>{isActive ? '?' : ''}</text>
                      </g>
                    ) : isEnd ? (
                      <g>
                        <circle cx={pos.x} cy={pos.y} r={r}
                          fill={fill} stroke={stroke} strokeWidth={isActive ? 1.8 : 0.8}
                          opacity={isActive ? 1 : 0.4}
                          style={{ filter: isActive ? 'url(#wfGlow)' : undefined }}
                        />
                        {/* Inner bullseye */}
                        <circle cx={pos.x} cy={pos.y} r={r * 0.55}
                          fill={isActive ? 'rgba(52,211,153,0.3)' : 'rgba(52,211,153,0.12)'}
                          stroke={isActive ? 'rgba(52,211,153,0.5)' : 'rgba(52,211,153,0.2)'}
                          strokeWidth={0.5}
                        />
                        <circle cx={pos.x} cy={pos.y} r={1.2}
                          fill={isActive ? '#34d399' : 'rgba(52,211,153,0.3)'}
                        />
                      </g>
                    ) : isPhase ? (
                      <g>
                        <polygon
                          points={Array.from({ length: 6 }, (_, i) => {
                            const a = (Math.PI / 3) * i - Math.PI / 6;
                            return `${pos.x + r * Math.cos(a)},${pos.y + r * Math.sin(a)}`;
                          }).join(' ')}
                          fill={fill} stroke={stroke} strokeWidth={isActive ? 1.8 : 0.8}
                          opacity={isActive ? 0.9 : 0.5}
                          style={{ filter: isActive ? 'url(#wfGlow)' : undefined }}
                        />
                        {/* Phase icon indicator */}
                        {isActive && (
                          <circle cx={pos.x} cy={pos.y} r={r * 0.35}
                            fill="rgba(255,255,255,0.15)"
                          />
                        )}
                      </g>
                    ) : (
                      <g>
                        <circle cx={pos.x} cy={pos.y} r={r}
                          fill={fill} stroke={stroke} strokeWidth={isActive ? 1.8 : 0.8}
                          opacity={isActive ? 0.9 : 0.5}
                          style={{ filter: isActive ? 'url(#wfGlow)' : undefined }}
                        />
                        {/* Action dot */}
                        {isActive && (
                          <circle cx={pos.x} cy={pos.y} r={1}
                            fill="rgba(255,255,255,0.3)"
                          />
                        )}
                      </g>
                    )}

                    {/* Label - rendered on top of everything */}
                    <text x={pos.x} y={pos.y - r - 2.5} textAnchor="middle" dominantBaseline="central"
                      fill={isActive ? labelColor : dimColor}
                      fontSize={isActive ? 3.2 : 2.4}
                      fontFamily="'JetBrains Mono',monospace"
                      fontWeight={isActive ? 700 : 400}
                      style={{ paintOrder: 'stroke', stroke: '#0f0f12', strokeWidth: 0.6, strokeLinecap: 'round', strokeLinejoin: 'round' }}>
                      {n.label}
                    </text>

                    {/* Subtitle */}
                    {n.subtitle && (
                      <text x={pos.x} y={pos.y + r + 3.2} textAnchor="middle" dominantBaseline="central"
                        fill={dimColor} fontSize={1.6} fontFamily="'JetBrains Mono',monospace"
                        opacity={isActive ? 0.6 : 0.25}>
                        {n.subtitle}
                      </text>
                    )}
                  </g>
                );
              })}

              {/* Loop-back indicator - decorative left border text */}
              <text x={8} y={40} textAnchor="middle" dominantBaseline="central"
                fill="rgba(52,211,153,0.35)" fontSize={1.8} fontFamily="'JetBrains Mono',monospace"
                transform="rotate(-90, 8, 40)"
                style={{ letterSpacing: '0.08em' }}
                fontWeight={500}>
                ← 循环回流
              </text>

              {/* Section labels - subtle background text */}
              <text x={55} y={10} textAnchor="middle" dominantBaseline="central"
                fill="rgba(255,255,255,0.05)" fontSize={1.6} fontFamily="monospace"
                letterSpacing="0.05em" fontWeight={600}>
                生成阶段 →
              </text>
              <text x={55} y={72} textAnchor="middle" dominantBaseline="central"
                fill="rgba(255,255,255,0.05)" fontSize={1.6} fontFamily="monospace"
                letterSpacing="0.05em" fontWeight={600}>
                ← 提交/卡死检测/循环
              </text>
            </svg>
          </div>
        </>
      )}
    </div>
  );
}