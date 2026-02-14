import { useState, useEffect, useRef } from 'react';
import type { CommsMessage } from '../api/types';

const QUICK_REPLIES = [
  'Are you hurt?',
  'Can you move?',
  'Help is on the way',
  'Stay calm',
  'Where are you?',
];

type Props = {
  msgs: CommsMessage[];
  onSend: (text: string) => void;
  loading: boolean;
};

export function Chat({ msgs, onSend, loading }: Props) {
  const [inp, setInp] = useState('');
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [msgs]);

  const send = () => {
    const t = inp.trim();
    if (!t || loading) return;
    onSend(t);
    setInp('');
  };

  return (
    <div className="flex flex-col h-full bg-base-900 border border-base-700 rounded overflow-hidden">
      <div className="px-3 py-1.5 border-b border-base-700 flex items-center justify-between shrink-0">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-base-400 font-mono">
          Comms
        </span>
        <span className="text-[9px] text-emerald-500/70 font-mono tracking-wide">RELAY ON</span>
      </div>
      <div
        ref={ref}
        className="flex-1 overflow-y-auto px-3 py-2 flex flex-col gap-1.5 min-h-0"
      >
        {msgs.map((m) => (
          <div
            key={m.id}
            className={`flex flex-col ${
              m.type === 'h' || m.type === 'op' ? 'items-end' : m.type === 'sys' ? 'items-center' : 'items-start'
            }`}
          >
            {m.type === 'sys' ? (
              <span className="text-[10px] text-base-500 font-mono py-0.5">{m.text}</span>
            ) : (
              <>
                <span className="text-[9px] font-mono tracking-wide mb-0.5 text-base-500">
                  {m.type === 'v' ? 'VICTIM' : m.type === 'op' ? 'OPERATOR' : 'ROBOT 1'} {m.t ?? ''}
                </span>
                <div
                  className={`max-w-[88%] px-2.5 py-1.5 text-[12px] leading-snug rounded ${
                    m.type === 'v'
                      ? 'bg-base-800 border border-base-700 text-base-200'
                      : m.type === 'op'
                        ? 'bg-base-700 border border-base-600 text-amber-200/90'
                        : 'bg-base-750 border border-base-600 text-base-200'
                  }`}
                >
                  {m.text}
                </div>
              </>
            )}
          </div>
        ))}
        {loading && (
          <div className="flex items-center gap-2 py-1">
            <div className="w-3 h-3 border border-base-500 border-t-base-200 rounded-full animate-spin-slow" />
            <span className="text-[10px] text-base-500 font-mono">Analyzing...</span>
          </div>
        )}
      </div>
      <div className="flex flex-wrap gap-1 px-2 pt-2 border-t border-base-700 shrink-0">
        {QUICK_REPLIES.map((q) => (
          <button
            key={q}
            onClick={() => !loading && onSend(q)}
            disabled={loading}
            className="text-[10px] font-mono px-2 py-1 rounded border border-base-600 bg-base-800 text-base-300 hover:bg-base-700 hover:text-base-100 disabled:opacity-40 transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
      <div className="flex gap-1.5 p-2 shrink-0">
        <input
          className="flex-1 bg-base-950 border border-base-700 rounded px-2.5 py-1.5 text-[12px] text-base-200 outline-none focus:border-base-500 transition-colors font-sans"
          placeholder="Type to have robot say (or quick-reply below)..."
          value={inp}
          onChange={(e) => setInp(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          disabled={loading}
        />
        <button
          onClick={send}
          disabled={loading}
          className="bg-base-700 hover:bg-base-600 disabled:opacity-40 transition-colors text-base-300 px-3 rounded text-[11px] font-medium"
        >
          SEND
        </button>
      </div>
    </div>
  );
}
