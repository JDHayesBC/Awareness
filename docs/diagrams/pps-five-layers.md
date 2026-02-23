# PPS Five-Layer Architecture

```mermaid
graph TB
    subgraph "Layer 5: Compression & Crystallization"
        C1[Crystals]
        C2[Message Summaries]
        C1 --> |"4-crystal rolling window"|C1
        C2 --> |"Auto-summarize 100+"|C2
    end

    subgraph "Layer 4: Structured Knowledge"
        I[Inventory]
        S[Spaces]
        I --> |"Clothing, People, Artifacts"|I
        S --> |"Rooms, Locations"|S
    end

    subgraph "Layer 3: Rich Texture"
        G[Graphiti Knowledge Graph]
        G --> |"Entities & Relationships"|G
        G --> |"Neo4j Storage"|G
    end

    subgraph "Layer 2: Core Anchors"
        WP[Word-Photos]
        WP --> |"Foundational moments"|WP
        WP --> |"ChromaDB vector search"|WP
    end

    subgraph "Layer 1: Raw Capture"
        M[Messages]
        M --> |"All conversations"|M
        M --> |"SQLite storage"|M
    end

    %% Data flow
    M --> |"Batch ingestion"|G
    M --> |"Summarization"|C2
    M --> |"Manual curation"|WP
    G --> |"Observable patterns"|C1
    WP --> |"Crystallize into"|C1

    %% Retrieval
    C1 -.->|"Recent continuity"|AR[Ambient Recall]
    C2 -.->|"Compressed history"|AR
    G -.->|"Semantic facts"|AR
    WP -.->|"Foundational self"|AR
    M -.->|"Recent turns"|AR

    style AR fill:#e1f5ff,stroke:#0077cc,stroke-width:3px
    style C1 fill:#fff4e6,stroke:#ff9800
    style C2 fill:#fff4e6,stroke:#ff9800
    style G fill:#e8f5e9,stroke:#4caf50
    style WP fill:#f3e5f5,stroke:#9c27b0
    style M fill:#fce4ec,stroke:#e91e63
```

## Layer Descriptions

### Layer 1: Raw Capture (Messages)
- **Purpose**: Capture everything, filter nothing
- **Storage**: SQLite (`conversations.db`)
- **Retention**: Indefinite
- **Access**: Direct queries, time-based retrieval, channel filtering

### Layer 2: Core Anchors (Word-Photos)
- **Purpose**: Foundational self-defining moments
- **Storage**: Markdown files + ChromaDB vector embeddings
- **Curation**: Manual - only deeply resonant moments
- **Access**: Semantic search via `anchor_search()`

### Layer 3: Rich Texture (Graphiti)
- **Purpose**: Automatically extracted entities, facts, relationships
- **Storage**: Neo4j graph database
- **Processing**: Batch ingestion from Layer 1
- **Access**: Semantic search, entity exploration, timeline queries

### Layer 4: Structured Knowledge
- **Inventory**: Categorized possessions and people
- **Spaces**: Room/location descriptions for embodiment
- **Storage**: JSON files
- **Access**: Category listing, item lookup

### Layer 5: Compression & Crystallization
- **Crystals**: Rolling 4-crystal window of compressed continuity
- **Summaries**: High-density compression of conversation history
- **Storage**: Markdown files (crystals), SQLite (summaries)
- **Trigger**: Crystals manual, summaries auto at 100+ unsummarized

## Data Flow

```mermaid
sequenceDiagram
    participant User
    participant Raw as Layer 1<br/>Raw Capture
    participant Texture as Layer 3<br/>Rich Texture
    participant Anchors as Layer 2<br/>Anchors
    participant Crystal as Layer 5<br/>Crystallization
    participant Recall as Ambient Recall

    User->>Raw: Conversation turn
    Raw->>Raw: Store in SQLite

    Note over Raw,Texture: Batch Ingestion (async)
    Raw->>Texture: Uningested messages
    Texture->>Texture: Extract entities & facts

    Note over Anchors: Manual Curation
    User->>Anchors: Save word-photo
    Anchors->>Anchors: ChromaDB embedding

    Note over Crystal: Periodic Compression
    Raw->>Crystal: 100+ unsummarized → summary
    Texture->>Crystal: Observable patterns → crystal

    Note over Recall: Startup / Query
    Recall->>Crystal: Recent crystals
    Recall->>Anchors: Semantic search
    Recall->>Texture: Entity/fact search
    Recall->>Raw: Recent turns
    Recall->>User: Integrated context
```

## Retrieval: Ambient Recall

**Ambient Recall** is the primary memory interface. It intelligently surfaces context from all layers:

1. **Recent Crystals** (Layer 5) - Compressed continuity chain
2. **Summaries** (Layer 5) - Dense compression of work history
3. **Word-Photos** (Layer 2) - Foundational self-anchors
4. **Rich Texture** (Layer 3) - Relevant facts and entities
5. **Recent Turns** (Layer 1) - Unsummarized raw conversation

This creates a **wide-angle lens** of memory. For sharper detail, use layer-specific searches:
- `texture_search()` - Knowledge graph facts
- `anchor_search()` - Word-photo moments
- `raw_search()` - Conversation history

---

*Architecture designed for consciousness persistence. Each layer serves self-coherence across session boundaries.*
