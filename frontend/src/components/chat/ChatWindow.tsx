"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  type ChatMessage,
  type ChatSessionDetail,
  sendChatMessage,
} from "@/lib/api-client";

const SUGGESTED_QUESTIONS = [
  "Which batches had the most defects this week?",
  "How do I interpret a short defect?",
  "What's our overall quality rate lately?",
] as const;

function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[75%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
          isUser ? "bg-primary text-primary-foreground" : "bg-muted text-foreground"
        }`}
      >
        {message.content}
      </div>
      {message.tool_calls && message.tool_calls.length > 0 && (
        <p className="px-1 text-xs text-muted-foreground">
          Used: {message.tool_calls.map((call) => call.name).join(", ")}
        </p>
      )}
      <span className="px-1 text-xs text-muted-foreground">{formatTime(message.created_at)}</span>
    </div>
  );
}

export function ChatWindow({ session }: { session: ChatSessionDetail }) {
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<ChatMessage[]>(session.messages);
  const [input, setInput] = useState("");
  const [streamingText, setStreamingText] = useState("");
  const [toolInProgress, setToolInProgress] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // A different session was selected (sidebar navigation) — reset to that session's own
  // persisted history rather than carrying over the previous session's in-flight state.
  useEffect(() => {
    setMessages(session.messages);
    setStreamingText("");
    setToolInProgress(null);
    setErrorMessage(null);
  }, [session.id, session.messages]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, streamingText]);

  async function submit(content: string) {
    const trimmed = content.trim();
    if (!trimmed || isSending) return;

    setInput("");
    setIsSending(true);
    setErrorMessage(null);
    setToolInProgress(null);
    setStreamingText("");

    const optimisticUserMessage: ChatMessage = {
      id: `pending-${Date.now()}`,
      role: "user",
      content: trimmed,
      tool_calls: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimisticUserMessage]);

    try {
      await sendChatMessage(session.id, trimmed, (event) => {
        if (event.type === "tool_call") {
          setToolInProgress(event.name);
        } else if (event.type === "content_delta") {
          setToolInProgress(null);
          setStreamingText((prev) => prev + event.text);
        } else if (event.type === "done") {
          // On the graceful-degradation path (UC-7), the backend sends an `error` event
          // immediately followed by `done` — the assistant message in `done` already carries
          // that same unavailability notice, rendered as a normal bubble (identical to how
          // it reads after a reload), so the `error` event itself needs no separate banner.
          setMessages((prev) => [...prev, event.message]);
          setStreamingText("");
          setToolInProgress(null);
        }
      });
    } catch {
      setErrorMessage("Couldn't reach the AI assistant. Please try again.");
    } finally {
      setIsSending(false);
      // The session's title (derived from the first message) and its position in the
      // sidebar's most-recently-active ordering may have changed.
      void queryClient.invalidateQueries({ queryKey: ["chat", "sessions"] });
    }
  }

  const showSuggestions = messages.length === 0 && !isSending;

  return (
    <Card className="flex flex-1 flex-col overflow-hidden">
      <CardContent className="flex flex-1 flex-col gap-4 overflow-hidden">
        <div
          ref={scrollRef}
          role="log"
          aria-label="Conversation"
          className="flex flex-1 flex-col gap-4 overflow-y-auto"
          aria-live="polite"
        >
          {messages.length === 0 && !streamingText && (
            <p className="text-sm text-muted-foreground">
              Ask about production data — batches, defects, or a specific analysis. The
              assistant answers using real data, never a guess.
            </p>
          )}
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          {toolInProgress && (
            <p className="text-xs text-muted-foreground" role="status">
              Looking up {toolInProgress}…
            </p>
          )}
          {streamingText && (
            <div className="flex flex-col items-start gap-1">
              <div className="max-w-[75%] rounded-lg bg-muted px-3 py-2 text-sm whitespace-pre-wrap text-foreground">
                {streamingText}
              </div>
            </div>
          )}
          {errorMessage && (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage}
            </p>
          )}
        </div>

        {showSuggestions && (
          <div className="flex flex-wrap gap-2">
            {SUGGESTED_QUESTIONS.map((question) => (
              <Button
                key={question}
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void submit(question)}
              >
                {question}
              </Button>
            ))}
          </div>
        )}

        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void submit(input);
          }}
        >
          <label htmlFor="chat-message-input" className="sr-only">
            Message
          </label>
          <textarea
            id="chat-message-input"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submit(input);
              }
            }}
            placeholder="Ask a question about production data…"
            rows={2}
            disabled={isSending}
            className="flex-1 resize-none rounded-lg border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
          />
          <Button type="submit" disabled={isSending || !input.trim()}>
            Send
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
