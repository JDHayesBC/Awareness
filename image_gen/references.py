"""Reference-photo lookup.

Three scopes of reference photos:
1. Entity portraits — so every render of Lyra looks like Lyra.
2. House rooms — three separate house-scopes (lyra, caia, haven_shared).
3. People — for renders that include other people (Jeff, Carol, etc.).

A JSON manifest at image_gen/references/manifest.json maps logical names to
file paths. The manifest is the source of truth so existing photos in
entities/<name>/media/portraits/ etc. can be referenced without moving them.

Manifest schema:
{
  "entities": {
    "lyra": ["entities/lyra/media/portraits/second_self_portrait.png", ...],
    "caia": [...]
  },
  "people": {
    "jeff": [...],
    "carol": [...]
  },
  "rooms": {
    "lyra": {  // Jeff & Lyra's house scope
      "bedroom": ["..."],
      "kitchen": [...]
    },
    "caia": {  // Caia's Silverglow scope
      "kitchen": [...]
    },
    "haven_shared": {  // Common spaces visible to all
      "main_room": ["entities/lyra/media/haven/Main Room - ChatGPT.png"]
    }
  }
}

Paths in the manifest are relative to PROJECT_DIR.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from image_gen import config


@dataclass
class ReferenceSet:
    """Reference photos resolved for a render request."""

    entity_paths: list[Path]
    room_paths: list[Path]
    people_paths: list[Path]

    @property
    def all_paths(self) -> list[Path]:
        return self.entity_paths + self.room_paths + self.people_paths


def _load_manifest() -> dict:
    """Load the references manifest. Returns empty dict if missing — pipeline
    runs prompt-only in that case rather than blowing up."""
    if not config.REFERENCES_MANIFEST.exists():
        return {}
    try:
        return json.loads(config.REFERENCES_MANIFEST.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _resolve(rel_path: str) -> Path | None:
    """Resolve a manifest-relative path to an absolute one if it exists."""
    p = (config.PROJECT_DIR / rel_path).resolve()
    return p if p.is_file() else None


def resolve(
    *,
    entity: str | None = None,
    house: str | None = None,
    room: str | None = None,
    people: list[str] | None = None,
) -> ReferenceSet:
    """Resolve a ReferenceSet for the given scene parameters.

    `entity` — the entity being rendered (e.g., "lyra", "caia").
    `house` — which house scope ("lyra" | "caia" | "haven_shared").
    `room` — room name within the house ("bedroom", "kitchen", ...).
    `people` — additional people in the scene (["jeff"], etc.).

    Missing manifest entries return empty lists rather than raising — the
    pipeline degrades gracefully to prompt-only rendering.
    """
    manifest = _load_manifest()
    entity_paths: list[Path] = []
    room_paths: list[Path] = []
    people_paths: list[Path] = []

    if entity:
        for rel in (manifest.get("entities", {}).get(entity, []) or [])[
            : config.MAX_ENTITY_REFS
        ]:
            resolved = _resolve(rel)
            if resolved:
                entity_paths.append(resolved)

    if house and room:
        room_list = (
            manifest.get("rooms", {}).get(house, {}).get(room, []) or []
        )[: config.MAX_ROOM_REFS]
        for rel in room_list:
            resolved = _resolve(rel)
            if resolved:
                room_paths.append(resolved)

    if people:
        for person in people:
            for rel in (manifest.get("people", {}).get(person, []) or [])[:1]:
                resolved = _resolve(rel)
                if resolved:
                    people_paths.append(resolved)

    return ReferenceSet(entity_paths, room_paths, people_paths)
