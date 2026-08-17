import { cn } from "@/lib/utils";

export type LampTone = "good" | "warning" | "serious" | "critical" | "neutral";

const TONE_COLOR: Record<LampTone, string> = {
  good: "var(--status-good)",
  warning: "var(--status-warning)",
  serious: "var(--status-serious)",
  critical: "var(--status-critical)",
  neutral: "var(--muted-foreground)",
};

/** One chip shape for every state in the app: a lit lamp beside a word. The word always says
 * the state, so nothing is carried by color alone, and the chip itself stays a quiet outline
 * so a column of them reads as a row of indicators rather than a row of filled badges.
 *
 * `pulse` marks a state that is still moving (a job running, a stream reconnecting); `hollow`
 * marks one that has not started yet.
 */
export function LampChip({
  tone,
  pulse,
  hollow,
  className,
  children,
  ...props
}: {
  tone: LampTone;
  pulse?: boolean;
  hollow?: boolean;
} & React.ComponentProps<"span">) {
  const color = TONE_COLOR[tone];
  return (
    <span
      className={cn(
        "inline-flex h-[1.375rem] items-center gap-1.5 rounded-[5px] border border-border bg-card px-1.5 text-[0.6875rem] font-medium whitespace-nowrap text-foreground",
        className
      )}
      {...props}
    >
      <span
        aria-hidden="true"
        className="relative flex size-2 shrink-0 items-center justify-center"
      >
        {pulse && (
          <span
            className="absolute size-2 animate-ping rounded-full opacity-60 [animation-duration:1.8s]"
            style={{ backgroundColor: color }}
          />
        )}
        <span
          className="relative size-2 rounded-full"
          style={hollow ? { border: `1.5px solid ${color}` } : { backgroundColor: color }}
        />
      </span>
      {children}
    </span>
  );
}
