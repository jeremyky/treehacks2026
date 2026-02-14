/** Command center API client. Uses /api when proxied (Vite), else VITE_COMMAND_CENTER_URL. */

import type { LatestResponse, MedicalAssessment, SnapshotHistoryResponse } from './types';

const BASE =
  (import.meta as unknown as { env: { VITE_COMMAND_CENTER_URL?: string } }).env
    .VITE_COMMAND_CENTER_URL ?? '/api';

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE.replace(/\/$/, '')}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json() as Promise<T>;
}

export async function fetchLatest(): Promise<LatestResponse> {
  return fetchJson<LatestResponse>('/latest');
}

/** URL for latest snapshot image (same-origin with proxy: /api/snapshot/latest). */
export function snapshotLatestUrl(): string {
  return `${BASE.replace(/\/$/, '')}/snapshot/latest`;
}

export async function fetchSnapshotHistory(limit = 80): Promise<SnapshotHistoryResponse> {
  const q = Number.isFinite(limit) ? `?limit=${encodeURIComponent(String(limit))}` : '';
  return fetchJson<SnapshotHistoryResponse>(`/snapshot/history${q}`);
}

export function absoluteCommandCenterUrl(pathOrUrl: string): string {
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl;
  return `${BASE.replace(/\/$/, '')}${pathOrUrl.startsWith('/') ? '' : '/'}${pathOrUrl}`;
}

export async function postOperatorMessage(text: string): Promise<{ status: string }> {
  return fetchJson<{ status: string }>('/operator-message', {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}

/** Call backend proxy to OpenAI for injury analysis (optional; can stay client-side). */
export async function analyzeInjuries(
  apiBase: string,
  apiKey: string,
  victimText: string,
  chatHistory: { type: string; text: string }[]
): Promise<MedicalAssessment> {
  const historyContext = chatHistory
    .filter((m) => m.type === 'v' || m.type === 'h')
    .map((m) => `${m.type === 'v' ? 'Victim' : 'Robot'}: ${m.text}`)
    .join('\n');

  const res = await fetch(`${apiBase}/analyze-injuries`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key: apiKey,
      victim_text: victimText,
      chat_history: chatHistory,
      history_context: historyContext,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { error?: string }).error ?? `API ${res.status}`);
  }
  return res.json() as Promise<MedicalAssessment>;
}

/** Client-side OpenAI call (original behavior) if no backend analyze endpoint. */
export async function analyzeInjuriesClient(
  apiKey: string,
  victimText: string,
  chatHistory: { type: string; text: string }[]
): Promise<MedicalAssessment> {
  const historyContext = chatHistory
    .filter((m) => m.type === 'v' || m.type === 'h')
    .map((m) => `${m.type === 'v' ? 'Victim' : 'Robot'}: ${m.text}`)
    .join('\n');

  const res = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: 'gpt-4o-mini',
      temperature: 0.3,
      messages: [
        {
          role: 'system',
          content: `You are a medical triage AI for a disaster rescue operation. A robot has found a victim and is relaying their messages. Based on the victim's description, provide a medical assessment.

Respond ONLY with valid JSON in this exact format:
{
  "injuryReport": "Describe the injuries identified based on the victim's description. Be specific about body parts, type of injury, and severity. Clinical tone, 2-4 sentences.",
  "medicalAttention": ["supply or action 1", "supply or action 2", "supply or action 3"],
  "severity": "CRITICAL" or "MODERATE" or "MINOR",
  "followUp": "A short follow-up question or instruction to relay to the victim"
}`,
        },
        {
          role: 'user',
          content: `Conversation so far:\n${historyContext}\n\nLatest from victim: "${victimText}"\n\nProvide medical triage assessment as JSON.`,
        },
      ],
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      (err as { error?: { message?: string } }).error?.message ?? `API ${res.status}`
    );
  }

  const data = (await res.json()) as { choices: { message: { content: string } }[] };
  const content = data.choices[0].message.content;
  const cleaned = content.replace(/```json\s*/g, '').replace(/```\s*/g, '').trim();
  return JSON.parse(cleaned) as MedicalAssessment;
}
