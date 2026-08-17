import { cn } from "@/lib/utils";

/** Every screen opens the same way: an engraved section label, the screen's name, one line
 * saying what the operator does here, and the screen's actions pinned right. Repeating one
 * masthead across the app is what makes seven different screens read as one instrument.
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  children,
  className,
}: {
  eyebrow?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-col gap-3", className)}>
      {children}
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          {eyebrow ? <p className="label-channel mb-2">{eyebrow}</p> : null}
          <h1 className="font-heading text-[1.375rem] leading-tight font-semibold tracking-[-0.02em]">
            {title}
          </h1>
          {description ? (
            <p className="mt-1.5 max-w-2xl text-[0.8125rem] leading-relaxed text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  );
}
