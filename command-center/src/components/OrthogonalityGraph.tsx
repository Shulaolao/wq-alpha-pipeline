'use client';

import { useEffect, useRef, useState } from 'react';
import { Graph } from '@antv/g6';

interface OrthogonalityData {
  nodes: { id: string; expr: string; fields: string[] }[];
  edges: { source: string; target: string; similarity: number }[];
  node_count?: number;
  edge_count?: number;
  sim_min?: number;
  sim_max?: number;
  sim_avg?: number;
}

interface OrthogonalityGraphProps {
  data: OrthogonalityData | null;
  loading?: boolean;
}

export default function OrthogonalityGraph({ data, loading }: OrthogonalityGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current || !data || data.nodes.length === 0) return;

    // Destroy previous graph
    if (graphRef.current) {
      graphRef.current.destroy();
      graphRef.current = null;
    }

    const width = containerRef.current.clientWidth || 500;
    const height = containerRef.current.clientHeight || 400;

    // Color by similarity clusters
    const nodeMap = new Map(data.nodes.map(n => [n.id, n]));

    const graph = new Graph({
      container: containerRef.current,
      width,
      height,
      animation: false,
      autoFit: 'view',
      layout: {
        type: 'force',
        preventOverlap: true,
        nodeStrength: -200,
        edgeStrength: (d: any) => {
          const sim = d.data?.similarity || 0;
          return sim * 3;
        },
        linkDistance: (d: any) => {
          const sim = d.data?.similarity || 0.1;
          return 200 - sim * 150;
        },
      },
      node: {
        type: 'circle',
        style: {
          size: (d: any) => {
            const node = nodeMap.get(d.id);
            return node ? Math.max(16, Math.min(32, 12 + (node.fields?.length || 0) * 3)) : 20;
          },
          fill: (d: any) => {
            const node = nodeMap.get(d.id);
            const fields = node?.fields || [];
            if (fields.includes('revenue')) return '#818cf8';
            if (fields.includes('close')) return '#34d399';
            if (fields.includes('volume')) return '#f59e0b';
            if (fields.includes('high')) return '#22d3ee';
            if (fields.includes('cap')) return '#f472b6';
            return '#6b7280';
          },
          stroke: '#1e1e36',
          lineWidth: 2,
          labelText: (d: any) => d.id,
          labelFill: '#e2e8f0',
          labelFontSize: 9,
          labelFontFamily: 'JetBrains Mono, monospace',
          labelPlacement: 'bottom',
          labelOffsetY: 4,
        },
      },
      edge: {
        type: 'line',
        style: {
          stroke: (d: any) => {
            const sim = d.data?.similarity || 0;
            if (sim > 0.4) return 'rgba(129, 140, 248, 0.6)';
            if (sim > 0.2) return 'rgba(129, 140, 248, 0.3)';
            return 'rgba(255,255,255,0.06)';
          },
          lineWidth: (d: any) => {
            const sim = d.data?.similarity || 0;
            return Math.max(0.5, sim * 3);
          },
        },
      },
      behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element'],
    });

    graph.setData({
      nodes: data.nodes.map(n => ({ id: n.id, data: { ...n } })),
      edges: data.edges.map(e => ({
        id: `${e.source}-${e.target}`,
        source: e.source,
        target: e.target,
        data: { ...e },
      })),
    });

    graph.render();

    graph.on('node:click', (evt: any) => {
      const id = evt.targetId || evt.itemId;
      setSelectedNode(id === selectedNode ? null : id);
    });

    graphRef.current = graph;

    // Handle resize
    const handleResize = () => {
      if (containerRef.current && graphRef.current) {
        const w = containerRef.current.clientWidth;
        const h = containerRef.current.clientHeight;
        graphRef.current.setSize(w, h);
        graphRef.current.fitView();
      }
    };

    const observer = new ResizeObserver(handleResize);
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      if (graphRef.current) {
        graphRef.current.destroy();
        graphRef.current = null;
      }
    };
  }, [data]);

  const selectedData = selectedNode && data
    ? data.nodes.find(n => n.id === selectedNode)
    : null;

  return (
    <div className="card p-4">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500 mb-3 flex items-center gap-2">
        <span>⧉</span> Field Orthogonality
        {data && (
          <span className="text-gray-600 font-normal text-[10px]">
            {data.nodes.length} nodes · {data.edges.length} edges
            {data.sim_avg != null && (
              <span className="ml-1.5 text-gray-700">
                · sim avg {data.sim_avg.toFixed(3)} · max {data.sim_max?.toFixed(3)}
              </span>
            )}
          </span>
        )}
      </h2>

      <div className="flex flex-col lg:flex-row gap-3">
        {/* Main graph area */}
        <div
          ref={containerRef}
          className={`flex-1 h-72 lg:h-96 rounded-lg overflow-hidden ${loading ? 'opacity-40' : ''}`}
        />

        {/* Info panel */}
        {selectedData && (
          <div className="lg:w-64 bg-black/20 rounded-lg p-3 text-xs space-y-2 shrink-0">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold text-indigo-400 font-mono">{selectedData.id}</span>
              <button
                onClick={() => setSelectedNode(null)}
                className="text-gray-600 hover:text-gray-400 text-[10px]"
              >
                ✕
              </button>
            </div>
            <div className="text-gray-400 break-all leading-relaxed font-mono text-[10px]">
              {selectedData.expr}
            </div>
            <div>
              <div className="text-gray-600 text-[10px] mb-1 uppercase tracking-wider">Fields</div>
              <div className="flex flex-wrap gap-1">
                {selectedData.fields.map(f => (
                  <span key={f} className="bg-indigo-500/10 text-indigo-400 px-1.5 py-0.5 rounded text-[9px]">
                    {f}
                  </span>
                ))}
              </div>
            </div>
            <div>
              <div className="text-gray-600 text-[10px] mb-1 uppercase tracking-wider">Connected to</div>
              {data && data.edges
                .filter(e => e.source === selectedNode || e.target === selectedNode)
                .sort((a, b) => b.similarity - a.similarity)
                .slice(0, 5)
                .map(e => {
                  const other = e.source === selectedNode ? e.target : e.source;
                  return (
                    <div key={other} className="flex justify-between text-[10px] py-0.5">
                      <span className="text-gray-400 font-mono">{other}</span>
                      <span className="text-gray-500">sim {e.similarity.toFixed(3)}</span>
                    </div>
                  );
                })}
            </div>
          </div>
        )}
      </div>

      {!selectedData && data && data.nodes.length > 0 && (
        <div className="text-[10px] text-gray-600 mt-2 text-center">
          Click a node to see details
        </div>
      )}
    </div>
  );
}