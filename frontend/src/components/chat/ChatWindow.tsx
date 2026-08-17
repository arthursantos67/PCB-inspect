"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { ChatAttachments } from "@/components/chat/ChatAttachments";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useI18n } from "@/contexts/I18nContext";
import {
  type ChatMessage,
  type ChatSessionDetail,
  sendChatMessage,
} from "@/lib/api-client";
import { formatTimeOfDay } from "@/lib/format";

// The openers offered on an empty conversation. Only their order lives here: the questions
// themselves come from the dictionaries, so the assistant is asked in the station language and
// answers in it (it replies in whatever language the question was written in).
const SUGGESTED_QUESTIONS = ["batches", "defect", "quality"] as const;

/** A local model on CPU can take a while, but "a while" has to end: past this the turn is
 * abandoned and the composer comes back, rather than staying disabled forever. */
const TURN_TIMEOUT_MS = 180_000;

function MessageBubble({ message }: { message: ChatMessage }) {
  const { t } = useI18n();
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
          {t("chat.used", { tools: message.tool_calls.map((call) => call.name).join(", ") })}
        </p>
      )}
      <span className="px-1 text-xs text-muted-foreground">
        {formatTimeOfDay(message.created_at)}
      </span>
    </div>
  );
}

export function ChatWindow({ session }: { session: ChatSessionDetail }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<ChatMessage[]>(session.messages);
  const [input, setInput] = useState("");
  const [streamingText, setStreamingText] = useState("");
  const [toolInProgress, setToolInProgress] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const isSendingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  // Server history wins, but never mid-turn: the parent refetches this session whenever the
  // sidebar's session list is invalidated, and adopting that snapshot while a turn is running
  // used to wipe the optimistic question and the text streaming in under it.
  // One session per mount (the page keys on the id), so
  // this only ever runs for refetches of the same conversation.
  useEffect(() => {
    if (isSendingRef.current) return;
    setMessages(session.messages);
  }, [session.messages]);

  // Abandoning the page mid-turn must not leave the request running against a dead component.
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, streamingText]);

  async function submit(content: string) {
    const trimmed = content.trim();
    if (!trimmed || isSending) return;

    setInput("");
    setIsSending(true);
    isSendingRef.current = true;
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

    const controller = new AbortController();
    abortRef.current = controller;
    const timeout = setTimeout(() => controller.abort(), TURN_TIMEOUT_MS);

    try {
      await sendChatMessage(session.id, trimmed, (event) => {
        if (event.type === "tool_call") {
          setToolInProgress(event.name);
        } else if (event.type === "content_reset") {
          // What streamed so far was the model thinking out loud before looking something up,
          // not the answer to this question.
          setStreamingText("");
        } else if (event.type === "content_delta") {
          setToolInProgress(null);
          setStreamingText((prev) => prev + event.text);
        } else if (event.type === "done") {
          // On the graceful-degradation path (UC-7), the backend sends an `error` event
          // immediately followed by `done` — the assistant message in `done` already carries
          // that same unavailability notice, rendered as a normal bubble (identical to how
          // it reads after a reload), so the `error` event itself needs no separate banner.
          // Replaces the streamed draft with the persisted message, matched by id so a
          // duplicate `done` (or a refetch that already brought it in) cannot double it up.
          setMessages((prev) =>
            prev.some((message) => message.id === event.message.id)
              ? prev
              : [...prev, event.message]
          );
          setStreamingText("");
          setToolInProgress(null);
        }
      }, controller.signal);
    } catch {
      setErrorMessage(
        controller.signal.aborted ? t("chat.timeout") : t("chat.unreachable")
      );
    } finally {
      clearTimeout(timeout);
      abortRef.current = null;
      isSendingRef.current = false;
      setIsSending(false);
      // The session's title (derived from the first message) and its position in the
      // sidebar's most-recently-active ordering may have changed. `exact` keeps this off the
      // session-detail query, whose key starts with the same two segments: refetching it here
      // is what used to overwrite this conversation mid-flight.
      void queryClient.invalidateQueries({ queryKey: ["chat", "sessions"], exact: true });
    }
  }

  const showSuggestions = messages.length === 0 && !isSending;
  // Something is running but nothing has been rendered for it yet: without this the UI sat
  // silent for the whole prompt-processing wait.
  const showThinking = isSending && !streamingText && !toolInProgress;

  return (
    <Card className="flex flex-1 flex-col overflow-hidden">
      <CardContent className="flex flex-1 flex-col gap-4 overflow-hidden">
        <ChatAttachments sessionId={session.id} />
        <div
          ref={scrollRef}
          role="log"
          aria-label={t("chat.conversation")}
          className="flex flex-1 flex-col gap-4 overflow-y-auto"
          aria-live="polite"
        >
          {messages.length === 0 && !streamingText && (
            <p className="text-sm text-muted-foreground">{t("chat.emptyHint")}</p>
          )}
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          {toolInProgress && (
            <p className="text-xs text-muted-foreground" role="status">
              {t("chat.lookingUp", { tool: toolInProgress })}
            </p>
          )}
          {showThinking && (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
              <span
                aria-hidden="true"
                className="size-1.5 animate-pulse rounded-full bg-muted-foreground"
              />
              {t("chat.thinking")}
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
            {SUGGESTED_QUESTIONS.map((key) => (
              <Button
                key={key}
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void submit(t(`chat.suggestion.${key}`))}
              >
                {t(`chat.suggestion.${key}`)}
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
            {t("chat.messageLabel")}
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
            placeholder={t("chat.placeholder")}
            rows={2}
            className="flex-1 resize-none rounded-lg border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
          {/* The box stays writable while an answer is generating: the next question can be
              composed meanwhile, only sending it waits. Nothing but the in-flight turn can
              disable this any more. */}
          <Button type="submit" disabled={isSending || !input.trim()}>
            {isSending ? t("chat.answering") : t("chat.send")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
