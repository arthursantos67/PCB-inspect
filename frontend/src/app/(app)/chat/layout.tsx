"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Plus, Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { useI18n, type Translate } from "@/contexts/I18nContext";
import { createChatSession, deleteChatSession, listChatSessions } from "@/lib/api-client";

function formatSessionLabel(title: string | null, t: Translate): string {
  return title && title.trim().length > 0 ? title : t("chat.newConversation");
}

export default function ChatLayout({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();
  const router = useRouter();
  const params = useParams<{ sessionId?: string }>();
  const activeSessionId = params.sessionId;
  const queryClient = useQueryClient();
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  const sessionsQuery = useQuery({
    queryKey: ["chat", "sessions"],
    queryFn: listChatSessions,
  });

  const createSession = useMutation({
    mutationFn: () => createChatSession(),
    onSuccess: (session) => {
      void queryClient.invalidateQueries({ queryKey: ["chat", "sessions"] });
      router.push(`/chat/${session.id}`);
    },
  });

  const deleteSession = useMutation({
    mutationFn: (sessionId: string) => deleteChatSession(sessionId),
    onSuccess: (_data, sessionId) => {
      void queryClient.invalidateQueries({ queryKey: ["chat", "sessions"] });
      if (sessionId === activeSessionId) router.push("/chat");
    },
    onSettled: () => setPendingDeleteId(null),
  });

  const sessions = sessionsQuery.data?.results ?? [];

  return (
    // One bezel around both columns, split by a hairline seam: the conversation list and the
    // conversation are two panes of one instrument, not a floating list next to a card.
    <div className="flex h-[calc(100vh-7.5rem)] gap-px overflow-hidden rounded-lg border border-border bg-border shadow-panel">
      <aside className="flex w-64 shrink-0 flex-col bg-card">
        <div className="flex items-center justify-between gap-2 px-4 pt-4 pb-3">
          <div>
            <p className="label-channel">{t("chat.eyebrow")}</p>
            <h1 className="mt-1.5 font-heading text-[0.9375rem] leading-none font-semibold tracking-[-0.012em]">
              {t("chat.title")}
            </h1>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => createSession.mutate()}
            disabled={createSession.isPending}
          >
            <Plus className="size-3.5" aria-hidden="true" />
            {t("chat.new")}
          </Button>
        </div>

        <nav
          aria-label={t("chat.sessionsLabel")}
          className="flex flex-1 flex-col gap-0.5 overflow-y-auto border-t border-border px-2 py-2"
        >
          {sessionsQuery.isPending && (
            <p className="px-2 py-1 text-[0.8125rem] text-muted-foreground">{t("chat.loadingSessions")}</p>
          )}
          {sessionsQuery.isSuccess && sessions.length === 0 && (
            <p className="px-2 py-2 text-[0.8125rem] leading-relaxed text-muted-foreground">
              {t("chat.noSessions")}
            </p>
          )}
          {sessions.map((session) => {
            const isActive = session.id === activeSessionId;
            return (
              <div key={session.id} className="group relative flex items-center gap-1">
                {isActive && (
                  <span
                    aria-hidden="true"
                    className="absolute top-1/2 -left-2 h-4 w-[3px] -translate-y-1/2 rounded-r-full bg-brand"
                  />
                )}
                <Link
                  href={`/chat/${session.id}`}
                  aria-current={isActive ? "page" : undefined}
                  className={`flex-1 truncate rounded-md px-2 py-1.5 text-[0.8125rem] transition-colors hover:bg-accent ${
                    isActive ? "bg-accent font-medium text-foreground" : "text-muted-foreground"
                  }`}
                >
                  {formatSessionLabel(session.title, t)}
                </Link>
                <button
                  type="button"
                  aria-label={t("chat.deleteConversation", {
                    title: formatSessionLabel(session.title, t),
                  })}
                  className="rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
                  disabled={pendingDeleteId === session.id}
                  onClick={() => {
                    setPendingDeleteId(session.id);
                    deleteSession.mutate(session.id);
                  }}
                >
                  <Trash2 className="size-3.5" aria-hidden="true" />
                </button>
              </div>
            );
          })}
        </nav>
      </aside>

      <div className="flex flex-1 flex-col overflow-hidden bg-card">{children}</div>
    </div>
  );
}
