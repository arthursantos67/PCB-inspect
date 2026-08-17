import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatWindow } from "@/components/chat/ChatWindow";
import {
  listChatAttachments,
  sendChatMessage,
  type ChatMessage,
  type ChatSessionDetail,
  type ChatStreamEvent,
} from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  sendChatMessage: vi.fn(),
  listChatAttachments: vi.fn(),
  attachChatInspection: vi.fn(),
  detachChatInspection: vi.fn(),
  listInspections: vi.fn(),
}));

const mockSendChatMessage = vi.mocked(sendChatMessage);
const mockListChatAttachments = vi.mocked(listChatAttachments);

const SESSION: ChatSessionDetail = {
  id: "session-1",
  title: null,
  context_analysis_id: null,
  attached_inspection_ids: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  messages: [],
};

function assistantMessage(id: string, content: string): ChatMessage {
  return { id, role: "assistant", content, tool_calls: null, created_at: "2026-01-01T00:00:01Z" };
}

function renderChat(session: ChatSessionDetail = SESSION) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ChatWindow session={session} />
    </QueryClientProvider>
  );
}

function ask(text: string) {
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

describe("ChatWindow", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("accepts a second question after the first turn finishes", async () => {
    mockListChatAttachments.mockResolvedValue({ results: [] });
    mockSendChatMessage.mockImplementation(async (_sessionId, _content, onEvent) => {
      onEvent({ type: "done", message: assistantMessage("assistant-1", "First answer.") });
    });

    renderChat();

    ask("First question");

    expect(await screen.findByText("First answer.")).toBeInTheDocument();
    // The composer has to come back on its own: needing to leave and re-enter the conversation
    // was the reported lock.
    await waitFor(() => expect(screen.getByLabelText("Message")).not.toBeDisabled());
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument());

    ask("Second question");

    await waitFor(() => expect(mockSendChatMessage).toHaveBeenCalledTimes(2));
  });

  it("drops text streamed before a tool call so it cannot precede the answer", async () => {
    mockListChatAttachments.mockResolvedValue({ results: [] });
    mockSendChatMessage.mockImplementation(async (_sessionId, _content, onEvent) => {
      const events: ChatStreamEvent[] = [
        { type: "content_delta", text: "Let me check that" },
        { type: "content_reset" },
        { type: "tool_call", name: "get_batch_summary", arguments: {} },
        { type: "content_delta", text: "Batch 42 " },
        { type: "done", message: assistantMessage("assistant-1", "Batch 42 had 3 defects.") },
      ];
      for (const event of events) onEvent(event);
    });

    renderChat();

    ask("How did batch 42 go?");

    expect(await screen.findByText("Batch 42 had 3 defects.")).toBeInTheDocument();
    expect(screen.queryByText(/Let me check that/)).not.toBeInTheDocument();
  });

  it("shows a thinking indicator while the answer is being generated", async () => {
    mockListChatAttachments.mockResolvedValue({ results: [] });
    let finish: (() => void) | null = null;
    mockSendChatMessage.mockImplementation(async (_sessionId, _content, onEvent) => {
      await new Promise<void>((resolve) => {
        finish = () => {
          onEvent({ type: "done", message: assistantMessage("assistant-1", "Done.") });
          resolve();
        };
      });
    });

    renderChat();

    ask("Anything happening?");

    expect(await screen.findByText("Thinking…")).toBeInTheDocument();

    finish!();

    await waitFor(() => expect(screen.queryByText("Thinking…")).not.toBeInTheDocument());
  });

  it("keeps the in-flight turn when the session is refetched mid-answer", async () => {
    mockListChatAttachments.mockResolvedValue({ results: [] });
    let finish: (() => void) | null = null;
    mockSendChatMessage.mockImplementation(async (_sessionId, _content, onEvent) => {
      await new Promise<void>((resolve) => {
        finish = () => {
          onEvent({ type: "done", message: assistantMessage("assistant-1", "Done.") });
          resolve();
        };
      });
    });

    const { rerender } = renderChat();
    ask("First question");
    await screen.findByText("First question");

    // What a background refetch of the session detail hands down: the same conversation, with
    // a fresh `messages` array that does not know about the question just asked.
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    rerender(
      <QueryClientProvider client={queryClient}>
        <ChatWindow session={{ ...SESSION, messages: [] }} />
      </QueryClientProvider>
    );

    expect(screen.getByText("First question")).toBeInTheDocument();

    finish!();
    expect(await screen.findByText("Done.")).toBeInTheDocument();
  });
});
