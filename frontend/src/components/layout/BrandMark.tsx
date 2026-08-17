import { cn } from "@/lib/utils";

/** The product mark: a fiducial. On a real panel it is the etched alignment target a
 * pick-and-place camera locks onto before it trusts any coordinate on the board — the
 * closest thing this domain has to a symbol for "machine vision looking at a PCB". Drawn as
 * a via ringed by a crosshair, with the copper pad as the only filled element.
 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={cn("size-6", className)}
    >
      <rect
        x="0.75"
        y="0.75"
        width="22.5"
        height="22.5"
        rx="5.5"
        className="fill-primary"
      />
      <circle cx="12" cy="12" r="6.25" stroke="currentColor" strokeWidth="1.1" opacity="0.55" />
      <circle cx="12" cy="12" r="2.6" className="fill-brand" />
      <path
        d="M12 2.6v4.3M12 17.1v4.3M2.6 12h4.3M17.1 12h4.3"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        opacity="0.85"
      />
    </svg>
  );
}
