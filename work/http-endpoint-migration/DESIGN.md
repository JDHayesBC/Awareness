# HTTP Endpoint Migration Design

## Overview

Phase 1 migrates 5 critical PPS tools from MCP-only to HTTP-accessible. These tools are blocking daemon autonomy because the reflection daemon cannot write memories without MCP.

## Endpoints to Implement

### 1. POST /tools/anchor_save

Save a word-photo to Layer 2 (Core Anchors).

**Request Model**:
```python
class AnchorSaveRequest(BaseModel):
    content: str          # The word-photo content in markdown
    title: str            # Title (used in filename)
    location: str = "terminal"  # Context tag
```

**Implementation**:
- Get CoreAnchorsChromaLayer from layers dict
- Call `layer.store(content, {"title": title, "location": location})`
- Return `{"success": bool, "message": str}`

**MCP Reference**: Lines 1130-1138 in server.py

---

### 2. POST /tools/crystallize

Save a new crystal to Layer 4 (Crystallization).

**Request Model**:
```python
class CrystallizeRequest(BaseModel):
    content: str          # Crystal content in markdown
```

**Implementation**:
- Get CrystallizationLayer from layers dict
- Call `layer.store(content)`
- Get latest crystal filename for response
- Return `{"success": bool, "filename": str}`

**MCP Reference**: Lines 1224-1235 in server.py

---

### 3. POST /tools/texture_add

Add content to Layer 3 (Rich Texture / Knowledge Graph).

**Request Model**:
```python
class TextureAddRequest(BaseModel):
    content: str          # Content to store
    channel: str = "manual"  # Source channel
```

**Implementation**:
- Get RichTextureLayerV2 from layers dict
- Call `layer.store(content, {"channel": channel})`
- Return `{"success": bool, "message": str}`

**MCP Reference**: Lines 1174-1183 in server.py

---

### 4. POST /tools/ingest_batch_to_graphiti

Batch ingest messages to Graphiti.

**Request Model**:
```python
class IngestBatchRequest(BaseModel):
    batch_size: int = 20
```

**Implementation**:
- Query uningested messages from SQLite
- Send to Graphiti via RichTextureLayerV2.store()
- Mark messages as ingested
- Return stats

**MCP Reference**: Needs research in server.py (around line 673)

---

### 5. POST /tools/enter_space

Enter a space and load its context.

**Request Model**:
```python
class EnterSpaceRequest(BaseModel):
    space_name: str
```

**Implementation**:
- Get InventoryLayer (needs to be added to server_http.py)
- Call `inventory.enter_space(space_name)`
- Return space description

**MCP Reference**: Lines 797-811 in server.py

---

## Dependencies

The HTTP server (`server_http.py`) currently initializes:
- `layers` dict with RAW_CAPTURE, CORE_ANCHORS, RICH_TEXTURE, CRYSTALLIZATION
- `message_summaries` layer

Need to add:
- `inventory` layer (for enter_space)

## Architecture Notes

1. All endpoints follow existing patterns in server_http.py
2. Use Pydantic models for request validation
3. Middleware already handles tracing
4. Error handling via HTTPException

## Testing Strategy

1. Unit tests with mocked layers
2. Integration test against running PPS Docker stack
3. Verify daemon can call each endpoint

## Related Files

- `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker/server_http.py` - HTTP server
- `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/server.py` - MCP server (reference)
- `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/layers/inventory.py` - Inventory layer
- `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/layers/core_anchors_chroma.py` - Anchors layer
- `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/layers/crystallization.py` - Crystal layer
- `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/layers/rich_texture_v2.py` - Texture layer
