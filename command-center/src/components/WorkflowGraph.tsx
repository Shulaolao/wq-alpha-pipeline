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
  const VB_W = 100;
  const VB_H = 72;

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
    <div ref={containerRef} className="card p-2 md:p-3 animate-[fade-in_0.3s_ease-out]">
      {/* Header */}
      <div
        className="flex items-center justify-between cursor-pointer md:cursor-default select-none"
        onClick={() => { if (isMobile) setExpanded(!expanded); }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-indigo-400 text-[10px] shrink-0">◈</span>
          <h2 className="text-[10px] md:text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 shrink-0">
            Pipeline
          </h2>
          {activeCount != null && (
            <span className="text-gray-600 font-normal text-[9px] md:text-[10px] shrink-0">
              {activeCount}/{target ?? 20}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 min-w-0 flex-1 justify-end">
          <span className="text-[8px] md:text-[9px] text-indigo-300/70 truncate hidden sm:block">
            {getPhaseEmoji(phase)} {getPhaseName(phase)}
          </span>
          {batchIndex != null && (
            <span className="bg-zinc-800/60 px-1.5 py-0.5 rounded text-[8px] md:text-[9px] text-gray-500 font-mono shrink-0">
              {batchIndex}/{batchTotal ?? '?'}
            </span>
          )}
          <span className={`px-1.5 py-0.5 rounded text-[8px] md:text-[9px] font-mono shrink-0 ${
            phase === 'done' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-indigo-500/10 text-indigo-400'
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
          <div className="hidden sm:flex items-center gap-3 mt-1 mb-1 text-[9px] text-gray-600">
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-zinc-800 border border-indigo-500" /> Phase</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-zinc-800 border border-amber-500" /> Decision</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-zinc-800 border border-emerald-500" /> Action</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm bg-indigo-900 border border-indigo-400" /> Active</span>
            <span className="text-zinc-700 ml-auto hidden md:inline">矩形闭环 · 循环回流</span>
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
                  <path d="M0,0 L2.5,1 L0,2Z" fill="rgba(129,140,248,0.5)" />
                </marker>
                <marker id="wfArrGreen" markerWidth="2.5" markerHeight="2" refX="2" refY="1" orient="auto">
                  <path d="M0,0 L2.5,1 L0,2Z" fill="rgba(52,211,153,0.5)" />
                </marker>
                <marker id="wfArrAmber" markerWidth="2.5" markerHeight="2" refX="2" refY="1" orient="auto">
                  <path d="M0,0 L2.5,1 L0,2Z" fill="rgba(245,158,11,0.5)" />
                </marker>
                <filter id="wfGlow">
                  <feGaussianBlur stdDeviation="1.5" result="blur" />
                  <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
              </defs>

              {/* Background: subtle rectangle outline */}
              <rect x={2} y={10} width={93} height={56} rx={2}
                fill="none" stroke="rgba(255,255,255,0.02)" strokeWidth={0.3} strokeDasharray="2,3" />

              {/* Edges */}
              {EDGES.map(e => {
                const sp = NODE_LAYOUT[e.source];
                const tp = NODE_LAYOUT[e.target];
                if (!sp || !tp) return null;
                const sActive = activeIds.has(e.source);
                const tActive = activeIds.has(e.target);
                const pathActive = sActive || tActive || (isStuckOrLoop && (e.target === 'act_loop' || e.source === 'act_loop'));
                const isLoop = e.style === 'loop';

                let markerId = 'url(#wfArr)';
                if (pathActive && isLoop) markerId = 'url(#wfArrGreen)';
                else if (pathActive) markerId = 'url(#wfArrAct)';
                const edgeColor = isLoop ? 'rgba(52,211,153,0.35)' : pathActive ? 'rgba(129,140,248,0.4)' : 'rgba(255,255,255,0.05)';
                const edgeWidth = isLoop ? 1.2 : pathActive ? 0.8 : 0.4;

                let d = '';
                if (isLoop) {
                  // Loop-back path: from act_loop (bottom-left) back to org_ortho (top-left)
                  const lx = VB_W * 0.05;
                  d = `M${sp.x},${sp.y} L${lx},${sp.y} L${lx},${tp.y} L${tp.x - 2},${tp.y}`;
                } else if (e.style === 'ortho' || (e.source === 'dec_stuck' && e.target === 'act_loop')) {
                  const mx = (sp.x + tp.x) / 2;
                  d = `M${sp.x},${sp.y} L${mx},${sp.y} L${mx},${tp.y} L${tp.x},${tp.y}`;
                } else {
                  d = `M${sp.x},${sp.y} L${tp.x},${tp.y}`;
                }

                return (
                  <g key={`${e.source}→${e.target}`}>
                    <path d={d} fill="none" stroke={edgeColor} strokeWidth={edgeWidth}
                      strokeDasharray={isLoop ? '1.5,1.5' : 'none'}
                      markerEnd={markerId} opacity={pathActive ? 0.7 : 0.3} />
                    {e.label && pathActive && (
                      <text x={(sp.x + tp.x) / 2} y={(sp.y + tp.y) / 2 - 1.5}
                        textAnchor="middle" dominantBaseline="central"
                        fill="rgba(129,140,248,0.7)" fontSize={2.2}
                        fontFamily="'JetBrains Mono',monospace"
                        style={{ paintOrder: 'stroke', stroke: '#18181b', strokeWidth: 0.5, strokeLinecap: 'round', strokeLinejoin: 'round' }}>
                        {e.label}
                      </text>
                    )}
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
                const fill = isActive ? '#312e81' : n.type === 'end' ? '#065f46' : '#1e293b';
                const stroke = isActive ? '#818cf8' : color;
                const labelColor = isActive ? '#c7d2fe' : n.type === 'end' ? '#a7f3d0' : n.type === 'phase' ? '#e2e8f0' : n.type === 'decision' ? '#fbbf24' : '#6ee7b7';
                const dimColor = isActive ? 'rgba(199,210,254,0.6)' : 'rgba(113,113,122,0.4)';

                const r = isEnd ? 2.5 : isActive ? 3.5 : 3;
                const isDecision = n.type === 'decision';
                const isPhase = n.type === 'phase';

                // Node shape: circle for action/phase, diamond for decision, special for end
                return (
                  <g key={n.id}>
                    {/* Active glow */}
                    {isActive && (
                      <circle cx={pos.x} cy={pos.y} r={r + 2} fill="none" stroke={`${stroke}30`}
                        strokeWidth={0.6} opacity={0.4} filter="url(#wfGlow)" />
                    )}

                    {/* Node body */}
                    {isDecision ? (
                      // Diamond for decision nodes
                      <g>
                        <polygon
                          points={`${pos.x},${pos.y - r * 1.4} ${pos.x + r * 1.4},${pos.y} ${pos.x},${pos.y + r * 1.4} ${pos.x - r * 1.4},${pos.y}`}
                          fill={fill} stroke={stroke} strokeWidth={isActive ? 1.5 : 0.7} opacity={isActive ? 1 : 0.6}
                        />
                        <text x={pos.x} y={pos.y + 0.3} textAnchor="middle" dominantBaseline="central"
                          fill={isActive ? '#fff' : dimColor} fontSize={2} fontFamily="monospace">?</text>
                      </g>
                    ) : isEnd ? (
                      // Star/medal for end node
                      <circle cx={pos.x} cy={pos.y} r={r}
                        fill={fill} stroke={stroke} strokeWidth={isActive ? 1.5 : 0.7} opacity={isActive ? 1 : 0.5} />
                    ) : isPhase ? (
                      // Hexagon for phase nodes
                      <g>
                        <polygon
                          points={
                            Array.from({ length: 6 }, (_, i) => {
                              const a = (Math.PI / 3) * i - Math.PI / 6;
                              return `${pos.x + r * Math.cos(a)},${pos.y + r * Math.sin(a)}`;
                            }).join(' ')
                          }
                          fill={fill} stroke={stroke} strokeWidth={isActive ? 1.5 : 0.7} opacity={isActive ? 1 : 0.6}
                        />
                      </g>
                    ) : (
                      // Circle for action nodes
                      <circle cx={pos.x} cy={pos.y} r={r}
                        fill={fill} stroke={stroke} strokeWidth={isActive ? 1.5 : 0.7} opacity={isActive ? 1 : 0.6} />
                    )}

                    {/* Label */}
                    <text x={pos.x} y={pos.y - r - 1.5} textAnchor="middle" dominantBaseline="central"
                      fill={isActive ? labelColor : dimColor}
                      fontSize={isActive ? 2.8 : 2.2}
                      fontFamily="'JetBrains Mono',monospace"
                      fontWeight={isActive ? 'bold' : 400}
                      style={{ paintOrder: 'stroke', stroke: '#18181b', strokeWidth: 0.4, strokeLinecap: 'round', strokeLinejoin: 'round' }}>
                      {n.label}
                    </text>

                    {/* Subtitle */}
                    {n.subtitle && (
                      <text x={pos.x} y={pos.y + r + 1.8} textAnchor="middle" dominantBaseline="central"
                        fill={dimColor} fontSize={1.6} fontFamily="'JetBrains Mono',monospace"
                        opacity={isActive ? 0.8 : 0.4}>
                        {n.subtitle}
                      </text>
                    )}
                  </g>
                );
              })}

              {/* Loop-back arrow label */}
              <text x={7} y={40} textAnchor="middle" dominantBaseline="central"
                fill="rgba(52,211,153,0.3)" fontSize={1.8} fontFamily="'JetBrains Mono',monospace"
                transform="rotate(-90, 7, 40)">
                ← 循环回流
              </text>

              {/* Corner labels */}
              <text x={50} y={8} textAnchor="middle" dominantBaseline="central"
                fill="rgba(255,255,255,0.04)" fontSize={1.6} fontFamily="monospace">
                生成阶段 →
              </text>
              <text x={50} y={69} textAnchor="middle" dominantBaseline="central"
                fill="rgba(255,255,255,0.04)" fontSize={1.6} fontFamily="monospace">
                ← 提交/卡死检测/循环
              </text>
            </svg>
          </div>
        </>
      )}
    </div>
  );
}