"use client";

import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { MessageSquare } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/contexts/I18nContext";
import { createChatSession } from "@/lib/api-client";

export default function ChatIndexPage() {
  const { t } = useI18n();
  const router = useRouter();
  const createSession = useMutation({
    mutationFn: () => createChatSession(),
    onSuccess: (session) => router.push(`/chat/${session.id}`),
  });

  return (
    // The chat layout already supplies the pane's surface, so this state is content only:
    // one sentence naming what the assistant can answer, and the action that starts it.
    <div className="flex flex-1 items-center justify-center p-8">
      <div className="flex max-w-sm flex-col items-center gap-4 text-center">
        <MessageSquare className="size-6 text-muted-foreground/60" aria-hidden="true" />
        <div>
          <p className="font-heading text-[0.9375rem] font-semibold tracking-[-0.012em]">
            {t("chat.index.title")}
          </p>
          <p className="mt-1.5 text-[0.8125rem] leading-relaxed text-muted-foreground">
            {t("chat.index.description")}
          </p>
        </div>
        <Button
          variant="brand"
          onClick={() => createSession.mutate()}
          disabled={createSession.isPending}
        >
          {t("chat.index.newChat")}
        </Button>
      </div>
    </div>
  );
}
