'use client';

import { useEffect, useRef, useState } from 'react';


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
  order: number;
}

const NODES: WorkflowNode[] = [
  { id: 'org_ortho', label: '正交分析', subtitle: '字段频率 + AST', type: 'phase', order: 1 },
  { id: 'dec_active20', label: '≥20 ACTIVE?', type: 'decision', order: 2 },
  { id: 'done', label: '🏆 完成', subtitle: '20 ACTIVE', type: 'end', order: 99 },
  { id: 'org_gen', label: '候选生成', subtitle: 'v3.19 骨架进化', type: 'phase', order: 3 },
  { id: 'dec_mult', label: 'MULT枯竭?', subtitle: '≥50%失败', type: 'decision', order: 4 },
  { id: 'act_phase0', label: 'Phase 0', subtitle: 'MULT', type: 'action', order: 5 },
  { id: 'act_phase1', label: 'Phase 1', subtitle: 'DIRECT_RANK', type: 'action', order: 6 },
  { id: 'act_phase2', label: 'Phase 2', subtitle: '混合', type: 'action', order: 7 },
  { id: 'act_dedup', label: '去重', subtitle: '最优权重', type: 'action', order: 8 },
  { id: 'act_sd_score', label: 'sd_score', subtitle: '拓扑距离加权 (P2+P7)', type: 'action', order: 8.5 },
  { id: 'act_intra_div', label: '多样性保证', subtitle: '7种骨架各取≥1 (P5)', type: 'action', order: 9 },
  { id: 'act_topn', label: 'Top-N', type: 'action', order: 10 },
  { id: 'org_quick_test', label: 'Quick Test', subtitle: 'P1Y', type: 'phase', order: 10 },
  { id: 'dec_s', label: 'Sharpe=?', type: 'decision', order: 11 },
  { id: 'act_skip', label: '跳过', subtitle: 'S=None + 📊骨架追踪', type: 'action', order: 12 },
  { id: 'act_fail', label: '丢弃', subtitle: 'S<1.0 + 📊骨架追踪', type: 'action', order: 13 },
  { id: 'act_pass_quick', label: '通过', subtitle: 'S≥1.0', type: 'action', order: 14 },
  { id: 'org_full_is', label: 'Full IS', subtitle: '5Y回测', type: 'phase', order: 15 },
  { id: 'act_adaptive', label: '轮询', subtitle: '15→120s', type: 'action', order: 16 },
  { id: 'dec_is', label: 'IS结果?', type: 'decision', order: 17 },
  { id: 'act_optimize', label: '优化', subtitle: '网格搜索', type: 'action', order: 18 },
  { id: 'act_tune', label: '调参', subtitle: '权重+动量', type: 'action', order: 19 },
  { id: 'dec_tune_ok', label: '调参成功?', type: 'decision', order: 20 },
  { id: 'act_discard', label: '✖ 丢弃', subtitle: '📊骨架失败 + 飞书⚠️', type: 'action', order: 21 },
  { id: 'org_sc', label: 'SC提交', subtitle: 'SELF_CORR', type: 'phase', order: 22 },
  { id: 'dec_sc', label: 'SC<0.90?', type: 'decision', order: 23 },
  { id: 'act_submit', label: '✅ 提交', subtitle: '📊骨架成功 + 飞书🎉', type: 'action', order: 24 },
  { id: 'act_sc_tune', label: 'SC调参', subtitle: '换字段', type: 'action', order: 25 },
  { id: 'dec_sc_ok', label: 'SC成功?', type: 'decision', order: 26 },
  { id: 'act_sc_discard', label: '✖ SC耗尽', subtitle: '📊骨架失败 + 飞书⚠️', type: 'action', order: 27 },
  { id: 'org_stuck', label: '卡死检测', type: 'phase', order: 28 },
  { id: 'dec_stuck', label: '有产出?', type: 'decision', order: 29 },
  { id: 'act_stuck_inc', label: 'stuck++', type: 'action', order: 30 },
  { id: 'dec_stuck3', label: 'stuck≥3?', type: 'decision', order: 31 },
  { id: 'act_stuck_mode', label: '⚠️ 卡死', subtitle: '跳零占用', type: 'action', order: 32 },
  { id: 'act_loop', label: '🔄 Loop', subtitle: '回正交分析', type: 'action', order: 33 },
];

