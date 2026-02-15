// L-shaped floor plan: Courtyard (top, 8ft wide x 5ft) + Hallway (bottom-right, 3ft wide x 5ft)
// Scale: 40px per foot (reduced from 50px to fit robot path in courtyard)
// Robot path: straight 5ft north → 90° left → 3ft west → patient

// Scaled coordinates to keep everything in courtyard (shifted right to avoid text overlap):
// Robot starts at bottom-right of courtyard: (280, 220)
// Goes north 5ft (200px) → corner at (280, 20)
// Turns left, goes west 3ft (120px) → patient at (200, 20)

const ROBOT_START_XY = { x: 280, y: 220 };
const PATIENT_XY = { x: 200, y: 20 };

type Props = { robotXY?: { x: number; y: number } };

export function FloorPlan({ robotXY = ROBOT_START_XY }: Props) {
  // Scale incoming robot positions to fit in courtyard
  // Assuming robot reports coordinates in a different scale, map them to courtyard
  const scaledRobotX = 280; // Keep X on right side of courtyard
  const scaledRobotY = Math.max(20, Math.min(220, robotXY.y * 0.5)); // Scale Y to fit
  const displayRobot = { x: scaledRobotX, y: scaledRobotY };
  
  // Path waypoints: robot start → north to corner → west to patient
  const cornerX = ROBOT_START_XY.x;
  const cornerY = PATIENT_XY.y;

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
            <span className="w-2.5 h-2.5 rounded-full bg-red-500/70" /> Patient
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

          {/* Dotted path: robot start → north → corner → west → patient */}
          <path
            d={`M${ROBOT_START_XY.x},${ROBOT_START_XY.y} L${cornerX},${cornerY} L${PATIENT_XY.x},${PATIENT_XY.y}`}
            fill="none"
            stroke="#3b82f6"
            strokeWidth="2"
            strokeDasharray="6,4"
            opacity="0.6"
          />

          {/* Corner marker */}
          <circle cx={cornerX} cy={cornerY} r="3" fill="#3b82f6" opacity="0.4" />

          {/* Patient (top-center area of courtyard) */}
          <circle
            cx={PATIENT_XY.x}
            cy={PATIENT_XY.y}
            r="12"
            fill="none"
            stroke="#ef4444"
            strokeWidth="1.5"
            opacity="0.4"
            className="animate-ping-ring"
            style={{ transformOrigin: `${PATIENT_XY.x}px ${PATIENT_XY.y}px` }}
          />
          <circle cx={PATIENT_XY.x} cy={PATIENT_XY.y} r="6" fill="#ef4444" opacity="0.9" />
          <text
            x={PATIENT_XY.x}
            y={PATIENT_XY.y - 18}
            textAnchor="middle"
            fill="#dc2626"
            style={{ fontSize: '9px', fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', opacity: 0.9 }}
          >
            PATIENT
          </text>

          {/* Robot (current position - starts at bottom-center) */}
          <circle
            cx={displayRobot.x}
            cy={displayRobot.y}
            r="10"
            fill="none"
            stroke="#3b82f6"
            strokeWidth="1.5"
            opacity="0.3"
            className="animate-ping-ring"
            style={{ transformOrigin: `${displayRobot.x}px ${displayRobot.y}px` }}
          />
          <rect
            x={displayRobot.x - 8}
            y={displayRobot.y - 7}
            width="16"
            height="14"
            rx="2"
            fill="#3b82f6"
            opacity="0.85"
            stroke="#2563eb"
            strokeWidth="0.8"
          />
          <circle cx={displayRobot.x - 3.5} cy={displayRobot.y + 0.5} r="1.8" fill="#fff" opacity="0.8" />
          <circle cx={displayRobot.x + 3.5} cy={displayRobot.y + 0.5} r="1.8" fill="#fff" opacity="0.8" />
          <text
            x={displayRobot.x}
            y={displayRobot.y - 16}
            textAnchor="middle"
            fill="#2563eb"
            style={{ fontSize: '9px', fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', opacity: 0.8 }}
          >
            ROBOT
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
