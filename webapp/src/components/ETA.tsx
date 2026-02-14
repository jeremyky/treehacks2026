import { useState, useEffect } from 'react';

const pad = (n: number) => String(n).padStart(2, '0');

export function ETA() {
  const [s, setS] = useState(720);
  useEffect(() => {
    const i = setInterval(() => setS((e) => Math.max(0, e - 1)), 1000);
    return () => clearInterval(i);
  }, []);
  const m = Math.floor(s / 60);
  const sec = pad(s % 60);

  return (
    <div className="bg-base-900 border border-base-700 rounded p-3 h-full flex flex-col items-center justify-center font-mono">
      <div className="text-[9px] uppercase tracking-widest text-base-500 mb-2">ETA</div>
      <div className="text-3xl font-bold text-base-100 tracking-tight">
        {m}:{sec}
      </div>
    </div>
  );
}
