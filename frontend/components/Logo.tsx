// Walkdown mark: a walked route along a pipe run, ending in a checked inspection point.
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="logo">
      <rect x="1" y="1" width="30" height="30" rx="8" fill="var(--accent)" />
      <path d="M7 22h8a3 3 0 0 0 3-3v-6a3 3 0 0 1 3-3h4" fill="none" stroke="#1b1203" strokeWidth="3" strokeLinecap="round" />
      <circle cx="7" cy="22" r="2.2" fill="#1b1203" />
      <circle cx="24.5" cy="10" r="4.2" fill="#1b1203" />
      <path d="M22.6 10.1l1.3 1.3 2.4-2.6" fill="none" stroke="var(--accent)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
