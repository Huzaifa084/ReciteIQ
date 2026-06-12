export function Logo({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <defs>
        <linearGradient id="riq-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#1d7a52" />
          <stop offset="1" stopColor="#0b3b27" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="14" fill="url(#riq-g)" />
      <g fill="#e7d9a8">
        <rect x="13" y="35" width="5.5" height="13" rx="2.75" />
        <rect x="22.5" y="27" width="5.5" height="21" rx="2.75" />
        <rect x="32" y="17" width="5.5" height="31" rx="2.75" />
        <rect x="41.5" y="27" width="5.5" height="21" rx="2.75" />
        <rect x="51" y="35" width="5.5" height="13" rx="2.75" />
      </g>
      <circle cx="34.75" cy="11" r="3.2" fill="#e7d9a8" />
    </svg>
  )
}
