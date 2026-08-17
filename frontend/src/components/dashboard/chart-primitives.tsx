"use client";

import { useId, useState } from "react";

import { cn } from "@/lib/utils";

/** Every chart in the app hovers into the same box, so the tooltip is a shape the operator
 * learns once. Text wears text tokens; the colored chip beside it carries identity.
 */
export function TooltipShell({
  title,
  children,
}: {
  title?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="pointer-events-none min-w-[9rem] rounded-md border border-border bg-popover px-3 py-2 text-xs shadow-lifted">
      {title ? (
        <p className="label-channel mb-2 border-b border-border pb-1.5">{title}</p>
      ) : null}
      {children}
    </div>
  );
}

export function TooltipRow({
  color,
  label,
  value,
  suffix,
}: {
  color?: string;
  label: string;
  value: React.ReactNode;
  suffix?: string;
}) {
  return (
    <li className="flex items-center gap-2 py-0.5">
      {color ? (
        <span
          aria-hidden="true"
          className="size-2 shrink-0 rounded-[2px]"
          style={{ backgroundColor: color }}
        />
      ) : null}
      <span className="mr-auto text-popover-foreground">{label}</span>
      <span className="readout font-semibold text-popover-foreground">
        {value}
        {suffix ? <span className="ml-0.5 font-normal text-muted-foreground">{suffix}</span> : null}
      </span>
    </li>
  );
}

// --- Dial -------------------------------------------------------------------------------

function polar(cx: number, cy: number, r: number, angle: number): [number, number] {
  const radians = ((angle - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(radians), cy + r * Math.sin(radians)];
}

function arcPath(cx: number, cy: number, r: number, start: number, end: number): string {
  const sweep = Math.min(Math.abs(end - start), 359.99);
  const stop = start + sweep;
  const [sx, sy] = polar(cx, cy, r, start);
  const [ex, ey] = polar(cx, cy, r, stop);
  return `M ${sx.toFixed(3)} ${sy.toFixed(3)} A ${r} ${r} 0 ${sweep > 180 ? 1 : 0} 1 ${ex.toFixed(3)} ${ey.toFixed(3)}`;
}

export type DialSegment = { key: string; label: string; value: number; color: string };

/** A proportion drawn as an instrument dial rather than a pie: one stroked track, segments
 * laid end to end with a gap of bare surface between them, and the reading in the middle.
 * `sweep` under 360 leaves the dial open at the bottom, the way a bench gauge is drawn;
 * a full 360 closes it into a ring. Hovering a segment swaps the centre readout to that
 * segment, which is the whole interaction — no tooltip layer to chase with the mouse.
 */
export function Dial({
  segments,
  sweep = 360,
  size = 172,
  thickness = 14,
  primary,
  onHoverChange,
  className,
}: {
  segments: readonly DialSegment[];
  sweep?: number;
  size?: number;
  thickness?: number;
  /** Centre content when nothing is hovered. */
  primary: React.ReactNode;
  onHoverChange?: (segment: DialSegment | null) => void;
  className?: string;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const titleId = useId();

  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  const radius = (size - thickness) / 2;
  const centre = size / 2;
  const start = sweep >= 360 ? -90 : -(sweep / 2);
  // A gap only fits between segments that actually have a neighbour with length.
  const drawn = segments.filter((segment) => segment.value > 0);
  const gap = drawn.length > 1 ? 2.4 : 0;
  const available = sweep - gap * drawn.length;

  let cursor = start;
  const arcs = drawn.map((segment) => {
    const span = total > 0 ? (segment.value / total) * available : 0;
    const path = arcPath(centre, centre, radius, cursor, cursor + span);
    cursor += span + gap;
    return { segment, path };
  });

  function setHover(segment: DialSegment | null) {
    setHovered(segment?.key ?? null);
    onHoverChange?.(segment);
  }

  const active = arcs.find((arc) => arc.segment.key === hovered)?.segment ?? null;

  return (
    <div className={cn("relative shrink-0", className)} style={{ width: size, height: size }}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-labelledby={titleId}
        className="overflow-visible"
      >
        <title id={titleId}>
          {segments.map((segment) => `${segment.label}: ${segment.value}`).join(", ")}
        </title>
        {/* Track: the unfilled part of the dial, so an empty reading still shows the scale. */}
        <path
          d={arcPath(centre, centre, radius, start, start + sweep)}
          fill="none"
          stroke="var(--muted)"
          strokeWidth={thickness}
          strokeLinecap="round"
        />
        {arcs.map(({ segment, path }) => (
          <path
            key={segment.key}
            d={path}
            fill="none"
            stroke={segment.color}
            strokeWidth={thickness}
            strokeLinecap="round"
            className="cursor-default transition-[opacity,stroke-width] duration-200"
            style={{
              opacity: hovered && hovered !== segment.key ? 0.32 : 1,
              strokeWidth: hovered === segment.key ? thickness + 3 : thickness,
            }}
            onMouseEnter={() => setHover(segment)}
            onMouseLeave={() => setHover(null)}
          />
        ))}
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
        {active ? (
          <>
            <span className="readout text-2xl leading-none font-semibold">{active.value}</span>
            <span className="mt-1.5 max-w-[70%] text-[0.6875rem] leading-tight text-muted-foreground">
              {active.label}
            </span>
          </>
        ) : (
          primary
        )}
      </div>
    </div>
  );
}

/** Legend for a dial: the segments listed with their share, which is the part a dial is bad
 * at communicating on its own.
 */
export function DialLegend({
  segments,
  className,
}: {
  segments: readonly DialSegment[];
  className?: string;
}) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  return (
    <ul className={cn("flex min-w-0 flex-col gap-2.5", className)}>
      {segments.map((segment) => (
        <li key={segment.key} className="flex items-baseline gap-2.5">
          <span
            aria-hidden="true"
            className="size-2 shrink-0 translate-y-[-1px] rounded-[2px]"
            style={{ backgroundColor: segment.color }}
          />
          <span className="min-w-0 flex-1 text-[0.8125rem] text-muted-foreground">
            {segment.label}
          </span>
          <span className="readout text-[0.8125rem] font-semibold">{segment.value}</span>
          <span className="readout w-11 text-right text-[0.6875rem] text-muted-foreground">
            {total > 0 ? `${Math.round((segment.value / total) * 100)}%` : "—"}
          </span>
        </li>
      ))}
    </ul>
  );
}
