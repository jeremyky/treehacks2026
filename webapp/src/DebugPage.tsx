import { useEffect, useMemo, useState } from 'react';
import { Header } from './components/Header';
import { absoluteCommandCenterUrl, fetchLatest, fetchSnapshotHistory, snapshotLatestUrl } from './api/client';
import type { LatestResponse, SnapshotHistoryEntry } from './api/types';

const POLL_MS = 1000;
const HISTORY_POLL_MS = 1500;

function safeJson(x: unknown): string {
  try {
    return JSON.stringify(x, null, 2);
  } catch {
    return String(x);
  }
}

export default function DebugPage() {
  const [latest, setLatest] = useState<LatestResponse | null>(null);
  const [snapshotKey, setSnapshotKey] = useState(0);
  const [history, setHistory] = useState<SnapshotHistoryEntry[]>([]);
  const [selected, setSelected] = useState<SnapshotHistoryEntry | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const data = await fetchLatest();
        if (!cancelled) {
          setLatest(data);
          setSnapshotKey((k) => k + 1);
        }
      } catch {
        if (!cancelled) setLatest(null);
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const data = await fetchSnapshotHistory(120);
        if (!cancelled) {
          setHistory(data.snapshots ?? []);
        }
      } catch {
        if (!cancelled) setHistory([]);
      }
    };
    tick();
    const id = setInterval(tick, HISTORY_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const latestSnapshotUrl = useMemo(() => {
    return latest ? `${snapshotLatestUrl()}?t=${snapshotKey}` : null;
  }, [latest, snapshotKey]);

  const focusUrl = useMemo(() => {
    if (selected?.url) return absoluteCommandCenterUrl(selected.url);
    if (latestSnapshotUrl) return latestSnapshotUrl;
    return null;
  }, [latestSnapshotUrl, selected?.url]);

  const ev = latest?.event ?? null;
  const decision = (ev?.decision ?? null) as
    | {
        action?: string;
        mode?: string;
        say?: string | null;
        wait_for_response_s?: number | null;
        used_llm?: boolean;
        params?: Record<string, unknown>;
      }
    | null;

  const searchSub = (ev?.search_sub_phase as string | undefined) ?? '—';
  const searchRetries = (ev?.search_ask_retries as number | undefined) ?? 0;

  // All possible actions the robot can take
  const ALL_ACTIONS = ['stop', 'rotate_left', 'rotate_right', 'forward_slow', 'back_up', 'wait', 'ask', 'say'];
  const currentAction = decision?.action ?? '';

  return (
    <div className="h-screen flex flex-col bg-base-950 text-base-200 font-sans">
      <Header />
      <main className="flex-1 grid grid-cols-[1.1fr_0.9fr] gap-1.5 p-1.5 overflow-hidden min-h-0">
        {/* LEFT: camera + snapshot history */}
        <section className="min-h-0 flex flex-col bg-base-900 border border-base-700 rounded overflow-hidden">
          <div className="px-3 py-1.5 border-b border-base-700 flex items-center justify-between shrink-0">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-base-400 font-mono">
              Debug camera / snapshots
            </span>
            <span className="text-[9px] text-base-500 font-mono">
              {selected ? `Selected: ${selected.name}` : 'Selected: LIVE'}
            </span>
          </div>
          <div className="flex-1 min-h-0 grid grid-rows-[1fr_180px] gap-1.5 p-2">
            <div className="min-h-0 flex items-center justify-center rounded border border-base-700 bg-base-950 overflow-hidden">
              {focusUrl ? (
                <img src={focusUrl} alt="Debug snapshot" className="w-full h-full object-contain" />
              ) : (
                <div className="text-[10px] font-mono text-base-500">No snapshot yet</div>
              )}
            </div>
            <div className="min-h-0 rounded border border-base-700 bg-base-950 overflow-hidden flex flex-col">
              <div className="px-2.5 py-1 border-b border-base-800 text-[10px] font-mono text-base-500 shrink-0 flex items-center justify-between">
                <span>Snapshot history (from command center)</span>
                <button
                  className="text-[10px] font-mono px-2 py-0.5 rounded border border-base-700 bg-base-900 text-base-300 hover:bg-base-800 transition-colors"
                  onClick={() => setSelected(null)}
                >
                  LIVE
                </button>
              </div>
              <div className="flex-1 min-h-0 overflow-auto p-2 grid grid-cols-6 gap-2 content-start">
                {history.slice().reverse().map((h) => {
                  const url = h.url ? absoluteCommandCenterUrl(h.url) : '';
                  const metaEvent = (h.metadata?.event as string | undefined) ?? '';
                  const metaPhase = (h.metadata?.phase as string | undefined) ?? '';
                  const isSel = selected?.name === h.name;
                  return (
                    <button
                      key={`${h.name}-${h.received_at}`}
                      className={`rounded border overflow-hidden text-left bg-base-900 ${
                        isSel ? 'border-amber-400/70' : 'border-base-700 hover:border-base-500'
                      } transition-colors`}
                      onClick={() => setSelected(h)}
                      title={`${h.name}\n${h.received_at}\n${metaEvent}${metaPhase ? ` | ${metaPhase}` : ''}`}
                    >
                      <div className="aspect-[4/3] bg-base-950 flex items-center justify-center">
                        {url ? (
                          <img src={url} alt={h.name} className="w-full h-full object-cover" />
                        ) : (
                          <div className="text-[9px] font-mono text-base-600">no url</div>
                        )}
                      </div>
                      <div className="px-1.5 py-1">
                        <div className="text-[9px] font-mono text-base-400 truncate">{metaEvent || 'snapshot'}</div>
                        <div className="text-[9px] font-mono text-base-500 truncate">{metaPhase || h.name}</div>
                      </div>
                    </button>
                  );
                })}
                {history.length === 0 && (
                  <div className="col-span-6 text-[10px] font-mono text-base-600">
                    No snapshots received yet. Start the Python command center server + orchestrator and let it post frames.
                  </div>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* RIGHT: decision info, action list, comms, raw data */}
        <section className="min-h-0 flex flex-col gap-1.5 overflow-auto">
          {/* Action list – shows all available actions, highlights current */}
          <div className="bg-base-900 border border-base-700 rounded overflow-hidden shrink-0">
            <div className="px-3 py-1.5 border-b border-base-700 flex items-center justify-between">
              <span className="text-[10px] font-semibold uppercase tracking-widest text-base-400 font-mono">
                Action list
              </span>
              <span className="text-[9px] text-base-500 font-mono">
                chosen: {currentAction || '—'}
              </span>
            </div>
            <div className="p-2 flex flex-wrap gap-1.5">
              {ALL_ACTIONS.map((a) => {
                const isActive = a === currentAction;
                return (
                  <span
                    key={a}
                    className={`text-[10px] font-mono px-2.5 py-1 rounded border transition-colors ${
                      isActive
                        ? 'border-amber-400 bg-amber-400/15 text-amber-200 font-semibold'
                        : 'border-base-700 bg-base-950 text-base-500'
                    }`}
                  >
                    {a}
                  </span>
                );
              })}
            </div>
          </div>

          {/* Decision detail */}
          <div className="bg-base-900 border border-base-700 rounded overflow-hidden shrink-0">
            <div className="px-3 py-1.5 border-b border-base-700 flex items-center justify-between">
              <span className="text-[10px] font-semibold uppercase tracking-widest text-base-400 font-mono">
                Decision / LLM
              </span>
              <span className="text-[9px] text-base-500 font-mono">
                phase: {ev?.phase_label ?? ev?.phase ?? '—'}
              </span>
            </div>
            <div className="p-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[11px] font-mono">
              <div className="text-base-500">heard</div>
              <div className="text-base-200 break-words">{(ev?.last_response as string) ?? '—'}</div>
              <div className="text-base-500">action</div>
              <div className={`break-words ${currentAction ? 'text-amber-200 font-semibold' : 'text-base-200'}`}>
                {currentAction || '—'}
              </div>
              <div className="text-base-500">say</div>
              <div className="text-base-200 break-words">{decision?.say ?? '—'}</div>
              <div className="text-base-500">listen_s</div>
              <div className="text-base-200">
                {decision?.wait_for_response_s ?? '—'} {decision?.used_llm ? '(LLM)' : ''}
              </div>
              <div className="text-base-500">persons/conf</div>
              <div className="text-base-200">
                {typeof ev?.num_persons === 'number' ? ev.num_persons : '—'} /{' '}
                {typeof ev?.confidence === 'number' ? `${Math.round(ev.confidence * 100)}%` : '—'}
              </div>
              <div className="text-base-500">search step</div>
              <div className="text-base-200">
                <span className={searchSub === 'ask_location' ? 'text-cyan-300' : searchSub === 'basic_search' ? 'text-amber-300' : 'text-base-200'}>
                  {searchSub}
                </span>
                {searchSub === 'ask_location' && <span className="text-base-500 ml-2">(retries: {searchRetries}/2)</span>}
              </div>
              <div className="text-base-500">mode/next</div>
              <div className="text-base-200 break-words">{decision?.mode ?? '—'}</div>
            </div>
          </div>

          {/* Says / hears (comms) */}
          <div className="bg-base-900 border border-base-700 rounded overflow-hidden flex flex-col max-h-[200px] shrink-0">
            <div className="px-3 py-1.5 border-b border-base-700 flex items-center justify-between shrink-0">
              <span className="text-[10px] font-semibold uppercase tracking-widest text-base-400 font-mono">
                Says / hears (comms)
              </span>
              <span className="text-[9px] text-base-500 font-mono">
                {(latest?.comms?.length ?? 0) > 0 ? `${latest?.comms?.length ?? 0} msgs` : '—'}
              </span>
            </div>
            <div className="flex-1 min-h-0 overflow-auto p-2 space-y-1.5">
              {(latest?.comms ?? []).slice(-50).map((c) => (
                <div key={c.id} className="rounded border border-base-800 bg-base-950 px-2 py-1">
                  <div className="text-[9px] font-mono text-base-500">
                    {(c.role || '—').toUpperCase()} {c.timestamp ? c.timestamp.slice(11, 19) : ''}
                  </div>
                  <div className="text-[11px] font-mono text-base-200 whitespace-pre-wrap break-words">
                    {c.text}
                  </div>
                </div>
              ))}
              {(latest?.comms?.length ?? 0) === 0 && (
                <div className="text-[10px] font-mono text-base-600">
                  No comms yet.
                </div>
              )}
            </div>
          </div>

          {/* Raw payloads */}
          <div className="bg-base-900 border border-base-700 rounded overflow-hidden flex flex-col shrink-0">
            <div className="px-3 py-1.5 border-b border-base-700 flex items-center justify-between shrink-0">
              <span className="text-[10px] font-semibold uppercase tracking-widest text-base-400 font-mono">
                Raw payloads
              </span>
              <span className="text-[9px] text-base-500 font-mono">
                event keys: {ev ? Object.keys(ev).length : 0}
              </span>
            </div>
            <div className="grid grid-rows-2 gap-1.5 p-2" style={{ maxHeight: 300 }}>
              <div className="rounded border border-base-700 bg-base-950 overflow-hidden flex flex-col" style={{ maxHeight: 140 }}>
                <div className="px-2.5 py-1 border-b border-base-800 text-[10px] font-mono text-base-500 shrink-0">
                  llm_proposal
                </div>
                <pre className="flex-1 min-h-0 overflow-auto p-2 text-[10px] leading-snug text-base-200">
                  {safeJson(ev?.llm_proposal ?? null)}
                </pre>
              </div>
              <div className="rounded border border-base-700 bg-base-950 overflow-hidden flex flex-col" style={{ maxHeight: 140 }}>
                <div className="px-2.5 py-1 border-b border-base-800 text-[10px] font-mono text-base-500 shrink-0">
                  latest.event
                </div>
                <pre className="flex-1 min-h-0 overflow-auto p-2 text-[10px] leading-snug text-base-200">
                  {safeJson(ev)}
                </pre>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

