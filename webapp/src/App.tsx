import { useState, useEffect, useCallback, useMemo } from 'react';
import { Header } from './components/Header';
import { Chat } from './components/Chat';
import { FloorPlan } from './components/FloorPlan';
import { Robots } from './components/Robots';
import { ETA } from './components/ETA';
import { InjuryReport } from './components/InjuryReport';
// import { MedicalAttention } from './components/MedicalAttention';
// import { RobotStatus } from './components/RobotStatus';
import { fetchLatest, snapshotLatestUrl, postOperatorMessage } from './api/client';
import type { CommsMessage, MedicalAssessment, LatestResponse, CommsEntry, IncidentReport } from './api/types';
import { nowT } from './utils/format';
import DebugPage from './DebugPage';

const POLL_MS = 2000;
const FEED_REFRESH_MS = 1000; // Refresh robot feed image every 1s so it updates continuously

function commsToMessages(comms: CommsEntry[]): CommsMessage[] {
  const roleToType = (r: string): CommsMessage['type'] =>
    r === 'victim' ? 'v' : r === 'robot' ? 'h' : r === 'operator' ? 'op' : 'h';
  return comms.map((c) => ({
    id: c.id,
    type: roleToType(c.role),
    text: c.text,
    t: c.timestamp ? c.timestamp.slice(11, 16) : '',
  }));
}

function CommandCenterPage() {
  const [loading, setLoading] = useState(false);
  const [latest, setLatest] = useState<LatestResponse | null>(null);
  const [snapshotKey, setSnapshotKey] = useState(0);
  const [feedTick, setFeedTick] = useState(0); // Bump every 1s so robot feed img refetches
  const [optimisticMsgs, setOptimisticMsgs] = useState<CommsMessage[]>([]);
  // Keep last report visible once robot creates it (don't clear when poll returns null)
  const [lastReport, setLastReport] = useState<IncidentReport | null>(null);

  const msgs = useMemo(() => {
    const fromServer = commsToMessages(latest?.comms ?? []);
    const combined = [...fromServer, ...optimisticMsgs];
    if (combined.length === 0) {
      return [{ id: 0, type: 'sys' as const, text: 'Comms connected. Send a message or quick-reply for robot to speak.' }];
    }
    return combined;
  }, [latest?.comms, optimisticMsgs]);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const data = await fetchLatest();
        if (!cancelled) {
          setLatest(data);
          setSnapshotKey((k) => k + 1);
          if (data.report) setLastReport(data.report);
          setOptimisticMsgs((prev) => {
            if (prev.length === 0) return prev;
            const serverTexts = new Set((data.comms ?? []).map((c) => c.text));
            return prev.filter((p) => !serverTexts.has(p.text));
          });
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

  // Refresh robot feed image every second so it stays continuously updating
  useEffect(() => {
    const id = setInterval(() => setFeedTick((t) => t + 1), FEED_REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  const handleSend = useCallback(async (text: string) => {
    setLoading(true);
    setOptimisticMsgs((p) => [...p, { id: -Date.now(), type: 'op', text, t: nowT() }]);
    try {
      await postOperatorMessage(text);
    } catch (err) {
      setOptimisticMsgs((prev) => prev.filter((m) => m.text !== text || m.type !== 'op'));
      setOptimisticMsgs((p) => [...p, { id: Date.now(), type: 'sys', text: `Send failed: ${err instanceof Error ? err.message : String(err)}` }]);
    } finally {
      setLoading(false);
    }
  }, []);

  const snapshotUrl = latest
    ? `${snapshotLatestUrl()}?t=${snapshotKey}&r=${feedTick}`
    : null;
  const robotXY = useMemo(() => {
    const e = latest?.event;
    if (e && typeof e.robot_map_x === 'number' && typeof e.robot_map_y === 'number') {
      return { x: e.robot_map_x, y: e.robot_map_y };
    }
    return { x: 325, y: 430 };
  }, [latest?.event?.robot_map_x, latest?.event?.robot_map_y]);

  return (
    <div className="h-screen flex flex-col bg-base-950 text-base-200 font-sans">
      <Header />
      <main className="flex-1 grid grid-cols-[260px_1fr_200px] grid-rows-[3fr_2fr] gap-1.5 p-1.5 overflow-hidden min-h-0">
        <div className="row-span-2 min-h-0">
          <Chat msgs={msgs} onSend={handleSend} loading={loading} />
        </div>
        <div className="min-h-0">
          <FloorPlan robotXY={robotXY} />
        </div>
        <div className="row-span-2 min-h-0">
          <Robots />
        </div>
        <div className="grid grid-cols-2 gap-1.5 min-h-0">
          <ETA snapshotUrl={snapshotUrl} />
          <InjuryReport 
            medical={lastReport ? {
              injuryReport: `🩺 Priority: ${lastReport.patient_summary?.triage_priority || 'HIGH'}\n📍 Location: ${lastReport.patient_summary?.injury_location || 'right leg'}\n🩸 Bleeding: ${lastReport.patient_summary?.bleeding || 'yes'}\n😣 Pain: ${lastReport.patient_summary?.pain_level || '8'}/10`,
              severity: (lastReport.patient_summary?.triage_priority as any) || 'MODERATE',
              medicalAttention: ['Bleeding control', 'Suspected fracture', 'Neurovascular intact'],
              followUp: 'Click to view full report'
            } : null}
            reportPath={lastReport?.report_path}
            pdfPath={lastReport?.pdf_path}
          />
        </div>
      </main>
    </div>
  );
}

export default function App() {
  const isDebug = typeof window !== 'undefined' && window.location.pathname.startsWith('/debug');
  return isDebug ? <DebugPage /> : <CommandCenterPage />;
}
