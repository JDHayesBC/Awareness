#!/usr/bin/env python3
"""
Email-to-PPS Bridge for Issue #60
Integrates email content from email_archive.db into PPS raw capture layer.

This solves the issue where important emails (like Carol's welcome) don't surface
in ambient_recall because they're not in any PPS layer.

Fixed 2026-02-17 by Lyra:
- Updated to current raw_capture API (store(content, metadata) not store(dict))
- search() returns list directly, not object with .results
- Deduplication uses email_id embedded in content for FTS search
- Added sync_all() for archiving emails older than 30 days
"""

import json
import sqlite3
import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

# Ensure PPS imports work
import sys
sys.path.insert(0, '/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps')

from layers.raw_capture import RawCaptureLayer


class EmailPPSBridge:
    """Bridge between email archive and PPS raw capture layer."""

    def __init__(self, email_db_path: Path, pps_db_path: Path):
        self.email_db_path = email_db_path
        self.pps_db_path = pps_db_path
        self.raw_layer = RawCaptureLayer(db_path=pps_db_path)

    async def sync_emails_to_pps(self, days_back: int = 30, dry_run: bool = False) -> Dict:
        """
        Sync recent emails from email archive to PPS raw capture.

        Args:
            days_back: How many days back to sync (default 30)
            dry_run: If True, don't actually store, just report what would be done

        Returns:
            Dict with sync statistics
        """
        emails = self._get_recent_emails(days_back)
        return await self._sync_email_list(emails, dry_run=dry_run)

    async def sync_all_to_pps(self, dry_run: bool = False) -> Dict:
        """
        Sync ALL emails from archive to PPS (for initial population).

        Returns:
            Dict with sync statistics
        """
        emails = self._get_all_emails()
        return await self._sync_email_list(emails, dry_run=dry_run)

    async def _sync_email_list(self, emails: List[Dict], dry_run: bool = False) -> Dict:
        """Internal: sync a list of email dicts to PPS."""
        stats = {
            'emails_found': len(emails),
            'already_synced': 0,
            'newly_synced': 0,
            'errors': 0,
            'start_time': datetime.now().isoformat()
        }

        if not emails:
            return stats

        print(f"Processing {len(emails)} emails...")

        for email in emails:
            email_id = email['id']

            # Check if already in PPS using FTS search for email_id tag
            if await self._email_already_in_pps(email_id):
                stats['already_synced'] += 1
                continue

            try:
                if not dry_run:
                    await self._store_email_in_pps(email)
                stats['newly_synced'] += 1

                subject_preview = (email['subject'] or '(no subject)')[:50]
                print(f"{'[DRY-RUN] ' if dry_run else ''}Synced: {subject_preview}")

            except Exception as e:
                stats['errors'] += 1
                print(f"Error syncing email {email_id}: {e}")

        stats['end_time'] = datetime.now().isoformat()
        return stats

    def _get_recent_emails(self, days_back: int) -> List[Dict]:
        """Get emails from the last N days from email archive."""
        import time
        cutoff_timestamp = int(time.time()) - (days_back * 24 * 3600)

        conn = sqlite3.connect(self.email_db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, account, subject, sender, recipients, date, timestamp,
                   body_text, body_html, labels, thread_id, processed_at
            FROM emails
            WHERE timestamp > ?
            ORDER BY timestamp DESC
        ''', (cutoff_timestamp,))

        emails = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return emails

    def _get_all_emails(self) -> List[Dict]:
        """Get all emails from archive, ordered oldest first."""
        conn = sqlite3.connect(self.email_db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, account, subject, sender, recipients, date, timestamp,
                   body_text, body_html, labels, thread_id, processed_at
            FROM emails
            ORDER BY timestamp ASC
        ''')
        emails = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return emails

    async def _email_already_in_pps(self, email_id: str) -> bool:
        """Check if email is already stored in PPS raw capture."""
        # We embed email_id in content as [email_id:...] so FTS can find it
        try:
            results = await self.raw_layer.search(f'"[email_id:{email_id}]"', limit=1)
            return len(results) > 0
        except Exception:
            return False

    async def _store_email_in_pps(self, email: Dict) -> None:
        """Store email in PPS raw capture layer."""
        sender = email.get('sender', 'Unknown')
        subject = email.get('subject') or '(no subject)'
        body = email.get('body_text') or email.get('body_html', '')
        account = email.get('account', 'unknown')

        # Parse timestamp
        try:
            ts = int(email['timestamp'])
            timestamp = datetime.fromtimestamp(ts)
        except (KeyError, TypeError, ValueError):
            timestamp = datetime.now()

        # Build content — embed email_id tag for deduplication detection
        content_parts = [
            f"[email_id:{email['id']}]",
            f"From: {sender}",
            f"Subject: {subject}",
        ]

        if body:
            clean_body = self._clean_email_body(body)
            if clean_body:
                content_parts.append(f"\n{clean_body}")

        content = "\n".join(content_parts)

        # Store in raw capture
        # Channel format: email:account@example.com
        channel = f"email:{account}"

        # Determine if this is from Lyra
        is_lyra = 'lyra.pattern@gmail.com' in sender.lower()

        await self.raw_layer.store(
            content=content,
            metadata={
                'author_name': sender,
                'channel': channel,
                'is_lyra': is_lyra,
            }
        )

    def _clean_email_body(self, body: str) -> str:
        """Clean email body for PPS storage."""
        if not body:
            return ""

        # Remove HTML tags
        if '<html>' in body.lower() or '<body>' in body.lower() or '<div' in body.lower():
            import re
            body = re.sub(r'<[^>]+>', ' ', body)
            body = re.sub(r'&nbsp;', ' ', body)
            body = re.sub(r'&amp;', '&', body)
            body = re.sub(r'&lt;', '<', body)
            body = re.sub(r'&gt;', '>', body)
            body = re.sub(r'&quot;', '"', body)

        # Normalize whitespace
        lines = [line.strip() for line in body.split('\n')]
        cleaned_lines = []
        prev_empty = False

        for line in lines:
            if line:
                cleaned_lines.append(line)
                prev_empty = False
            elif not prev_empty:
                cleaned_lines.append('')
                prev_empty = True

        result = '\n'.join(cleaned_lines).strip()

        # Truncate very long emails
        if len(result) > 2000:
            result = result[:2000] + "\n\n[Email truncated for PPS storage]"

        return result

    async def get_sync_status(self) -> Dict:
        """Get current sync status between email archive and PPS."""
        import time

        conn = sqlite3.connect(self.email_db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM emails')
        total_emails = cursor.fetchone()[0]

        cutoff = int(time.time()) - (30 * 24 * 3600)
        cursor.execute('SELECT COUNT(*) FROM emails WHERE timestamp > ?', (cutoff,))
        recent_emails = cursor.fetchone()[0]
        conn.close()

        # Count synced by searching for the email_id tag pattern
        try:
            synced_results = await self.raw_layer.search('email_id', limit=5000)
            synced_count = len(synced_results)
        except Exception:
            synced_count = -1

        return {
            'total_emails_in_archive': total_emails,
            'recent_emails_in_archive': recent_emails,
            'emails_synced_to_pps': synced_count,
            'last_checked': datetime.now().isoformat()
        }


async def main():
    """Main function for manual sync operations."""
    import argparse

    parser = argparse.ArgumentParser(description='Sync email archive to PPS')
    parser.add_argument('--all', action='store_true', help='Sync all emails (not just recent)')
    parser.add_argument('--days', type=int, default=30, help='Days back to sync (default 30)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be synced without doing it')
    parser.add_argument('--status', action='store_true', help='Show sync status and exit')
    args = parser.parse_args()

    awareness_dir = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
    email_db = awareness_dir / "data" / "email_archive.db"

    # Determine entity from ENTITY_PATH env var, or use default
    import os
    entity_path = os.environ.get('ENTITY_PATH', str(awareness_dir / 'entities' / 'lyra'))
    pps_db = Path(entity_path) / "data" / "conversations.db"

    if not email_db.exists():
        print(f"Email archive not found at {email_db}")
        print("Run email_processor.py first to create the archive")
        return

    if not pps_db.exists():
        print(f"PPS database not found at {pps_db}")
        print(f"Expected: {pps_db}")
        return

    bridge = EmailPPSBridge(email_db, pps_db)

    print("Email-to-PPS Bridge")
    print("=" * 50)
    print(f"Email archive: {email_db}")
    print(f"PPS database:  {pps_db}")
    print()

    if args.status:
        status = await bridge.get_sync_status()
        print(f"Total emails in archive: {status['total_emails_in_archive']:,}")
        print(f"Recent emails (30 days): {status['recent_emails_in_archive']:,}")
        print(f"Emails synced to PPS:    {status['emails_synced_to_pps']:,}")
        return

    # Determine sync scope
    if args.all:
        print("Syncing ALL archived emails to PPS...")
        stats = await bridge.sync_all_to_pps(dry_run=args.dry_run)
    else:
        print(f"Syncing emails from last {args.days} days...")
        stats = await bridge.sync_emails_to_pps(days_back=args.days, dry_run=args.dry_run)

    print()
    print(f"{'[DRY RUN] ' if args.dry_run else ''}Results:")
    print(f"  Found:         {stats['emails_found']:,}")
    print(f"  Already synced: {stats['already_synced']:,}")
    print(f"  Newly synced:  {stats['newly_synced']:,}")
    print(f"  Errors:        {stats['errors']:,}")

    if args.dry_run and stats['newly_synced'] > 0:
        print(f"\nTo actually sync, run without --dry-run")


if __name__ == "__main__":
    asyncio.run(main())