const EDGES: { source: string; target: string; label?: string }[] = [
  { source: 'org_ortho', target: 'dec_active20' },
  { source: 'dec_active20', target: 'done', label: '✅ 是' },
  { source: 'dec_active20', target: 'org_gen', label: '否' },
  { source: 'org_gen', target: 'dec_mult' },
  { source: 'dec_mult', target: 'act_phase0', label: '否' },
  { source: 'dec_mult', target: 'act_phase1', label: '✅ 是' },
  { source: 'act_phase0', target: 'act_dedup' },
  { source: 'act_phase1', target: 'act_sd_score' },
  { source: 'act_phase2', target: 'act_sd_score' },
  { source: 'act_dedup', target: 'act_sd_score' },
  { source: 'act_sd_score', target: 'act_intra_div' },
  { source: 'act_intra_div', target: 'act_topn' },
  { source: 'act_topn', target: 'org_quick_test' },
  { source: 'org_quick_test', target: 'dec_s' },
  { source: 'dec_s', target: 'act_skip', label: 'S=None' },
  { source: 'dec_s', target: 'act_fail', label: 'S<1.0' },
  { source: 'dec_s', target: 'act_pass_quick', label: 'S≥1.0' },
  { source: 'act_pass_quick', target: 'org_full_is' },
  { source: 'org_full_is', target: 'act_adaptive' },
  { source: 'act_adaptive', target: 'dec_is' },
  { source: 'dec_is', target: 'act_optimize', label: '✅ PASS' },
  { source: 'dec_is', target: 'act_tune', label: 'TUNE/FAIL' },
  { source: 'act_optimize', target: 'dec_tune_ok' },
  { source: 'act_tune', target: 'dec_tune_ok' },
  { source: 'dec_tune_ok', target: 'act_adaptive', label: '✅ 重试' },
  { source: 'dec_tune_ok', target: 'act_discard', label: '❌ 放弃' },
  { source: 'act_optimize', target: 'org_sc', label: 'IS通过' },
  { source: 'act_optimize', target: 'org_sc', label: 'IS通过' },
  { source: 'org_sc', target: 'dec_sc' },
  { source: 'dec_sc', target: 'act_submit', label: '✅ ≥0.90' },
  { source: 'dec_sc', target: 'act_sc_tune', label: '❌ <0.90' },
  { source: 'act_sc_tune', target: 'dec_sc_ok' },
  { source: 'dec_sc_ok', target: 'org_sc', label: '✅ 重试' },
  { source: 'dec_sc_ok', target: 'act_sc_discard', label: '❌ 放弃' },
  { source: 'act_submit', target: 'org_stuck', label: 'batch完成' },
  { source: 'act_sc_discard', target: 'org_stuck' },
  { source: 'act_discard', target: 'org_stuck' },
  { source: 'org_stuck', target: 'dec_stuck' },
  { source: 'dec_stuck', target: 'act_loop', label: '✅ 有' },
  { source: 'dec_stuck', target: 'act_stuck_inc', label: '全体失败' },
  { source: 'act_stuck_inc', target: 'dec_stuck3' },
  { source: 'dec_stuck3', target: 'act_stuck_mode', label: '✅ 3+' },
  { source: 'dec_stuck3', target: 'act_loop', label: '否' },
  { source: 'act_stuck_mode', target: 'act_loop' },
  { source: 'act_skip', target: 'act_loop' },
  { source: 'act_fail', target: 'act_loop' },
];

const NODE_COLORS: Record<string, { fill: string; stroke: string; label: string }> = {
  phase: { fill: '#1e293b', stroke: '#6366f1', label: '#e2e8f0' },
  decision: { fill: '#1e293b', stroke: '#f59e0b', label: '#fbbf24' },
  action: { fill: '#1e293b', stroke: '#34d399', label: '#6ee7b7' },
  end: { fill: '#065f46', stroke: '#34d399', label: '#a7f3d0' },
};

