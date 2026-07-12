import { Badge } from "@/components/ui/badge";
import type { ImageStatus } from "@/lib/api-client";

const STATUS_LABEL: Record<ImageStatus, string> = {
  QUEUED: "Queued",
  PROCESSING: "Processing",
  DETECTED: "Detected",
  ANALYZING: "Analyzing",
  COMPLETED: "Completed",
  FAILED: "Failed",
};

const STATUS_VARIANT: Record<ImageStatus, "default" | "secondary" | "destructive" | "outline"> = {
  QUEUED: "outline",
  PROCESSING: "secondary",
  DETECTED: "secondary",
  ANALYZING: "secondary",
  COMPLETED: "default",
  FAILED: "destructive",
};

/** Processing-status badge (FE-02/FE-10) — the label text is always self-describing, so a
 * status is never conveyed by color/variant alone.
 */
export function StatusBadge({ status }: { status: ImageStatus }) {
  return <Badge variant={STATUS_VARIANT[status]}>{STATUS_LABEL[status]}</Badge>;
}
