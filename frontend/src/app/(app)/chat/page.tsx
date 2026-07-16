"use client";

import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { createChatSession } from "@/lib/api-client";

export default function ChatIndexPage() {
  const router = useRouter();
  const createSession = useMutation({
    mutationFn: () => createChatSession(),
    onSuccess: (session) => router.push(`/chat/${session.id}`),
  });

  return (
    <Card className="flex flex-1 items-center justify-center">
      <CardContent className="flex flex-col items-center gap-3 text-center">
        <p className="text-sm text-muted-foreground">
          Select a conversation from the sidebar, or start a new one.
        </p>
        <Button onClick={() => createSession.mutate()} disabled={createSession.isPending}>
          New chat
        </Button>
      </CardContent>
    </Card>
  );
}
