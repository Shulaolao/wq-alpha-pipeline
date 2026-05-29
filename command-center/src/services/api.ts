// WQ Command Center — API client v2
import type { PipelineStatus, HistoryEvent } from '@/types/dashboard';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '';

export async function fetchStatus(): Promise<PipelineStatus> {
  const res = await fetch(`${API_BASE}/api/status`);
  if (!res.ok) throw new Error(`Status API: ${res.status}`);
  return res.json();
}

export async function fetchHistory(): Promise<{ total: number; events: HistoryEvent[] }> {
  const res = await fetch(`${API_BASE}/api/history`);
  if (!res.ok) throw new Error(`History API: ${res.status}`);
  return res.json();
}

export async function fetchLog(lines = 100): Promise<{ total: number; returned: number; entries: any[] }> {
  const res = await fetch(`${API_BASE}/api/log?lines=${lines}`);
  if (!res.ok) throw new Error(`Log API: ${res.status}`);
  return res.json();
}

export async function fetchOrthogonality(): Promise<{ nodes: any[]; edges: any[]; node_count: number; edge_count: number; sim_min: number; sim_max: number; sim_avg: number }> {
  const res = await fetch(`${API_BASE}/api/orthogonality`);
  if (!res.ok) throw new Error(`Orthogonality API: ${res.status}`);
  return res.json();
}

export async function fetchBatch(): Promise<any> {
  const res = await fetch(`${API_BASE}/api/batch`);
  if (!res.ok) throw new Error(`Batch API: ${res.status}`);
  return res.json();
}

export async function fetchActives(): Promise<{ total: number; target: number; remaining: number; pct: number; alphas: any[] }> {
  const res = await fetch(`${API_BASE}/api/actives`);
  if (!res.ok) throw new Error(`Actives API: ${res.status}`);
  return res.json();
}