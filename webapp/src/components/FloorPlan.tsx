// L-shaped floor plan: Courtyard (top, 8ft wide x 5ft) + Hallway (bottom-right, 3ft wide x 5ft)
// Scale: 50px per foot. Total bounding box ≈ 8ft x 10ft = 400px x 500px
// Robot path: straight 5ft north → 90° left → 3ft west → victim

const VICTIM_XY = { x: 175, y: 200 };

type Props = { robotXY?: { x: number; y: number } };

export function FloorPlan({ robotXY = { x: 325, y: 430 } }: Props) {
  // Path waypoints: robot → north 5ft → corner → west 3ft → victim
  const cornerX = robotXY.x;
  const cornerY = VICTIM_XY.y;

  return (
    <div className="flex flex-col h-full bg-base-900 border-2 border-base-700 rounded overflow-hidden">
      <div className="px-3 py-2 border-b border-base-700 flex items-center justify-between shrink-0">
        <span className="text-[14px] font-semibold uppercase tracking-widest text-base-400 font-mono">
          Emergency Response Map
        </span>
        <div className="flex items-center gap-3 text-[13px] font-mono text-base-500">
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-blue-500/70" /> Robot
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-red-500/70" /> Victim
          </span>
        </div>
      </div>
      <div className="flex-1 flex items-center justify-center p-3 overflow-hidden">
        <svg viewBox="-50 -50 500 600" className="w-full h-full" style={{ maxHeight: '100%' }}>
          <defs>
            <pattern id="grid-pattern" width="16" height="16" patternUnits="userSpaceOnUse">
              <path d="M16 0L0 0 0 16" fill="none" stroke="#c3cddb" strokeWidth="0.4" />
            </pattern>
          </defs>

          {/* Background */}
          <rect x="-50" y="-50" width="500" height="600" fill="#e8edf4" />
          <rect x="-50" y="-50" width="500" height="600" fill="url(#grid-pattern)" />

          {/* L-shape outline */}
          <path
            d="M0,0 L400,0 L400,500 L250,500 L250,250 L0,250 Z"
            fill="none"
            stroke="#8a9ab5"
            strokeWidth="1.5"
          />

          {/* Courtyard fill — top area, 8ft x 5ft */}
          <rect x="0" y="0" width="400" height="250" rx="2" fill="#d6e2ec" stroke="#9ab0c8" strokeWidth="0.8" />

          {/* Hallway fill — bottom-right, 3ft x 5ft */}
          <rect x="250" y="250" width="150" height="250" rx="2" fill="#dce0e8" stroke="#a8b0c0" strokeWidth="0.8" />

          {/* Area labels */}
          <text
            x="125"
            y="70"
            textAnchor="middle"
            fill="#506880"
            style={{ fontSize: '12px', fontWeight: 600, fontFamily: 'JetBrains Mono, monospace', letterSpacing: '2px' }}
          >
            COURTYARD
          </text>
          <text
            x="125"
            y="92"
            textAnchor="middle"
            fill="#7088a0"
            style={{ fontSize: '7px', fontFamily: 'JetBrains Mono, monospace', letterSpacing: '1px' }}
          >
            Jen-Hsun Huang Engineering Center
          </text>

          <text
            x="325"
            y="380"
            textAnchor="middle"
            fill="#586878"
            style={{ fontSize: '10px', fontWeight: 600, fontFamily: 'JetBrains Mono, monospace', letterSpacing: '2px' }}
          >
            HALLWAY
          </text>

          {/* Dotted path: robot → north 5ft → corner → west 3ft → victim */}
          <path
            d={`M${robotXY.x},${robotXY.y} L${cornerX},${cornerY} L${VICTIM_XY.x},${VICTIM_XY.y}`}
            fill="none"
            stroke="#3b82f6"
            strokeWidth="1.5"
            strokeDasharray="5,4"
            opacity="0.5"
          />

          {/* Corner marker */}
          <circle cx={cornerX} cy={cornerY} r="2" fill="#3b82f6" opacity="0.3" />

          {/* Victim */}
          <circle
            cx={VICTIM_XY.x}
            cy={VICTIM_XY.y}
            r="8"
            fill="none"
            stroke="#ef4444"
            strokeWidth="1"
            opacity="0.4"
            className="animate-ping-ring"
            style={{ transformOrigin: `${VICTIM_XY.x}px ${VICTIM_XY.y}px` }}
          />
          <circle cx={VICTIM_XY.x} cy={VICTIM_XY.y} r="4" fill="#ef4444" opacity="0.8" />
          <text
            x={VICTIM_XY.x}
            y={VICTIM_XY.y - 13}
            textAnchor="middle"
            fill="#dc2626"
            style={{ fontSize: '8px', fontWeight: 600, fontFamily: 'JetBrains Mono, monospace', opacity: 0.8 }}
          >
            VIC
          </text>

          {/* Robot */}
          <circle
            cx={robotXY.x}
            cy={robotXY.y}
            r="8"
            fill="none"
            stroke="#3b82f6"
            strokeWidth="1"
            opacity="0.25"
            className="animate-ping-ring"
            style={{ transformOrigin: `${robotXY.x}px ${robotXY.y}px` }}
          />
          <rect
            x={robotXY.x - 7}
            y={robotXY.y - 6}
            width="14"
            height="12"
            rx="2"
            fill="#3b82f6"
            opacity="0.75"
            stroke="#2563eb"
            strokeWidth="0.5"
          />
          <circle cx={robotXY.x - 3} cy={robotXY.y + 0.5} r="1.5" fill="#fff" opacity="0.7" />
          <circle cx={robotXY.x + 3} cy={robotXY.y + 0.5} r="1.5" fill="#fff" opacity="0.7" />
          <text
            x={robotXY.x}
            y={robotXY.y - 13}
            textAnchor="middle"
            fill="#2563eb"
            style={{ fontSize: '8px', fontWeight: 600, fontFamily: 'JetBrains Mono, monospace', opacity: 0.7 }}
          >
            R-01
          </text>

          {/* Scale bar — 2ft = 100px */}
          <line x1="300" y1="530" x2="400" y2="530" stroke="#7a8a9e" strokeWidth="0.5" />
          <line x1="300" y1="526" x2="300" y2="534" stroke="#7a8a9e" strokeWidth="0.5" />
          <line x1="400" y1="526" x2="400" y2="534" stroke="#7a8a9e" strokeWidth="0.5" />
          <text
            x="350"
            y="545"
            textAnchor="middle"
            fill="#6a7a90"
            style={{ fontSize: '7px', fontFamily: 'JetBrains Mono, monospace' }}
          >
            2 ft
          </text>
        </svg>
      </div>
    </div>
  );
}
