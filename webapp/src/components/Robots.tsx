import { useState } from 'react';

const ACTIVE_ROBOTS = [
  { id: 1, name: 'Robot 1', task: 'Debris removal', bat: 64 },
  { id: 2, name: 'Robot 2', task: 'Area scan', bat: 81 },
  { id: 3, name: 'Robot 3', task: 'Perimeter', bat: 73 },
  { id: 4, name: 'Robot 4', task: 'Comms relay', bat: 90 },
];
const RESERVE_ROBOTS = [
  { id: 6, name: 'Robot 6' },
  { id: 7, name: 'Robot 7' },
];

export function Robots() {
  const [sel, setSel] = useState(1);
  return (
    <div className="flex flex-col h-full bg-base-900 border-2 border-base-700 rounded overflow-hidden">
      <div className="px-3 py-2 border-b border-base-700 shrink-0">
        <span className="text-[14px] font-semibold uppercase tracking-widest text-base-400 font-mono">
          Units
        </span>
      </div>
      <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-1">
        <div className="text-[13px] uppercase tracking-widest text-base-500 font-mono px-1 mb-0.5">
          Active
        </div>
        {ACTIVE_ROBOTS.map((r) => (
          <button
            key={r.id}
            onClick={() => setSel(r.id)}
            className={`w-full text-left px-3 py-2.5 rounded border transition-all text-[15px] ${
              sel === r.id
                ? 'bg-base-800 border-base-600 text-base-100'
                : 'bg-transparent border-transparent text-base-300 hover:bg-base-850'
            }`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/70" />
                <span className="font-mono font-medium">{r.name}</span>
              </div>
              <span className="font-mono text-[14px] text-base-500">{r.bat}%</span>
            </div>
            <div className="text-[14px] text-base-500 ml-4.5 font-mono">{r.task}</div>
          </button>
        ))}
        <div className="text-[13px] uppercase tracking-widest text-base-500 font-mono px-1 mt-2 mb-0.5">
          Reserve
        </div>
        {RESERVE_ROBOTS.map((r) => (
          <button
            key={r.id}
            onClick={() => setSel(r.id)}
            className={`w-full text-left px-3 py-2.5 rounded border transition-all text-[15px] ${
              sel === r.id
                ? 'bg-base-800 border-base-600 text-base-100'
                : 'bg-transparent border-transparent text-base-400 hover:bg-base-850'
            }`}
          >
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-base-500" />
              <span className="font-mono">{r.name}</span>
              <span className="text-[13px] text-base-500 font-mono ml-auto">STBY</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
