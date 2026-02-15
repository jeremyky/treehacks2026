export function ETA() {
  return (
    <div className="bg-base-900 border-2 border-base-700 rounded p-4 h-full flex flex-col items-center justify-center font-mono">
      <div className="text-[14px] uppercase tracking-widest text-base-500 mb-3">Camera Feed</div>
      <div className="flex-1 w-full flex items-center justify-center rounded border-2 border-dashed border-base-700 bg-base-850">
        <span className="text-[16px] text-base-500 italic">Camera loading...</span>
      </div>
    </div>
  );
}
