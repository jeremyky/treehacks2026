const ROOMS = [
  { id: 'pump', label: 'PUMP RM', x: 0, y: 0, w: 155, h: 125, c: '#2a3a3a' },
  { id: 'cold', label: 'COLD RM', x: 165, y: 0, w: 135, h: 125, c: '#2a2a3a' },
  { id: 'store', label: 'STORAGE', x: 310, y: 0, w: 130, h: 125, c: '#2a3328' },
  { id: 'mech', label: 'MECH RM', x: 450, y: 0, w: 150, h: 125, c: '#302a3a' },
  { id: 'corr', label: 'MAIN CORRIDOR', x: 0, y: 135, w: 600, h: 55, c: '#2d2d22' },
  { id: 'west', label: 'WEST CELL', x: 0, y: 200, w: 135, h: 115, c: '#3a2a2a' },
  { id: 'tun', label: 'TUNNELS', x: 145, y: 200, w: 155, h: 115, c: '#1e2a3a' },
  { id: 'east', label: 'EAST CELL', x: 310, y: 200, w: 135, h: 115, c: '#3a3525' },
  { id: 'ctrl', label: 'CONTROL RM', x: 455, y: 200, w: 145, h: 115, c: '#1e3535' },
];
const DOOR_SLOTS = [
  { x: 55, y: 125, w: 28, h: 10 },
  { x: 215, y: 125, w: 28, h: 10 },
  { x: 360, y: 125, w: 28, h: 10 },
  { x: 505, y: 125, w: 28, h: 10 },
  { x: 50, y: 190, w: 28, h: 10 },
  { x: 200, y: 190, w: 28, h: 10 },
  { x: 360, y: 190, w: 28, h: 10 },
  { x: 510, y: 190, w: 28, h: 10 },
  { x: -3, y: 150, w: 6, h: 26 },
  { x: 597, y: 150, w: 6, h: 26 },
  { x: 210, y: 311, w: 28, h: 6 },
  { x: 510, y: 311, w: 28, h: 6 },
];
const EXIT_LABELS = [
  { x: -12, y: 163, label: 'SEWAGE EXIT', a: 'end' as const },
  { x: 612, y: 163, label: 'FUSEBOX EXIT', a: 'start' as const },
  { x: 224, y: 330, label: 'OVERGROWN EXIT', a: 'middle' as const },
  { x: 524, y: 330, label: 'SERVICE EXIT', a: 'middle' as const },
];
const VICTIM_XY = { x: 68, y: 58 };

type Props = { robotXY?: { x: number; y: number } };

