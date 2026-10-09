import json
import logging
import os
import textwrap
from typing import Any

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    RunContext,
    TurnHandlingOptions,
    cli,
    function_tool,
    inference,
    room_io,
    tts,
)
from livekit.plugins import ai_coustics, google, groq, deepgram

from prompts import SYSTEM_PROMPT
from services.art_institute import search_artworks

load_dotenv(".env.local")
logger = logging.getLogger("agent")




class Assistant(Agent):
    def __init__(self, room) -> None:
        self.room = room
        self._last_artwork_results: list[dict] = []

        super().__init__(
            llm=google.LLM(model="gemini-3.1-flash-lite"),
            instructions=textwrap.dedent(SYSTEM_PROMPT),
        )

    async def on_enter(self) -> None:
        self.session.generate_reply(
            instructions="Greet the user in one short, warm sentence as Sarjy and ask how you can help today. Do not mention artwork or tools.",
        )

    @function_tool()
    async def search_artwork(
        self,
        context: RunContext,
        query: str,
    ) -> dict[str, Any]:
        """Search museum collections for artwork candidates.

        Use the user's accumulated clues to investigate a plausible
        artwork hypothesis. Results are candidates, not confirmation.

        Args:
            query: A specific search query based on the user's clues.
        """
        logger.info("========== ARTWORK TOOL CALLED ==========")
        logger.info("query=%r", query)

        try:
            result = await search_artworks(query, limit=5)

            self._last_artwork_results = result.get("results", [])

            logger.info(
                "source=%r count=%s fallback=%s",
                result.get("source"),
                result.get("count"),
                result.get("fallback_used"),
            )
            for artwork in self._last_artwork_results:
                logger.info(
                    "candidate=%r artist=%r id=%r",
                    artwork.get("title"),
                    artwork.get("artist"),
                    artwork.get("id"),
                )
            return result

        except Exception:
            logger.exception("Unexpected artwork search failure")
            self._last_artwork_results = []
            return {
                "query": query,
                "source": None,
                "count": 0,
                "results": [],
                "fallback_used": False,
                "errors": [{"error": "The artwork search service is currently unavailable."}],
            }

    @function_tool()
    async def select_artwork(
        self,
        context: RunContext,
        artwork_id: int,
    ) -> dict[str, Any]:
        """Select an artwork candidate for display in the frontend.

        Use this after searching for artwork when one candidate best matches
        the user's clues. The artwork_id must come from the latest search.

        Args:
            artwork_id: The id of a candidate from the latest search.
        """
        logger.info("========== ARTWORK SELECTED ==========")
        logger.info("artwork_id=%s", artwork_id)

        for artwork in self._last_artwork_results:
            if artwork.get("id") == artwork_id:
                await self.room.local_participant.publish_data(
                    json.dumps({"type": "artwork_candidate", "artwork": artwork}).encode("utf-8"),
                    reliable=True,
                )
                return {"selected": True, "artwork": artwork}

        logger.warning("Artwork id %s not in latest search results", artwork_id)
        return {
            "selected": False,
            "artwork": None,
            "error": "The requested artwork was not found in the latest search results.",
        }




server = AgentServer()


@server.rtc_session(agent_name="sarjy-agent")
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    session = AgentSession(
        stt=groq.STT(model="whisper-large-v3-turbo", language="en"),
        tts=deepgram.TTS(model="aura-2-thalia-en"),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            interruption={"mode": "adaptive"},
            preemptive_generation={"enabled": False},
        ),
        expressive=False,
    )

    assistant = Assistant(ctx.room)

    logger.info("========== LLM CONFIG ==========")
    logger.info("LLM: %s", assistant.llm)
    logger.info("TOOLS: %s", assistant.tools)

    await session.start(
        agent=assistant,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(model=ai_coustics.EnhancerModel.QUAIL_VF_S),
            ),
        ),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)
