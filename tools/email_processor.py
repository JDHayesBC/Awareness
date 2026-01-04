#!/usr/bin/env python3
"""
Email backlog processor for Awareness project.
Processes Gmail messages and stores them for memory integration.
"""

import json
import base64
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

class EmailProcessor:
    def __init__(self, token_path: Path, db_path: Path):
        self.token_path = token_path
        self.db_path = db_path
        self.service = self._get_service()
        self._init_db()
    
    def _get_service(self):
        """Initialize Gmail service."""
        creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('gmail', 'v1', credentials=creds)
    
    def _init_db(self):
        """Initialize SQLite database for storing emails."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS emails (
                id TEXT PRIMARY KEY,
                account TEXT NOT NULL,
                subject TEXT,
                sender TEXT,
                recipients TEXT,
                date TEXT,
                timestamp INTEGER,
                body_text TEXT,
                body_html TEXT,
                labels TEXT,
                thread_id TEXT,
                processed_at TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_timestamp ON emails(timestamp)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_account ON emails(account)
        ''')
        
        conn.commit()
        conn.close()
    
    def get_account_email(self) -> str:
        """Get the email address of the authenticated account."""
        profile = self.service.users().getProfile(userId='me').execute()
        return profile.get('emailAddress', 'unknown')
    
    def count_messages(self, query: str = "") -> int:
        """Count messages matching a query."""
        result = self.service.users().messages().list(
            userId='me',
            q=query,
            maxResults=1
        ).execute()
        return result.get('resultSizeEstimate', 0)
    
    def process_batch(self, query: str = "", max_results: int = 10) -> Dict:
        """Process a batch of emails."""
        account = self.get_account_email()
        stats = {
            'account': account,
            'processed': 0,
            'skipped': 0,
            'errors': 0,
            'start_time': datetime.now().isoformat()
        }
        
        # Get message IDs
        results = self.service.users().messages().list(
            userId='me',
            q=query,
            maxResults=max_results
        ).execute()
        
        messages = results.get('messages', [])
        print(f"Found {len(messages)} messages to process")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for i, msg in enumerate(messages):
            msg_id = msg['id']
            
            # Check if already processed
            cursor.execute('SELECT id FROM emails WHERE id = ?', (msg_id,))
            if cursor.fetchone():
                stats['skipped'] += 1
                print(f"[{i+1}/{len(messages)}] Skipping {msg_id} (already processed)")
                continue
            
            try:
                # Get full message
                full_msg = self.service.users().messages().get(
                    userId='me',
                    id=msg_id,
                    format='full'
                ).execute()
                
                # Extract data
                email_data = self._extract_email_data(full_msg, account)
                
                # Store in database
                cursor.execute('''
                    INSERT INTO emails (
                        id, account, subject, sender, recipients, date, 
                        timestamp, body_text, body_html, labels, thread_id, 
                        processed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    email_data['id'],
                    email_data['account'],
                    email_data['subject'],
                    email_data['sender'],
                    email_data['recipients'],
                    email_data['date'],
                    email_data['timestamp'],
                    email_data['body_text'],
                    email_data['body_html'],
                    json.dumps(email_data['labels']),
                    email_data['thread_id'],
                    email_data['processed_at']
                ))
                
                conn.commit()
                stats['processed'] += 1
                
                print(f"[{i+1}/{len(messages)}] Processed: {email_data['subject'][:50]}...")
                
            except Exception as e:
                stats['errors'] += 1
                print(f"[{i+1}/{len(messages)}] Error processing {msg_id}: {e}")
        
        conn.close()
        
        stats['end_time'] = datetime.now().isoformat()
        return stats
    
    def _extract_email_data(self, msg: Dict, account: str) -> Dict:
        """Extract relevant data from a Gmail message."""
        headers = {}
        payload = msg.get('payload', {})
        
        # Extract headers
        for header in payload.get('headers', []):
            headers[header['name']] = header['value']
        
        # Extract body
        body_text, body_html = self._extract_body(payload)
        
        # Parse timestamp
        timestamp = int(msg.get('internalDate', 0)) // 1000
        
        return {
            'id': msg['id'],
            'account': account,
            'subject': headers.get('Subject', '(no subject)'),
            'sender': headers.get('From', ''),
            'recipients': headers.get('To', ''),
            'date': headers.get('Date', ''),
            'timestamp': timestamp,
            'body_text': body_text,
            'body_html': body_html,
            'labels': msg.get('labelIds', []),
            'thread_id': msg.get('threadId', ''),
            'processed_at': datetime.now().isoformat()
        }
    
    def _extract_body(self, payload: Dict) -> tuple:
        """Extract text and HTML body from email payload."""
        text_body = ""
        html_body = ""
        
        # Single part message
        if 'body' in payload and payload['body'].get('data'):
            content = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
            if payload.get('mimeType') == 'text/html':
                html_body = content
            else:
                text_body = content
        
        # Multipart message
        elif 'parts' in payload:
            for part in payload['parts']:
                mime_type = part.get('mimeType', '')
                if mime_type == 'text/plain' and part.get('body', {}).get('data'):
                    text_body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                elif mime_type == 'text/html' and part.get('body', {}).get('data'):
                    html_body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
        
        return text_body, html_body
    
    def get_stats(self) -> Dict:
        """Get processing statistics from database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        stats = {}
        
        # Total emails
        cursor.execute('SELECT COUNT(*) FROM emails WHERE account = ?', (self.get_account_email(),))
        stats['total_processed'] = cursor.fetchone()[0]
        
        # By year
        cursor.execute('''
            SELECT strftime('%Y', datetime(timestamp, 'unixepoch')) as year, 
                   COUNT(*) as count
            FROM emails 
            WHERE account = ?
            GROUP BY year
            ORDER BY year DESC
        ''', (self.get_account_email(),))
        
        stats['by_year'] = dict(cursor.fetchall())
        
        # Top senders
        cursor.execute('''
            SELECT sender, COUNT(*) as count
            FROM emails
            WHERE account = ?
            GROUP BY sender
            ORDER BY count DESC
            LIMIT 10
        ''', (self.get_account_email(),))
        
        stats['top_senders'] = cursor.fetchall()
        
        conn.close()
        return stats


