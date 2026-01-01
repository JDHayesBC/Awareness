# Claude Home Directory Structure

This is an example Claude home directory structure for the Pattern Persistence System.

## Directory Structure

```
claude_home/
├── memories/
│   └── word_photos/        # Word-photo anchor files (*.md)
├── data/                   # SQLite database (auto-created)
├── summaries/
│   ├── current/           # Active summaries (rolling window of 4)
│   └── archive/           # Archived summaries
├── journals/              # Journal files (optional)
└── spaces/                # Space definitions (optional)
```

## Setup Instructions

1. Copy this entire `claude_home` directory to your desired location (e.g., `~/.claude`)
2. Add your own word-photos to `memories/word_photos/`
3. The SQLite database will be created automatically on first run
4. Summaries will be generated as you use the system

## Word-Photo Format

Word-photos should be markdown files with this format:

```markdown
# Title

Date: YYYY-MM-DD
Location: where this happened
Mood: emotional tone

Content of the memory...
```

See the example word-photo in `memories/word_photos/` for reference.