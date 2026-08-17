import * as React from "react";

import { cn } from "@/lib/utils";

/** Data table, tuned for the density an operator scans rather than the airy default:
 * column heads are engraved channel labels (mono, tracked, uppercase), rows are separated
 * by hairlines only, and the hover state is a wash plus a copper edge on the leading cell
 * so the row under the cursor is unmistakable in a long list.
 */
function Table({ className, ...props }: React.ComponentProps<"table">) {
  return (
    <div data-slot="table-container" className="relative w-full overflow-x-auto">
      <table
        data-slot="table"
        className={cn("w-full caption-bottom border-collapse text-sm", className)}
        {...props}
      />
    </div>
  );
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn("[&_tr]:border-b [&_tr]:border-border-strong", className)}
      {...props}
    />
  );
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  );
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "group/row border-b border-border transition-colors data-[state=selected]:bg-accent hover:bg-accent/60",
        className
      )}
      {...props}
    />
  );
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "label-channel h-8 px-3 text-left align-middle whitespace-nowrap first:pl-0 last:pr-0",
        className
      )}
      {...props}
    />
  );
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "px-3 py-2.5 align-middle whitespace-nowrap first:pl-0 last:pr-0",
        // The leading cell carries a copper marker on hover: the row you are pointing at
        // is identified at its edge, where the eye returns after crossing the columns.
        "first:relative first:before:absolute first:before:inset-y-0 first:before:-left-3 first:before:w-[2px] first:before:bg-brand first:before:opacity-0 first:before:transition-opacity group-hover/row:first:before:opacity-100",
        className
      )}
      {...props}
    />
  );
}

function TableCaption({ className, ...props }: React.ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("mt-4 text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

export { Table, TableHeader, TableBody, TableRow, TableHead, TableCell, TableCaption };
