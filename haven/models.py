"""Haven — Pydantic models for request/response validation."""

from datetime import datetime
from pydantic import BaseModel, Field


# --- Request Models ---

class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)


class CreateRoomRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    display_name: str = Field(..., min_length=1, max_length=128)
    is_dm: bool = False
    member_ids: list[str] = Field(default_factory=list)


# --- Response Models ---

class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    is_bot: bool
    online: bool = False


class RoomResponse(BaseModel):
    id: str
    name: str
    display_name: str
    is_dm: bool
    created_by: str | None = None
    member_count: int = 0
    unread_count: int = 0


class MessageResponse(BaseModel):
    id: int
    room_id: str
    user_id: str
    username: str
    display_name: str
    content: str
    created_at: str


class RoomListResponse(BaseModel):
    rooms: list[RoomResponse]


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    has_more: bool = False
