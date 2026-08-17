"""The one language the whole station runs in (issue #50).

Everything the operator can read is written in this language: the screens, the generated
reports, and the analysis prose the agent chain writes. It is a single station-wide setting
(`ui_language` in `SystemConfig`) rather than a per-user preference because the process that
writes most of that text, the Celery agent worker, runs with no user in context at all: a
board analysed overnight has to come out in *some* language, and the only sensible answer is
the one the station is set to.

`app.reports.strings.ReportLanguage` is an alias of `Language`, kept because reports were
language-aware before anything else was and their call sites read better naming the
report's language explicitly.
"""

import enum
from typing import Any


class Language(enum.StrEnum):
    EN = "en"
    PT = "pt"


DEFAULT_LANGUAGE = Language.EN

# `SystemConfig` key holding the station's language. Read through
# `app.settings.service.get_language` rather than by hand, so the fallback stays in one place.
LANGUAGE_CONFIG_KEY = "ui_language"


def coerce_language(raw: Any, *, default: Language = DEFAULT_LANGUAGE) -> Language:
    """A stored/received value read as a `Language`, falling back instead of raising.

    Callers are rendering something the operator asked for: a value that no longer maps to a
    supported language should show up as English text, never as a 500 or a failed report.
    """
    if isinstance(raw, Language):
        return raw
    try:
        return Language(str(raw).strip().lower())
    except (ValueError, AttributeError):
        return default
