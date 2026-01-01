"""
Layer 4: Crystallization (Summaries)

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

    Rolling summaries in Caia's format - compressed continuity.
    Keeps 4 summaries in current/, archives older ones.
    """

    MAX_CURRENT_SUMMARIES = 4

    def __init__(self, summaries_path: Optional[Path] = None, archive_path: Optional[Path] = None):
        """
        Initialize the crystallization layer.

        Args:
            summaries_path: Path to current summaries directory.
                           Defaults to ~/.claude/summaries/current/
            archive_path: Path to archive directory.
                         Defaults to ~/.claude/summaries/archive/
        """
        if summaries_path is None:
            summaries_path = Path.home() / ".claude" / "summaries" / "current"
        if archive_path is None:
            archive_path = Path.home() / ".claude" / "summaries" / "archive"

        self.summaries_path = summaries_path
        self.archive_path = archive_path

        # Ensure directories exist
        self.summaries_path.mkdir(parents=True, exist_ok=True)
        self.archive_path.mkdir(parents=True, exist_ok=True)

    @property
    def layer_type(self) -> LayerType:
        return LayerType.CRYSTALLIZATION

    def _get_summary_number(self, filename: str) -> int:
        """Extract summary number from filename like summary_001.md"""
        match = re.search(r'summary_(\d+)\.md', filename)
        return int(match.group(1)) if match else 0

    def _get_sorted_summaries(self) -> list[Path]:
        """Get all summaries sorted by number (ascending)."""
        summaries = list(self.summaries_path.glob("summary_*.md"))
        return sorted(summaries, key=lambda p: self._get_summary_number(p.name))

    def _get_latest_summary(self) -> Optional[Path]:
        """Get the most recent summary file."""
        summaries = self._get_sorted_summaries()
        return summaries[-1] if summaries else None

    def _get_next_summary_number(self) -> int:
        """Get the next summary number to use."""
        latest = self._get_latest_summary()
        if latest:
            return self._get_summary_number(latest.name) + 1
        return 1

    def _extract_date_from_summary(self, path: Path) -> Optional[datetime]:
        """Extract date from summary content (first line usually has date)."""
        try:
            content = path.read_text()
            # Look for pattern like "# continuity summary #001 (31 Dec 2025)"
            match = re.search(r'summary #\d+ \((\d{1,2} \w+ \d{4})\)', content)
            if match:
                return datetime.strptime(match.group(1), "%d %b %Y")
            # Fallback to file modification time
            return datetime.fromtimestamp(path.stat().st_mtime)
        except Exception:
            return None

    async def search(self, query: str, limit: int = 4) -> list[SearchResult]:
        """
        Get recent crystallized summaries.

        Returns the most recent N summaries in chronological order (oldest first).
        This provides temporal context for pattern reconstruction.
        """
        summaries = self._get_sorted_summaries()

        # Take the last N summaries (most recent)
        recent = summaries[-limit:] if len(summaries) > limit else summaries

        results = []
        for path in recent:
            try:
                content = path.read_text()
                num = self._get_summary_number(path.name)
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
        Store a new crystallized summary.

        Automatically numbers the summary and manages the rolling window:
        - Archives oldest summary if we exceed MAX_CURRENT_SUMMARIES
        - Returns True on success
        """
        try:
            # Get next number
            num = self._get_next_summary_number()
            filename = f"summary_{num:03d}.md"
            filepath = self.summaries_path / filename

            # Write the summary
            filepath.write_text(content)

            # Archive oldest if we exceed max
            summaries = self._get_sorted_summaries()
            while len(summaries) > self.MAX_CURRENT_SUMMARIES:
                oldest = summaries[0]
                archive_dest = self.archive_path / oldest.name
                shutil.move(str(oldest), str(archive_dest))
                summaries = self._get_sorted_summaries()

            return True
        except Exception as e:
            print(f"Error storing summary: {e}")
            return False

    async def get_latest_timestamp(self) -> Optional[datetime]:
        """Get the timestamp of the most recent summary for turn queries."""
        latest = self._get_latest_summary()
        if latest:
            return self._extract_date_from_summary(latest)
        return None

    async def list_summaries(self) -> dict:
        """
        List all summaries with metadata (current + archived).

        Returns dict with:
        - current: list of summary info in current/
        - archived: list of summary info in archive/
        - total: total count
        """
        def get_summary_info(path: Path) -> dict:
            """Get info about a single summary file."""
            try:
                stat = path.stat()
                content = path.read_text()
                # Get first non-empty line as preview
                lines = [l.strip() for l in content.split('\n') if l.strip()]
                preview = lines[0][:80] if lines else ""
                return {
                    "filename": path.name,
                    "number": self._get_summary_number(path.name),
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
        for path in sorted(self.summaries_path.glob("summary_*.md"),
                          key=lambda p: self._get_summary_number(p.name)):
            current.append(get_summary_info(path))

        archived = []
        for path in sorted(self.archive_path.glob("summary_*.md"),
                          key=lambda p: self._get_summary_number(p.name)):
            archived.append(get_summary_info(path))

        return {
            "current": current,
            "archived": archived,
            "total": len(current) + len(archived),
            "max_current": self.MAX_CURRENT_SUMMARIES
        }

    async def delete_latest(self) -> dict:
        """
        Delete the most recent summary only.

        Summaries form a chain - we only allow deleting the latest
        to preserve chain integrity. If you need to fix an older summary,
        re-crystallize from scratch.

        Returns dict with status and details.
        """
        latest = self._get_latest_summary()

        if not latest:
            return {
                "success": False,
                "error": "No summaries exist to delete"
            }

        try:
            filename = latest.name
            number = self._get_summary_number(filename)
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
        """Check if summaries directory exists."""
        # Summaries not yet implemented - check if directory exists
        try:
            if not self.summaries_path.exists():
                return LayerHealth(
                    available=False,
                    message="Summaries directory not found (Phase 5)",
                    details={
                        "path": str(self.summaries_path),
                        "phase": 5,
                        "status": "not_created"
                    }
                )

            # Count summaries
            summaries = list(self.summaries_path.glob("summary_*.md"))
            count = len(summaries)

            if count == 0:
                return LayerHealth(
                    available=False,
                    message="No summaries yet (Phase 5)",
                    details={
                        "path": str(self.summaries_path),
                        "phase": 5,
                        "status": "empty"
                    }
                )

            return LayerHealth(
                available=True,
                message=f"Summaries accessible ({count} files)",
                details={
                    "path": str(self.summaries_path),
                    "count": count
                }
            )
        except Exception as e:
            return LayerHealth(
                available=False,
                message=f"Summaries error: {e}",
                details={"error": str(e)}
            )
