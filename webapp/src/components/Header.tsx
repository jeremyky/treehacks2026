import { useState, useEffect } from 'react';
import { fmtTime } from '../utils/format';

export function Header() {
  const [clk, setClk] = useState('');
  const [el, setEl] = useState(6443);
  const isDebug = typeof window !== 'undefined' && window.location.pathname.startsWith('/debug');

  useEffect(() => {
    const t = () => setClk(new Date().toUTCString().split(' ')[4] + 'Z');
    t();
    const i = setInterval(t, 1000);
    return () => clearInterval(i);
  }, []);
  useEffect(() => {
    const i = setInterval(() => setEl((e) => e + 1), 1000);
    return () => clearInterval(i);
  }, []);

  return (
    <header className="h-10 bg-base-900 border-b border-base-700 flex items-center justify-between px-4 shrink-0 font-mono">
      <div className="flex items-center gap-3">
        <span className="text-[11px] font-semibold tracking-wider text-base-200">ADAM-OPS</span>
        <nav className="flex items-center gap-1.5">
          <a
            href="/"
            className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
              isDebug
                ? 'border-base-700 bg-base-900 text-base-400 hover:bg-base-800 hover:text-base-200'
                : 'border-amber-400/60 bg-base-950 text-base-200'
            }`}
          >
            Command
          </a>
          <a
            href="/debug"
            className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
              isDebug
                ? 'border-amber-400/60 bg-base-950 text-base-200'
                : 'border-base-700 bg-base-900 text-base-400 hover:bg-base-800 hover:text-base-200'
            }`}
          >
            Debug
          </a>
        </nav>
      </div>
      <div className="flex items-center gap-5 text-[10px] text-base-400 tracking-wide">
        <span>{clk}</span>
        <span>
          T+ <span className="text-base-200">{fmtTime(el)}</span>
        </span>
      </div>
    </header>
  );
}
