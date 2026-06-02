// WQ Command Center — API client v2
import type { PipelineStatus } from '@/types/dashboard';

export interface HistoryEvent {
  name: string;
  event_type: string;
  timestamp?: string;
  created_at?: string;
  sharpe?: number | null;
  fitness?: number | null;
  sc_value?: number | null;
  sc_result?: string | null;
  is_status?: string | null;
  phase?: string | null;
  alpha_id?: string | null;
  duration?: number | null;
}

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

export interface AlphaSummary {
  name: string;
  expr: string;
  alpha_id: string | null;
  sharpe: number | null;
  fitness: number | null;
  sc_value: number | null;
  sc_result: string | null;
  is_status: string | null;
  status: string;
  total_attempts: number;
  first_generated_at: string | null;
  last_milestone_at: string | null;
  last_updated: string;
  state_chain: { event_type: string; sharpe: number | null; fitness: number | null; sc_value: number | null; created_at: string }[];
  chain_length: number;
}

export async function fetchCompleteAlphas(limit = 200, offset = 0): Promise<{ total: number; alphas: AlphaSummary[] }> {
  const res = await fetch(`${API_BASE}/api/alphas/complete?limit=${limit}&offset=${offset}`);
  if (!res.ok) throw new Error(`Complete Alphas API: ${res.status}`);
  return res.json();
}