const ACTIVE_COLORS = { fill: '#312e81', stroke: '#818cf8', label: '#c7d2fe' };

const ACTIVE_IDS_FOR_PHASE: Record<string, string[]> = {
  init: ['org_ortho'],
  orthogonality: ['org_ortho', 'dec_active20'],
  generate: ['org_gen', 'dec_mult', 'act_phase0', 'act_phase1', 'act_phase2', 'act_dedup', 'act_sd_score', 'act_intra_div'],
  quick_test: ['org_quick_test', 'dec_s'],
  full_sim: ['org_full_is', 'act_adaptive'],
  tune_is: ['dec_is', 'act_optimize', 'act_tune', 'dec_tune_ok'],
  sc_submit: ['org_sc', 'dec_sc', 'act_sc_tune', 'dec_sc_ok'],
  submit: ['act_submit'],
  done: ['done'],
};

function getPhaseName(phase: string): string {
  const names: Record<string, string> = {
    init: '🔄 Initializing', orthogonality: '📊 正交分析', generate: '⚙️ 生成候选',
    quick_test: '🧪 Quick Test', full_sim: '🔬 Full IS', tune_is: '🔧 调参',
    sc_submit: '📋 SC提交', submit: '📤 提交', done: '🏆 完成',
  };
  return names[phase] || phase;
}

function getPhaseEmoji(phase: string): string {
  const emojis: Record<string, string> = {
    init: '🔄', orthogonality: '📊', generate: '⚙️',
    quick_test: '🧪', full_sim: '🔬', tune_is: '🔧',
    sc_submit: '📋', submit: '📤', done: '🏆',
  };
  return emojis[phase] || '⏳';
}

