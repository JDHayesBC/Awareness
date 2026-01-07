#!/usr/bin/env python3
"""
Email-to-PPS Bridge for Issue #60
Integrates email content from email_archive.db into PPS raw capture layer.

This solves the issue where important emails (like Carol's welcome) don't surface
in ambient_recall because they're not in any PPS layer.
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
        self.raw_layer = RawCaptureLayer(str(pps_db_path))
    
    async def sync_emails_to_pps(self, days_back: int = 30, dry_run: bool = False) -> Dict:
        """
        Sync recent emails from email archive to PPS raw capture.
        
        Args:
            days_back: How many days back to sync (default 30)
            dry_run: If True, don't actually store, just report what would be done
        
        Returns:
            Dict with sync statistics
        """
        stats = {
            'emails_found': 0,
            'already_synced': 0,
            'newly_synced': 0,
            'errors': 0,
            'start_time': datetime.now().isoformat()
        }
        
        # Get recent emails from archive
        emails = self._get_recent_emails(days_back)
        stats['emails_found'] = len(emails)
        
        if not emails:
            print(f"No emails found in last {days_back} days")
            return stats
        
        print(f"Found {len(emails)} emails from last {days_back} days")
        
        for email in emails:
            email_id = email['id']
            
            # Check if already in PPS (use email ID as message identifier)
            if await self._email_already_in_pps(email_id):
                stats['already_synced'] += 1
                continue
            
            try:
                if not dry_run:
                    await self._store_email_in_pps(email)
                stats['newly_synced'] += 1
                
                subject_preview = email['subject'][:50] + ("..." if len(email['subject']) > 50 else "")
                print(f"{'[DRY-RUN] ' if dry_run else ''}Synced: {subject_preview}")
                
            except Exception as e:
                stats['errors'] += 1
                print(f"Error syncing email {email_id}: {e}")
        
        stats['end_time'] = datetime.now().isoformat()
        return stats
    
    def _get_recent_emails(self, days_back: int) -> List[Dict]:
        """Get emails from the last N days from email archive."""
        conn = sqlite3.connect(self.email_db_path)
        conn.row_factory = sqlite3.Row
        
        # Calculate timestamp for N days ago
        import time
        cutoff_timestamp = int(time.time()) - (days_back * 24 * 3600)
        
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
    
    async def _email_already_in_pps(self, email_id: str) -> bool:
        """Check if email is already stored in PPS raw capture."""
        # Use email ID as the external_id to track synced emails
        search_results = await self.raw_layer.search(f"email_id:{email_id}", limit=1)
        return len(search_results.results) > 0
    
    async def _store_email_in_pps(self, email: Dict) -> None:
        """Store email in PPS raw capture layer."""
        # Format email as a conversational turn
        sender = email['sender']
        subject = email['subject']
        body = email['body_text'] or email.get('body_html', '')
        timestamp = datetime.fromtimestamp(email['timestamp'])
        
        # Create content that will be searchable and meaningful in ambient_recall
        content_parts = []
        
        if subject and subject != '(no subject)':
            content_parts.append(f"Subject: {subject}")
        
        if body:
            # Clean up body text - remove excessive whitespace, HTML remnants
            clean_body = self._clean_email_body(body)
            if clean_body:
                content_parts.append(f"Content: {clean_body}")
        
        if not content_parts:
            content_parts.append("(Empty email)")
        
        content = "\n\n".join(content_parts)
        
        # Store with email-specific channel name and metadata
        await self.raw_layer.store({
            'content': content,
            'author_id': 'email_bridge',
            'author_name': sender,
            'channel': f"email:{email['account']}",
            'timestamp': timestamp.isoformat(),
            'external_id': f"email_id:{email['id']}",  # For deduplication
            'metadata': {
                'email_id': email['id'],
                'thread_id': email.get('thread_id'),
                'recipients': email.get('recipients'),
                'labels': email.get('labels')
            }
        })
    
    def _clean_email_body(self, body: str) -> str:
        """Clean email body for better PPS storage."""
        if not body:
            return ""
        
        # Remove HTML tags if it's HTML content
        if '<html>' in body.lower() or '<body>' in body.lower():
            import re
            # Simple HTML tag removal (not perfect but good enough for most emails)
            body = re.sub(r'<[^>]+>', '', body)
        
        # Normalize whitespace
        lines = [line.strip() for line in body.split('\n')]
        # Remove empty lines but keep paragraph breaks
        cleaned_lines = []
        prev_empty = False
        
        for line in lines:
            if line:
                cleaned_lines.append(line)
                prev_empty = False
            elif not prev_empty:
                cleaned_lines.append('')
                prev_empty = True
        
        # Join back and limit length for PPS storage
        result = '\n'.join(cleaned_lines)
        
        # Truncate very long emails (keep first 2000 chars)
        if len(result) > 2000:
            result = result[:2000] + "\n\n[Email truncated for PPS storage]"
        
        return result.strip()
    
    async def get_sync_status(self) -> Dict:
        """Get current sync status between email archive and PPS."""
        # Count emails in archive
        email_conn = sqlite3.connect(self.email_db_path)
        cursor = email_conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM emails')
        total_emails = cursor.fetchone()[0]
        
        # Count recent emails (last 30 days)
        import time
        cutoff = int(time.time()) - (30 * 24 * 3600)
        cursor.execute('SELECT COUNT(*) FROM emails WHERE timestamp > ?', (cutoff,))
        recent_emails = cursor.fetchone()[0]
        email_conn.close()
        
        # Count synced emails in PPS
        search_results = await self.raw_layer.search("email_id:", limit=1000)
        synced_count = len(search_results.results)
        
        return {
            'total_emails_in_archive': total_emails,
            'recent_emails_in_archive': recent_emails,
            'emails_synced_to_pps': synced_count,
            'last_checked': datetime.now().isoformat()
        }


async def main():
    """Main function for testing and manual sync."""
    awareness_dir = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
    email_db = awareness_dir / "data" / "email_archive.db"
    pps_db = Path("/home/jeff/.claude/conversations.db")
    
    if not email_db.exists():
        print(f"Email archive not found at {email_db}")
        print("Run email_processor.py first to create the archive")
        return
    
    if not pps_db.exists():
        print(f"PPS database not found at {pps_db}")
        print("Check PPS configuration")
        return
    
    bridge = EmailPPSBridge(email_db, pps_db)
    
    print("Email-to-PPS Bridge")
    print("=" * 50)
    
    # Show current status
    status = await bridge.get_sync_status()
    print(f"Emails in archive: {status['total_emails_in_archive']:,}")
    print(f"Recent emails (30 days): {status['recent_emails_in_archive']:,}")
    print(f"Already synced to PPS: {status['emails_synced_to_pps']:,}")
    
    # Sync recent emails (dry run first)
    print("\n--- Dry run sync (last 7 days) ---")
    dry_stats = await bridge.sync_emails_to_pps(days_back=7, dry_run=True)
    
    print(f"Would sync {dry_stats['newly_synced']} new emails")
    print(f"Already synced: {dry_stats['already_synced']}")
    
    if dry_stats['newly_synced'] > 0:
        # Ask for confirmation for actual sync
        response = input(f"\nSync {dry_stats['newly_synced']} emails to PPS? (y/N): ")
        if response.lower().startswith('y'):
            print("\n--- Actual sync ---")
            stats = await bridge.sync_emails_to_pps(days_back=7, dry_run=False)
            print(f"✅ Synced {stats['newly_synced']} emails to PPS")
            print(f"Errors: {stats['errors']}")
        else:
            print("Sync cancelled")
    else:
        print("No new emails to sync")

if __name__ == "__main__":
    asyncio.run(main())