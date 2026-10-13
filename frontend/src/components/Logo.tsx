export function Logo() {
  return (
    <span className="flex items-center gap-2 font-semibold">
      <svg viewBox="0 0 32 32" className="size-7" aria-hidden="true">
        <rect width="32" height="32" rx="7" className="fill-brand" />
        <path d="M10 8h8l5 5v11H10z" fill="#fff" />
        <path d="M13 17h7M13 21h5" className="stroke-brand" strokeWidth="2" strokeLinecap="round" />
      </svg>
      <span className="text-lg tracking-tight">
        docflow <span className="font-normal text-muted">review</span>
      </span>
    </span>
  )
}