export function FloorPlan({ robotXY = { x: 255, y: 162 } }: Props) {
  return (
    <div className="flex flex-col h-full bg-base-900 border border-base-700 rounded overflow-hidden">
      <div className="px-3 py-1.5 border-b border-base-700 flex items-center justify-between shrink-0">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-base-400 font-mono">
          Emergency Response Map
        </span>
        <div className="flex items-center gap-3 text-[9px] font-mono text-base-500">
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400/60" /> Robot
          </span>
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-red-400/60" /> Victim
          </span>
        </div>
      </div>
      <div className="flex-1 flex items-center justify-center p-3 overflow-hidden">
        <svg viewBox="-70 -25 745 385" className="w-full h-full" style={{ maxHeight: '100%' }}>
          <defs>
            <pattern id="grid-pattern" width="16" height="16" patternUnits="userSpaceOnUse">
              <path d="M16 0L0 0 0 16" fill="none" stroke="#1a1a20" strokeWidth="0.4" />
            </pattern>
          </defs>
          <rect x="-70" y="-25" width="745" height="385" fill="#0c0c10" />
          <rect x="-70" y="-25" width="745" height="385" fill="url(#grid-pattern)" />
          <rect x="-2" y="-2" width="604" height="320" rx="2" fill="none" stroke="#2a2a33" strokeWidth="1" />
          {ROOMS.map((r) => (
            <g key={r.id}>
              <rect
                x={r.x}
                y={r.y}
                width={r.w}
                height={r.h}
                rx="1"
                fill={r.c}
                stroke="#3a3a44"
                strokeWidth="0.8"
              />
              <text
                x={r.x + r.w / 2}
                y={r.y + r.h / 2}
                textAnchor="middle"
                dominantBaseline="central"
                fill="#666"
                style={{ fontSize: '10px', fontWeight: 600, fontFamily: 'JetBrains Mono, monospace', letterSpacing: '1px' }}
              >
                {r.label}
              </text>
            </g>
          ))}
          {DOOR_SLOTS.map((d, i) => (
            <rect
              key={i}
              x={d.x}
              y={d.y}
              width={d.w}
              height={d.h}
              rx="1"
              fill="#1a1a20"
              stroke="#333"
              strokeWidth="0.5"
            />
          ))}
          {EXIT_LABELS.map((e, i) => (
            <text
              key={i}
              x={e.x}
              y={e.y}
              textAnchor={e.a}
              fill="#444"
              style={{ fontSize: '8px', fontWeight: 500, fontFamily: 'JetBrains Mono, monospace', letterSpacing: '1px' }}
            >
              {e.label}
            </text>
          ))}
          <path
            d={`M${robotXY.x},${robotXY.y} L155,${robotXY.y} L80,${robotXY.y} L80,125 L${VICTIM_XY.x},125 L${VICTIM_XY.x},${VICTIM_XY.y}`}
            fill="none"
            stroke="#3b82f6"
            strokeWidth="1"
            strokeDasharray="4,3"
            opacity="0.3"
          />
          <circle
            cx={VICTIM_XY.x}
            cy={VICTIM_XY.y}
            r="7"
            fill="none"
            stroke="#ef4444"
            strokeWidth="0.8"
            opacity="0.3"
            className="animate-ping-ring"
            style={{ transformOrigin: `${VICTIM_XY.x}px ${VICTIM_XY.y}px` }}
          />
          <circle cx={VICTIM_XY.x} cy={VICTIM_XY.y} r="3.5" fill="#ef4444" opacity="0.7" />
          <text
            x={VICTIM_XY.x}
            y={VICTIM_XY.y - 10}
            textAnchor="middle"
            fill="#ef4444"
            style={{ fontSize: '7px', fontWeight: 600, fontFamily: 'JetBrains Mono, monospace', opacity: 0.7 }}
          >
            VIC
          </text>
          <circle
            cx={robotXY.x}
            cy={robotXY.y}
            r="7"
            fill="none"
            stroke="#3b82f6"
            strokeWidth="0.8"
            opacity="0.2"
            className="animate-ping-ring"
            style={{ transformOrigin: `${robotXY.x}px ${robotXY.y}px` }}
          />
          <rect
            x={robotXY.x - 6}
            y={robotXY.y - 5}
            width="12"
            height="10"
            rx="2"
            fill="#3b82f6"
            opacity="0.6"
            stroke="#6ba3f7"
            strokeWidth="0.5"
          />
          <circle cx={robotXY.x - 2.5} cy={robotXY.y + 0.5} r="1.5" fill="#fff" opacity="0.5" />
          <circle cx={robotXY.x + 2.5} cy={robotXY.y + 0.5} r="1.5" fill="#fff" opacity="0.5" />
          <text
            x={robotXY.x}
            y={robotXY.y - 11}
            textAnchor="middle"
            fill="#3b82f6"
            style={{ fontSize: '7px', fontWeight: 600, fontFamily: 'JetBrains Mono, monospace', opacity: 0.6 }}
          >
            R-01
          </text>
          <line x1="480" y1="340" x2="560" y2="340" stroke="#333" strokeWidth="0.5" />
          <text
            x="520"
            y="350"
            textAnchor="middle"
            fill="#444"
            style={{ fontSize: '7px', fontFamily: 'JetBrains Mono, monospace' }}
          >
            10m
          </text>
        </svg>
      </div>
    </div>
  );
}
