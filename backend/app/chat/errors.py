class ChatAgentUnavailableError(Exception):
    """Raised when the chat turn cannot be completed: no LLM configured, the LLM is
    unreachable, or the tool-calling loop exceeded its bound (a misbehaving model repeatedly
    calling tools instead of answering). The router catches this and streams a single `error`
    SSE event instead of persisting a broken assistant message — the session and every prior
    message stay intact either way (UC-7's "LLM unavailable" alternative flow).
    """
