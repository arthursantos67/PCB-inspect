"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useI18n, type Translate } from "@/contexts/I18nContext";
import {
  attachChatInspection,
  detachChatInspection,
  listChatAttachments,
  listInspections,
} from "@/lib/api-client";

const MAX_ATTACHMENTS = 5;
const PICKER_PAGE_SIZE = 8;

function inspectionLabel(
  batchNumber: string | null,
  boardNumber: string | null,
  t: Translate
): string {
  const batch = batchNumber ?? t("chat.attachments.unknownBatch");
  return boardNumber ? t("chat.attachments.boardLabel", { batch, board: boardNumber }) : batch;
}

/** Analyses pinned to a chat session.
 *
 * The assistant otherwise only sees whatever its tools happen to fetch, so asking about "this
 * board" meant describing it in prose every time. A pinned analysis is preloaded as a fact on
 * every turn; unpinning it takes it back out of context, which is also how an old, no longer
 * relevant analysis stops costing tokens and confusing the answers.
 */
export function ChatAttachments({ sessionId }: { sessionId: string }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [search, setSearch] = useState("");

  const attachmentsQuery = useQuery({
    queryKey: ["chat", "attachments", sessionId],
    queryFn: () => listChatAttachments(sessionId),
  });

  // Only completed boards are offered: an analysis is what gets attached, and it exists only
  // once the pipeline has finished writing it.
  const candidatesQuery = useQuery({
    queryKey: ["chat", "attachment-candidates", search],
    queryFn: () =>
      listInspections({
        page: 1,
        page_size: PICKER_PAGE_SIZE,
        status: "COMPLETED",
        batch_number: search || undefined,
      }),
    placeholderData: keepPreviousData,
    enabled: pickerOpen,
  });

  const attachments = attachmentsQuery.data?.results ?? [];
  const attachedIds = new Set(attachments.map((item) => item.inspection_id));
  const atCap = attachments.length >= MAX_ATTACHMENTS;

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["chat", "attachments", sessionId] });
  }

  const attach = useMutation({
    mutationFn: (inspectionId: string) => attachChatInspection(sessionId, inspectionId),
    onSuccess: () => {
      refresh();
      setPickerOpen(false);
    },
  });

  const detach = useMutation({
    mutationFn: (inspectionId: string) => detachChatInspection(sessionId, inspectionId),
    onSuccess: refresh,
  });

  return (
    <div className="flex flex-col gap-2 border-b border-border pb-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-muted-foreground">
          {t("chat.attachments.label")}
        </span>
        {attachments.length === 0 && (
          <span className="text-xs text-muted-foreground">{t("chat.attachments.none")}</span>
        )}
        {attachments.map((attachment) => (
          <span
            key={attachment.inspection_id}
            className="inline-flex items-center gap-1 rounded-full border border-border bg-muted px-2 py-0.5 text-xs"
          >
            {inspectionLabel(attachment.batch_number, attachment.board_number, t)}
            <button
              type="button"
              aria-label={t("chat.attachments.remove", {
                label: inspectionLabel(attachment.batch_number, attachment.board_number, t),
              })}
              className="text-muted-foreground hover:text-foreground"
              disabled={detach.isPending}
              onClick={() => detach.mutate(attachment.inspection_id)}
            >
              <X className="size-3" aria-hidden="true" />
            </button>
          </span>
        ))}
        <Button
          type="button"
          size="xs"
          variant={pickerOpen ? "selected" : "outline"}
          aria-pressed={pickerOpen}
          aria-expanded={pickerOpen}
          disabled={atCap && !pickerOpen}
          onClick={() => setPickerOpen((open) => !open)}
        >
          {atCap
            ? t("chat.attachments.limit", { max: MAX_ATTACHMENTS })
            : t("chat.attachments.attach")}
        </Button>
      </div>

      {pickerOpen && (
        <div className="flex flex-col gap-2 rounded-lg border border-border p-3">
          <label htmlFor="chat-attachment-search" className="text-xs font-medium">
            {t("chat.attachments.find")}
          </label>
          <Input
            id="chat-attachment-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("chat.attachments.searchPlaceholder")}
          />
          {candidatesQuery.isPending && (
            <p className="text-xs text-muted-foreground">{t("chat.attachments.loadingBoards")}</p>
          )}
          {candidatesQuery.isError && (
            <p className="text-xs text-destructive">{t("chat.attachments.loadFailed")}</p>
          )}
          {candidatesQuery.isSuccess && candidatesQuery.data.results.length === 0 && (
            <p className="text-xs text-muted-foreground">{t("chat.attachments.noMatches")}</p>
          )}
          <ul className="flex flex-col gap-1">
            {(candidatesQuery.data?.results ?? []).map((item) => {
              const alreadyAttached = attachedIds.has(item.id);
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left text-xs hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={alreadyAttached || attach.isPending}
                    onClick={() => attach.mutate(item.id)}
                  >
                    <span>{inspectionLabel(item.batch_number, item.board_number, t)}</span>
                    <span className="text-muted-foreground">
                      {alreadyAttached
                        ? t("chat.attachments.alreadyAttached")
                        : item.defect_types.length > 0
                          ? t("chat.attachments.defectTypes", {
                              count: item.defect_types.length,
                            })
                          : t("chat.attachments.noDefects")}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          {attach.isError && (
            <p className="text-xs text-destructive">{t("chat.attachments.attachFailed")}</p>
          )}
        </div>
      )}
    </div>
  );
}
