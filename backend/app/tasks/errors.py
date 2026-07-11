class TransientProcessingError(Exception):
    """Raised by pipeline stage tasks for retryable failures — LLM unavailable, disk I/O
    hiccup (section 3.7). Anything else raised by a stage is treated as permanent and fails
    the task immediately, without burning retries on an error that won't self-resolve.
    """
