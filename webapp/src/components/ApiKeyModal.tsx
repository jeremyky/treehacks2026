import { useState } from 'react';

type Props = { onSave: (key: string) => void };

export function ApiKeyModal({ onSave }: Props) {
  const [key, setKey] = useState('');
  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center">
      <div className="bg-base-800 border border-base-600 rounded-lg p-6 w-[420px]">
        <div className="text-[11px] font-mono uppercase tracking-widest text-base-400 mb-1">
          Configuration Required
        </div>
        <div className="text-[13px] text-base-200 mb-4">
          Enter your OpenAI API key. It will be stored locally in your browser only.
        </div>
        <input
          className="w-full bg-base-950 border border-base-600 rounded px-3 py-2 text-[12px] text-base-200 font-mono outline-none focus:border-base-400 mb-3"
          placeholder="sk-proj-..."
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && key.trim() && onSave(key.trim())}
        />
        <button
          onClick={() => key.trim() && onSave(key.trim())}
          className="w-full bg-base-700 hover:bg-base-600 text-base-200 text-[11px] font-medium font-mono py-2 rounded transition-colors"
        >
          CONNECT
        </button>
      </div>
    </div>
  );
}