// Build row layout for G6 — three-tier responsive
function getScaledLayout(width: number) {
  // Three tiers: mobile (<640), tablet (640-1024), desktop (>1024)
  const tier = width < 640 ? 'mobile' : width < 1024 ? 'tablet' : 'desktop';

  // Layout constants per tier
  const config: Record<string, { rowH: number; marginX: number; marginY: number; nodeW: number; nodeH: number; decisionW: number; decisionH: number; labelFs: number; labelOffY: number; labelLineH: number; labelMaxW: number; edgeLabelFs: number; edgeLabel: boolean; arrowSz: number }> = {
    mobile:    { rowH: 64, marginX: 24, marginY: 10, nodeW: 32, nodeH: 24, decisionW: 28, decisionH: 28, labelFs: 9, labelOffY: -8, labelLineH: 12, labelMaxW: 80, edgeLabelFs: 5, edgeLabel: false, arrowSz: 3 },
    tablet:    { rowH: 82, marginX: 48, marginY: 14, nodeW: 42, nodeH: 32, decisionW: 36, decisionH: 36, labelFs: 10, labelOffY: -10, labelLineH: 13, labelMaxW: 120, edgeLabelFs: 6, edgeLabel: true, arrowSz: 4 },
    desktop:   { rowH: 104, marginX: 80, marginY: 16, nodeW: 54, nodeH: 40, decisionW: 40, decisionH: 40, labelFs: 12, labelOffY: -14, labelLineH: 15, labelMaxW: 160, edgeLabelFs: 7, edgeLabel: true, arrowSz: 5 },
  };
  const c = config[tier];
  const isMobile = tier === 'mobile';

  const NODE_LAYOUT_Y: Record<string, number> = {
    'org_ortho': 0, 'dec_active20': 0, 'done': 0,
    'org_gen': 1, 'dec_mult': 1, 'act_phase0': 1, 'act_phase1': 1,
    'act_phase2': 1, 'act_dedup': 1, 'act_sd_score': 1, 'act_intra_div': 1, 'act_topn': 1,
    'org_quick_test': 2, 'dec_s': 2, 'act_skip': 2, 'act_fail': 2, 'act_pass_quick': 2,
    'org_full_is': 3, 'act_adaptive': 3, 'dec_is': 3, 'act_optimize': 3,
    'act_tune': 3, 'dec_tune_ok': 3, 'act_discard': 3,
    'org_sc': 4, 'dec_sc': 4, 'act_submit': 4, 'act_sc_tune': 4, 'dec_sc_ok': 4, 'act_sc_discard': 4,
    'org_stuck': 5, 'dec_stuck': 5, 'act_stuck_inc': 5, 'dec_stuck3': 5, 'act_stuck_mode': 5, 'act_loop': 5,
  };

  const rowLayout: Record<number, string[]> = {};
  for (const n of NODES) {
    const row = NODE_LAYOUT_Y[n.id] ?? 0;
    if (!rowLayout[row]) rowLayout[row] = [];
    rowLayout[row].push(n.id);
  }

  // For rows with many nodes, split into two sub-rows for horizontal spacing
  const splitRowLayout: Record<number, string[]> = {};
  for (const [rowStr, ids] of Object.entries(rowLayout)) {
    const row = Number(rowStr);
    // Split wide rows into sub-groups
    if (ids.length > 5) {
      const mid = Math.ceil(ids.length / 2);
      for (let i = 0; i < ids.length; i++) {
        const subRow = row * 10 + (i < mid ? 0 : 1); // e.g. 30 or 31
        if (!splitRowLayout[subRow]) splitRowLayout[subRow] = [];
        splitRowLayout[subRow].push(ids[i]);
      }
    } else if (ids.length > 3) {
      // Split into two: first half on main row, rest on sub-row
      const mid = Math.ceil(ids.length / 2);
      const firstHalf = ids.slice(0, mid);
      const secondHalf = ids.slice(mid);
      if (!splitRowLayout[row * 10]) splitRowLayout[row * 10] = firstHalf;
      if (secondHalf.length > 0) {
        const subRow = row * 10 + 1;
        if (!splitRowLayout[subRow]) splitRowLayout[subRow] = [];
        splitRowLayout[subRow] = secondHalf;
      }
    } else {
      if (!splitRowLayout[row]) splitRowLayout[row] = [];
      splitRowLayout[row].push(...ids);
    }
  }

  const nodePositions: Record<string, { x: number; y: number }> = {};
  for (const [rowStr, ids] of Object.entries(splitRowLayout)) {
    const row = Number(rowStr);
    const displayRow = Math.floor(row / 10);
    const subRow = row % 10;
    const count = ids.length;
    const usableWidth = width - c.marginX * 2;
    const spacing = count > 1 ? usableWidth / (count - 1) : 0;
    const rowY = c.marginY + (displayRow * 2 + subRow) * (c.rowH / 3); // finer vertical resolution
    ids.forEach((id, i) => {
      nodePositions[id] = {
        x: count > 1 ? c.marginX + spacing * i : width / 2,
        y: rowY,
      };
    });
  }

  return { nodePositions, isMobile, tier, totalHeight: c.marginY * 2 + 13 * (c.rowH / 3) + 16 };
}

