"""Background translation of an already-written analysis into the station's language (#50).

`app.analyses.localization` can translate on read, but only reports can afford to: a local
CPU model takes minutes to answer, and the analysis detail screen cannot hang a page load on
that. So the screen asks for the free paths only (cache, baseline rebuild) and, when a board's
agent-written prose is still in the other language, the API enqueues this task and answers
immediately with the original text. The translation lands in `Analysis.translations`, an
`analysis.translated` event goes out, and the screen refetches into the cached version.

Routed to the `agents` queue on purpose: it is the queue that owns the LLM. Running at the
agents worker's concurrency of 1 means a translation waits behind an in-flight board analysis
instead of competing with it for the same CPU (see the local LLM envelope in the README).

Failure is a no-op, not an error. `localize_analysis` never raises and returns the stored text
when it can't do better, so the worst case is exactly the state the screen already shows.
"""

import asyncio
import logging
import uuid

from app.analyses.localization import analysis_language, localize_analysis
from app.core.language import coerce_language
from app.events.publisher import publish_event
from app.models import Analysis
from app.tasks.celery_app import celery_app
from app.tasks.db import task_db_session

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.translation.translate_analysis")
def translate_analysis(analysis_id: str, language: str) -> None:
    asyncio.run(_translate_analysis_async(analysis_id, language))


async def _translate_analysis_async(analysis_id: str, language: str) -> None:
    target = coerce_language(language)
    async with task_db_session() as db:
        analysis = await db.get(Analysis, uuid.UUID(analysis_id))
        if analysis is None:
            return
        # Several screen loads can enqueue this before the first one finishes, so the task is
        # written to be safely repeatable: by the time a duplicate runs, `localize_analysis`
        # finds the cache the first one wrote and returns without calling the model again.
        localized = await localize_analysis(db, analysis, language=target)
        if localized is None or localized.language is not target:
            logger.info("Analysis %s could not be translated to %s", analysis_id, target.value)
            return
        if analysis_language(analysis) is target:
            return

        await publish_event(
            "analysis.translated",
            {
                "id": str(analysis.image_id),
                "analysis_id": str(analysis.id),
                "language": target.value,
            },
        )
