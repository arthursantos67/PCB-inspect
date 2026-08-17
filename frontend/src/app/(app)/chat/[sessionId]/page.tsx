"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { ChatWindow } from "@/components/chat/ChatWindow";
import { useI18n } from "@/contexts/I18nContext";
import { getChatSession } from "@/lib/api-client";

export default function ChatSessionPage() {
  const { t } = useI18n();
  const params = useParams<{ sessionId: string }>();
  const sessionId = params.sessionId;

  const sessionQuery = useQuery({
    queryKey: ["chat", "sessions", sessionId],
    queryFn: () => getChatSession(sessionId),
  });

  if (sessionQuery.isPending) {
    return <p className="text-sm text-muted-foreground">{t("chat.loadingConversation")}</p>;
  }

  if (sessionQuery.isError || !sessionQuery.data) {
    return <p className="text-sm text-destructive">{t("chat.loadFailed")}</p>;
  }

  return <ChatWindow key={sessionId} session={sessionQuery.data} />;
}
