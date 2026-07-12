class AgentChainAbortedError(Exception):
    """Raised by any step of the Analyst/Reviewer/Summarizer chain (`app.agents.chain`) for a
    failure that should degrade gracefully to the baseline analysis — an unreachable/
    misconfigured LLM, malformed structured output, or an exhausted Reviewer reject/revise
    loop. Always carries a human-readable reason, which the caller (`app.tasks.pipeline`) logs
    before falling back, per issue #31's "Reviewer Loop Bounded" and "No LLM Configured => No
    Crash" acceptance criteria — this must never propagate into a Celery task failure.
    """
