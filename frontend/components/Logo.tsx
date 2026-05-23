export default function Logo({ size = 36 }: { size?: number }) {
  return (
    <div className="flex items-center gap-2.5">
      <svg
        width={size}
        height={size}
        viewBox="0 0 64 64"
        aria-hidden="true"
        className="shrink-0"
      >
        <g transform="translate(32 32) rotate(-25)">
          <ellipse cx="0" cy="0" rx="22" ry="13" fill="#FFD700" />
          <line x1="-17" y1="0" x2="17" y2="0" stroke="#003087" strokeWidth="2.5" strokeLinecap="round" />
          <line x1="-6.5" y1="-3.5" x2="-6.5" y2="3.5" stroke="#003087" strokeWidth="2.2" strokeLinecap="round" />
          <line x1="-2" y1="-3.5" x2="-2" y2="3.5" stroke="#003087" strokeWidth="2.2" strokeLinecap="round" />
          <line x1="2.5" y1="-3.5" x2="2.5" y2="3.5" stroke="#003087" strokeWidth="2.2" strokeLinecap="round" />
          <line x1="7" y1="-3.5" x2="7" y2="3.5" stroke="#003087" strokeWidth="2.2" strokeLinecap="round" />
        </g>
      </svg>
      <span className="font-display text-xl tracking-wide leading-none">
        NRL <span className="text-nrl-gold">PREDICTOR</span>
      </span>
    </div>
  );
}