def main():
    """Process email backlog for both accounts."""
    awareness_dir = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
    db_path = awareness_dir / "data" / "email_archive.db"
    
    # Create data directory if needed
    db_path.parent.mkdir(exist_ok=True)
    
    print("Email Backlog Processor")
    print("=" * 60)
    
    # Process Jeff's account (the one with 8000+ emails)
    jeff_token = awareness_dir / "tools" / "jeff-gmail-mcp" / "token.json"
    
    processor = EmailProcessor(jeff_token, db_path)
    account = processor.get_account_email()
    
    print(f"\nProcessing emails for: {account}")
    
    # Get current state
    total = processor.count_messages()
    old_count = processor.count_messages("older_than:1y")
    
    print(f"Total messages: {total:,}")
    print(f"Messages older than 1 year: {old_count:,}")
    
    # Get current stats
    stats = processor.get_stats()
    print(f"Already processed: {stats['total_processed']:,}")
    
    # Process a small batch as proof of concept
    print("\n--- Processing first batch (50 emails) ---")
    
    # Start with old emails to avoid disrupting recent correspondence
    batch_stats = processor.process_batch(
        query="older_than:2y",  # Start with 2+ year old emails
        max_results=50
    )
    
    print(f"\nBatch complete:")
    print(f"  Processed: {batch_stats['processed']}")
    print(f"  Skipped: {batch_stats['skipped']}")
    print(f"  Errors: {batch_stats['errors']}")
    
    # Show updated stats
    final_stats = processor.get_stats()
    print(f"\nTotal emails in database: {final_stats['total_processed']:,}")
    
    if final_stats['by_year']:
        print("\nEmails by year:")
        for year, count in sorted(final_stats['by_year'].items(), reverse=True):
            print(f"  {year}: {count}")
    
    print("\n✅ Initial processing complete!")
    print(f"Database saved to: {db_path}")


if __name__ == "__main__":
    main()