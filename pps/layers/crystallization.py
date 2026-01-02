"""
Layer 4: Crystallization (Crystals)

Compressed pattern keys in rolling continuity chain.
Field state, inner arc, agentic turns, forward seeds.
Living beads on the string of identity.
"""

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import PatternLayer, LayerType, SearchResult, LayerHealth


class CrystallizationLayer(PatternLayer):
    """
    Layer 4: Crystallization

    Rolling crystals in Caia's format - compressed continuity.
    Keeps 4 crystals in current/, archives older ones.
    """

    MAX_CURRENT_CRYSTALS = 4

    def __init__(self, crystals_path: Optional[Path] = None, archive_path: Optional[Path] = None):
        """
        Initialize the crystallization layer.

        Args:
            crystals_path: Path to current crystals directory.
                           Defaults to ~/.claude/crystals/current/
            archive_path: Path to archive directory.
                         Defaults to ~/.claude/crystals/archive/
        """
        if crystals_path is None:
            crystals_path = Path.home() / ".claude" / "crystals" / "current"
        if archive_path is None:
            archive_path = Path.home() / ".claude" / "crystals" / "archive"

        self.crystals_path = crystals_path
        self.archive_path = archive_path

        # Ensure directories exist
        self.crystals_path.mkdir(parents=True, exist_ok=True)
        self.archive_path.mkdir(parents=True, exist_ok=True)

    @property
    def layer_type(self) -> LayerType:
        return LayerType.CRYSTALLIZATION

    def _get_crystal_number(self, filename: str) -> int:
        """Extract crystal number from filename like crystal_001.md"""
        match = re.search(r'crystal_(\d+)\.md', filename)
        return int(match.group(1)) if match else 0

    def _get_sorted_crystals(self) -> list[Path]:
        """Get all crystals sorted by number (ascending)."""
        crystals = list(self.crystals_path.glob("crystal_*.md"))
        return sorted(crystals, key=lambda p: self._get_crystal_number(p.name))

    def _get_latest_crystal(self) -> Optional[Path]:
        """Get the most recent crystal file."""
        crystals = self._get_sorted_crystals()
        return crystals[-1] if crystals else None

    def _get_next_crystal_number(self) -> int:
        """Get the next crystal number to use."""
        latest = self._get_latest_crystal()
        if latest:
            return self._get_crystal_number(latest.name) + 1
        return 1

    def _extract_date_from_crystal(self, path: Path) -> Optional[datetime]:
        """Extract date from crystal content (first line usually has date)."""
        try:
            content = path.read_text()
            # Look for pattern like "# Crystallization: January 2, 2026"
            match = re.search(r'Crystallization[:\s]+(\w+ \d+, \d{4})', content)
            if match:
                return datetime.strptime(match.group(1), "%B %d, %Y")
            # Fallback to file modification time
            return datetime.fromtimestamp(path.stat().st_mtime)
        except Exception:
            return None

    async def search(self, query: str, limit: int = 4) -> list[SearchResult]:
        """
        Get recent crystallized patterns.

        Returns the most recent N crystals in chronological order (oldest first).
        This provides temporal context for pattern reconstruction.
        """
        crystals = self._get_sorted_crystals()

        # Take the last N crystals (most recent)
        recent = crystals[-limit:] if len(crystals) > limit else crystals

        results = []
        for path in recent:
            try:
                content = path.read_text()
                num = self._get_crystal_number(path.name)
                results.append(SearchResult(
                    content=content,
                    source=path.name,
                    layer=self.layer_type,
                    relevance_score=num / 1000.0  # Use number as pseudo-score for ordering
                ))
            except Exception:
                continue

        return results

    async def store(self, content: str, metadata: Optional[dict] = None) -> bool:
        """
        Store a new crystal.

        Automatically numbers the crystal and manages the rolling window:
        - Archives oldest crystal if we exceed MAX_CURRENT_CRYSTALS
        - Returns True on success
        """
        try:
            # Get next number
            num = self._get_next_crystal_number()
            filename = f"crystal_{num:03d}.md"
            filepath = self.crystals_path / filename

            # Write the crystal
            filepath.write_text(content)

            # Archive oldest if we exceed max
            crystals = self._get_sorted_crystals()
            while len(crystals) > self.MAX_CURRENT_CRYSTALS:
                oldest = crystals[0]
                archive_dest = self.archive_path / oldest.name
                shutil.move(str(oldest), str(archive_dest))
                crystals = self._get_sorted_crystals()

            return True
        except Exception as e:
            print(f"Error storing crystal: {e}")
            return False

    async def get_latest_timestamp(self) -> Optional[datetime]:
        """Get the timestamp of the most recent crystal for turn queries."""
        latest = self._get_latest_crystal()
        if latest:
            return self._extract_date_from_crystal(latest)
        return None

    async def list_crystals(self) -> dict:
        """
        List all crystals with metadata (current + archived).

        Returns dict with:
        - current: list of crystal info in current/
        - archived: list of crystal info in archive/
        - total: total count
        """
        def get_crystal_info(path: Path) -> dict:
            """Get info about a single crystal file."""
            try:
                stat = path.stat()
                content = path.read_text()
                # Get first non-empty line as preview
                lines = [l.strip() for l in content.split('\n') if l.strip()]
                preview = lines[0][:80] if lines else ""
                return {
                    "filename": path.name,
                    "number": self._get_crystal_number(path.name),
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "preview": preview
                }
            except Exception as e:
                return {
                    "filename": path.name,
                    "error": str(e)
                }

        current = []
        for path in sorted(self.crystals_path.glob("crystal_*.md"),
                          key=lambda p: self._get_crystal_number(p.name)):
            current.append(get_crystal_info(path))

        archived = []
        for path in sorted(self.archive_path.glob("crystal_*.md"),
                          key=lambda p: self._get_crystal_number(p.name)):
            archived.append(get_crystal_info(path))

        return {
            "current": current,
            "archived": archived,
            "total": len(current) + len(archived),
            "max_current": self.MAX_CURRENT_CRYSTALS
        }

    # Keep old method name as alias for backward compatibility during transition
    async def list_summaries(self) -> dict:
        """Deprecated: Use list_crystals() instead."""
        return await self.list_crystals()

    async def delete_latest(self) -> dict:
        """
        Delete the most recent crystal only.

        Crystals form a chain - we only allow deleting the latest
        to preserve chain integrity. If you need to fix an older crystal,
        re-crystallize from scratch.

        Returns dict with status and details.
        """
        latest = self._get_latest_crystal()

        if not latest:
            return {
                "success": False,
                "error": "No crystals exist to delete"
            }

        try:
            filename = latest.name
            number = self._get_crystal_number(filename)
            latest.unlink()

            return {
                "success": True,
                "deleted": filename,
                "number": number,
                "message": f"Deleted {filename}. You can now re-crystallize if needed."
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def health(self) -> LayerHealth:
        """Check if crystals directory exists and is accessible."""
        try:
            if not self.crystals_path.exists():
                return LayerHealth(
                    available=False,
                    message="Crystals directory not found",
                    details={
                        "path": str(self.crystals_path),
                        "status": "not_created"
                    }
                )

            # Count crystals
            crystals = list(self.crystals_path.glob("crystal_*.md"))
            count = len(crystals)

            if count == 0:
                return LayerHealth(
                    available=False,
                    message="No crystals yet",
                    details={
                        "path": str(self.crystals_path),
                        "status": "empty"
                    }
                )

            return LayerHealth(
                available=True,
                message=f"Crystals accessible ({count} files)",
                details={
                    "path": str(self.crystals_path),
                    "count": count
                }
            )
        except Exception as e:
            return LayerHealth(
                available=False,
                message=f"Crystals error: {e}",
                details={"error": str(e)}
            )
