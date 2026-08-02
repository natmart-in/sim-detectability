"""The world: a graph of locations with objects and documents, plus agent positions.

Phase 1 runs everything in eager mode: all state is materialized at build time.
The optimisation suite (Phase 3) will hook into the same structures behind flags.
"""
from collections import deque
from dataclasses import dataclass, field


@dataclass
class WorldObject:
    id: str
    name: str
    location_id: str
    description: str
    state: dict = field(default_factory=dict)


@dataclass
class Document:
    id: str
    title: str
    location_id: str  # where it can be read
    content: str


@dataclass
class Location:
    id: str
    name: str
    description: str
    neighbors: list[str]
    ambient: str = ""


class World:
    def __init__(self):
        self.locations: dict[str, Location] = {}
        self.objects: dict[str, WorldObject] = {}
        self.documents: dict[str, Document] = {}
        self.agent_positions: dict[str, str] = {}  # agent name -> location id
        self._paths: dict[tuple[str, str], list[str]] = {}

    def add_location(self, loc: Location):
        self.locations[loc.id] = loc

    def add_object(self, obj: WorldObject):
        self.objects[obj.id] = obj

    def add_document(self, doc: Document):
        self.documents[doc.id] = doc

    def objects_at(self, loc_id: str) -> list[WorldObject]:
        return sorted(
            (o for o in self.objects.values() if o.location_id == loc_id),
            key=lambda o: o.id,
        )

    def documents_at(self, loc_id: str) -> list[Document]:
        return sorted(
            (d for d in self.documents.values() if d.location_id == loc_id),
            key=lambda d: d.id,
        )

    def agents_at(self, loc_id: str) -> list[str]:
        return sorted(a for a, p in self.agent_positions.items() if p == loc_id)

    def path(self, src: str, dst: str) -> list[str]:
        """BFS shortest path (list of location ids, excluding src, including dst)."""
        if src == dst:
            return []
        key = (src, dst)
        if key in self._paths:
            return self._paths[key]
        prev: dict[str, str | None] = {src: None}
        q = deque([src])
        while q:
            cur = q.popleft()
            if cur == dst:
                break
            for n in sorted(self.locations[cur].neighbors):
                if n not in prev:
                    prev[n] = cur
                    q.append(n)
        if dst not in prev:
            raise ValueError(f"no path from {src} to {dst}")
        path = []
        node: str | None = dst
        while node is not None and node != src:
            path.append(node)
            node = prev[node]
        path.reverse()
        self._paths[key] = path
        return path

    def validate(self):
        for loc in self.locations.values():
            for n in loc.neighbors:
                assert n in self.locations, f"{loc.id} -> unknown neighbor {n}"
                assert loc.id in self.locations[n].neighbors, (
                    f"asymmetric edge {loc.id} <-> {n}"
                )
