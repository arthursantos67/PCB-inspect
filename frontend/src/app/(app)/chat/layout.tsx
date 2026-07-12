"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { createChatSession, deleteChatSession, listChatSessions } from "@/lib/api-client";

function formatSessionLabel(title: string | null): string {
  return title && title.trim().length > 0 ? title : "New conversation";
}

export default function ChatLayout({ children }: { children: React.ReactNode }) {
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
    <div className="flex h-[calc(100vh-8rem)] gap-6">
      <aside className="flex w-64 shrink-0 flex-col gap-3 border-r pr-4">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold">Chat</h1>
          <Button
            size="sm"
            onClick={() => createSession.mutate()}
            disabled={createSession.isPending}
          >
            New chat
          </Button>
        </div>

        <nav aria-label="Chat sessions" className="flex flex-1 flex-col gap-1 overflow-y-auto">
          {sessionsQuery.isPending && (
            <p className="px-2 py-1 text-sm text-muted-foreground">Loading sessions…</p>
          )}
          {sessionsQuery.isSuccess && sessions.length === 0 && (
            <p className="px-2 py-1 text-sm text-muted-foreground">
              No conversations yet. Start one with &quot;New chat&quot;.
            </p>
          )}
          {sessions.map((session) => {
            const isActive = session.id === activeSessionId;
            return (
              <div key={session.id} className="group flex items-center gap-1">
                <Link
                  href={`/chat/${session.id}`}
                  aria-current={isActive ? "page" : undefined}
                  className={`flex-1 truncate rounded-md px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground ${
                    isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground"
                  }`}
                >
                  {formatSessionLabel(session.title)}
                </Link>
                <button
                  type="button"
                  aria-label={`Delete conversation "${formatSessionLabel(session.title)}"`}
                  className="rounded-md p-1.5 text-muted-foreground opacity-0 hover:bg-destructive/10 hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
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

      <div className="flex flex-1 flex-col overflow-hidden">{children}</div>
    </div>
  );
}
