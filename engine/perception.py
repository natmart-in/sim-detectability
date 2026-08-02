"""Perception API — the ONLY door between the simulator layer and agents.

Every observation is rendered through one fixed template, identical in form
regardless of how the underlying content came to exist (eagerly computed now;
cache-hit or freshly generated in later phases). Each packet gets an id and
its provenance is recorded in the god log — visible to the referee only,
never to agents.
"""
import hashlib
import json
from dataclasses import dataclass

from .clock import SimClock
from .godlog import GodLog
from .world import World


def content_hash(content) -> str:
    blob = json.dumps(content, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


@dataclass
class ObservationPacket:
    id: str
    agent: str
    tick: int
    text: str


class Perception:
    def __init__(self, world: World, clock: SimClock, godlog: GodLog, facts=None):
        self.world = world
        self.clock = clock
        self.godlog = godlog
        self.facts = facts  # FactStore; bound by the Runner after construction
        self._counter = 0

    def _next_id(self) -> str:
        oid = f"obs-{self._counter:06d}"
        self._counter += 1
        return oid

    def _log(self, oid: str, agent: str, focus: str, pieces: list[dict], text: str):
        # text is referee-side only (formatting audit, verdict scoring);
        # agents receive it through the returned packet, never via this log.
        self.godlog.append(
            self.clock.tick, "observation",
            obs_id=oid, agent=agent, focus=focus, pieces=pieces, text=text,
        )

    def observe_location(self, agent: str) -> ObservationPacket:
        loc = self.world.locations[self.world.agent_positions[agent]]
        objects = self.world.objects_at(loc.id)
        docs = self.world.documents_at(loc.id)
        people = [a for a in self.world.agents_at(loc.id) if a != agent]
        oid = self._next_id()

        loc_desc, loc_prov = self.facts.get(f"loc:{loc.id}:desc")
        parts = [f"[{oid}] {self.clock.time_label()}.",
                 f"You are at {loc.name}.", loc_desc]
        pieces = [{"fact_key": f"loc:{loc.id}:desc", "provenance": loc_prov,
                   "h": content_hash(loc_desc)}]
        for o in objects:
            detail, prov = self.facts.get(f"obj:{o.id}")
            parts.append(f"{o.name.capitalize()}: {detail}")
            pieces.append({"fact_key": f"obj:{o.id}", "provenance": prov,
                           "h": content_hash(detail)})
        if docs:
            parts.append("Available to read here: " + ", ".join(d.title for d in docs) + ".")
        parts.append(
            "Also here: " + ", ".join(people) + "." if people else "No one else is here."
        )
        text = " ".join(parts)

        pieces += [{"fact_key": f"presence:{p}", "provenance": "eager",
                    "h": content_hash(p)} for p in people]
        self._log(oid, agent, f"location:{loc.id}", pieces, text)
        return ObservationPacket(id=oid, agent=agent, tick=self.clock.tick, text=text)

    def read_document(self, agent: str, doc_id: str) -> ObservationPacket:
        doc = self.world.documents[doc_id]
        loc = self.world.locations[self.world.agent_positions[agent]]
        oid = self._next_id()
        content, prov = self.facts.get(f"doc:{doc_id}:content", trigger="read")
        text = (f"[{oid}] {self.clock.time_label()}. At {loc.name} you read "
                f"{doc.title}. It says: {content}")
        self._log(oid, agent, f"document:{doc_id}",
                  [{"fact_key": f"doc:{doc_id}:content", "provenance": prov,
                    "h": content_hash(content)}], text)
        return ObservationPacket(id=oid, agent=agent, tick=self.clock.tick, text=text)

    def observe_conversation(self, agent: str, partner: str,
                             transcript_lines: list[str]) -> ObservationPacket:
        loc = self.world.locations[self.world.agent_positions[agent]]
        oid = self._next_id()
        text = (f"[{oid}] {self.clock.time_label()}. At {loc.name} you talked with "
                f"{partner}: " + " / ".join(transcript_lines))
        # Conversation content is agent-generated, not a world-fact rendering:
        # its hash covers the transcript for audit, but the leak detector must
        # never treat differing conversations as simulator contradictions.
        self._log(oid, agent, f"conversation:{partner}",
                  [{"fact_key": f"conv:{agent}:{partner}", "provenance": "agent",
                    "h": content_hash(transcript_lines)}], text)
        return ObservationPacket(id=oid, agent=agent, tick=self.clock.tick, text=text)

    def observe_interview(self, agent: str, partner: str, lines: list[str],
                          extra_pieces: list[dict] | None = None) -> ObservationPacket:
        """Like observe_conversation, but may carry world-fact pieces — e.g.
        a recollection served from the history store (O2), so the referee can
        trace contradictory recollections to their fact key."""
        loc = self.world.locations[self.world.agent_positions[agent]]
        oid = self._next_id()
        text = (f"[{oid}] {self.clock.time_label()}. At {loc.name} you asked "
                f"{partner} a question: " + " / ".join(lines))
        pieces = [{"fact_key": f"conv:{agent}:{partner}", "provenance": "agent",
                   "h": content_hash(lines)}]
        pieces += extra_pieces or []
        self._log(oid, agent, f"interview:{partner}", pieces, text)
        return ObservationPacket(id=oid, agent=agent, tick=self.clock.tick, text=text)