export default function WorkflowGraph({ phase, activeCount, target, batchIndex, batchTotal }: WorkflowGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphWrapperRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<SVGSVGElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [isMobile, setIsMobile] = useState(true);
  const graphMounted = useRef(false);

  useEffect(() => {
    setIsMobile(window.innerWidth < 768);
    setExpanded(window.innerWidth >= 768);
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const updateWidth = () => {
      const w = el.clientWidth;
      setContainerWidth(w);
      setIsMobile(window.innerWidth < 768);
      if (window.innerWidth >= 768) setExpanded(true);
    };
    updateWidth();
    const observer = new ResizeObserver(updateWidth);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Layout computation — runs every phase/width change
  const layoutResult = expanded && containerWidth > 0
    ? getScaledLayout(containerWidth)
    : { nodePositions: {} as Record<string, { x: number; y: number }>, totalHeight: 300 };
  const { nodePositions, totalHeight } = layoutResult;

  const tier = containerWidth > 0
    ? (containerWidth < 640 ? 'mobile' : containerWidth < 1024 ? 'tablet' : 'desktop')
    : 'desktop';

  const isMobileView = tier === 'mobile';

  // Layout constants for styling
  const layoutStyle = {
    mobile: { nodeFont: 8, labelH: 11, minNodeW: 30, minNodeH: 22, decisionMinW: 26, decisionMinH: 26, rowVGap: 26, marginX: 8, marginY: 6, arrowSz: 3 },
    tablet: { nodeFont: 10, labelH: 13, minNodeW: 38, minNodeH: 30, decisionMinW: 32, decisionMinH: 32, rowVGap: 32, marginX: 16, marginY: 8, arrowSz: 4 },
    desktop: { nodeFont: 12, labelH: 15, minNodeW: 48, minNodeH: 36, decisionMinW: 40, decisionMinH: 40, rowVGap: 38, marginX: 24, marginY: 10, arrowSz: 5 },
  }[tier]!;

  const svgHeight = isMobileView ? Math.max(totalHeight + 80, 520) : Math.max(totalHeight, 300);

  // Cleanup
  useEffect(() => {
    return () => {};
  }, []);


  const activeIds = new Set(ACTIVE_IDS_FOR_PHASE[phase] || ['org_ortho']);
  const activeNodeLabels = NODES.filter(n => activeIds.has(n.id)).map(n => n.label).join(' → ');

  return (
    <div ref={containerRef} className="card p-3 md:p-4 animate-[fade-in_0.3s_ease-out]">
      {/* Header — always visible */}
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
          {/* Phase badge - shows current step */}
          <span className="text-[8px] md:text-[9px] text-indigo-300/70 truncate hidden sm:block">
            {getPhaseEmoji(phase)} {getPhaseName(phase)}
          </span>
          {/* Batch info */}
          {batchIndex != null && (
            <span className="bg-zinc-800/60 px-1.5 py-0.5 rounded text-[8px] md:text-[9px] text-gray-500 font-mono shrink-0">
              {batchIndex}/{batchTotal ?? '?'}
            </span>
          )}
          {/* Phase tag */}
          <span className={`px-1.5 py-0.5 rounded text-[8px] md:text-[9px] font-mono shrink-0 ${
            phase === 'done' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-indigo-500/10 text-indigo-400'
          }`}>
            {phase}
          </span>
          {/* Expand/collapse indicator - mobile only */}
          {isMobile && (
            <span className="text-zinc-600 text-[10px] ml-1 shrink-0 transition-transform duration-200"
              style={{ transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)' }}>
              ▼
            </span>
          )}
        </div>
      </div>

      {/* Collapsed mobile summary — shows the active path as a text trail */}
      {isMobile && !expanded && (
        <div className="mt-2 flex items-center gap-1 text-[9px] text-zinc-500 overflow-x-auto pb-1">
          <span className="shrink-0">{getPhaseEmoji(phase)}</span>
          <span className="text-indigo-400 font-mono truncate">{activeNodeLabels || phase}</span>
        </div>
      )}

      {/* Expanded content */}
      {expanded && (
        <>
          {/* Legend */}
          <div className="hidden sm:flex items-center gap-3 mt-2 mb-2 text-[9px] text-gray-600">
            <span className="flex items-center gap-1">
              <span className="inline-block w-2 h-2 rounded-sm bg-zinc-800 border border-indigo-500" /> Phase
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-2 h-2 rounded-sm bg-zinc-800 border border-amber-500" /> Decision
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-2 h-2 rounded-sm bg-zinc-800 border border-emerald-500" /> Action
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-2 h-2 rounded-sm bg-indigo-900 border border-indigo-400" /> Active
            </span>
            <span className="text-zinc-700 ml-auto hidden md:inline">Scroll to zoom · Drag to pan</span>
          </div>
          <div className="sm:hidden flex items-center gap-2 mt-1 mb-1 text-[8px] text-zinc-700">
            <span>I=indigo</span>
            <span>A=amber</span>
            <span>G=green</span>
            <span className="ml-auto">Pinch zoom</span>
          </div>

          {/* SVG Pipeline Graph */}
          <svg
            viewBox={`0 0 ${containerWidth} ${svgHeight}`}
            className="w-full rounded-lg bg-black/20"
            style={{ height: svgHeight, minHeight: 300 }}
            role="img"
            aria-label="Workflow Pipeline"
          >
            <defs>
              <marker id="arrow" markerWidth="6" markerHeight="4" refX="5" refY="2" orient="auto">
                <path d="M0,0 L6,2 L0,4 Z" fill={tier === 'mobile' ? '#444' : '#555'} />
              </marker>
              <marker id="arrowActive" markerWidth="6" markerHeight="4" refX="5" refY="2" orient="auto">
                <path d="M0,0 L6,2 L0,4 Z" fill="rgba(129,140,248,0.6)" />
              </marker>
            </defs>
            {/* Edges */}
            {EDGES.map((e, i) => {
              const src = nodePositions[e.source];
              const tgt = nodePositions[e.target];
              if (!src || !tgt) return null;
              const isActive = activeIds.has(e.source) || activeIds.has(e.target);
              return (
                <line
                  key={i}
                  x1={src.x} y1={src.y}
                  x2={tgt.x} y2={tgt.y}
                  stroke={isActive ? 'rgba(129,140,248,0.4)' : 'rgba(255,255,255,0.05)'}
                  strokeWidth={isActive ? 1 : 0.5}
                  markerEnd={isActive ? 'url(#arrowActive)' : 'url(#arrow)'}
                />
              );
            })}
            {/* Nodes */}
            {NODES.map(n => {
              const pos = nodePositions[n.id];
              if (!pos) return null;
              const isActive = activeIds.has(n.id);
              const colors = isActive ? ACTIVE_COLORS : NODE_COLORS[n.type];
              const isDec = n.type === 'decision';
              const hasSub = !!n.subtitle;
              // Node size based on content — ensures text fits inside
              const baseW = layoutStyle.minNodeW;
              const baseH = layoutStyle.minNodeH;
              const w = hasSub ? Math.max(baseW, 50) : baseW;
              const h = hasSub ? baseH * 1.6 : baseH;
              return (
                <g key={n.id}>
                  {isDec ? (
                    <rect
                      x={pos.x - w/2} y={pos.y - h/2}
                      width={w} height={h}
                      fill={colors.fill} stroke={colors.stroke}
                      strokeWidth={isActive ? 2 : 1.2}
                      rx={4}
                      transform={`rotate(45, ${pos.x}, ${pos.y})`}
                    />
                  ) : (
                    <rect
                      x={pos.x - w/2} y={pos.y - h/2}
                      width={w} height={h}
                      fill={colors.fill} stroke={colors.stroke}
                      strokeWidth={isActive ? 2 : 1.2}
                      rx={6}
                    />
                  )}
                  {/* Subtitle — above label when exists */}
                  {hasSub && (
                    <text
                      x={pos.x} y={pos.y - 3}
                      textAnchor="middle"
                      dominantBaseline="central"
                      fill={colors.label}
                      opacity={0.55}
                      fontSize={layoutStyle.nodeFont - 2}
                      fontFamily="'JetBrains Mono', 'SF Mono', monospace"
                      style={{ pointerEvents: 'none', userSelect: 'none' }}
                    >
                      {n.subtitle}
                    </text>
                  )}
                  {/* Main label — centered */}
                  <text
                    x={pos.x} y={hasSub ? pos.y + 5 : pos.y}
                    textAnchor="middle"
                    dominantBaseline="central"
                    fill={colors.label}
                    fontSize={isActive ? layoutStyle.nodeFont : layoutStyle.nodeFont - 1}
                    fontFamily="'JetBrains Mono', 'SF Mono', monospace"
                    fontWeight={isActive ? 700 : 400}
                    style={{ pointerEvents: 'none', userSelect: 'none' }}
                  >
                    {n.label}
                  </text>
                </g>
              );
            })}
          </svg>
        </>
      )}
    </div>
  );
}
