from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import asyncpg
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(title="YouTube Notes API")

# CORS middleware to allow Chrome extension
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your extension ID
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database connection pool
db_pool = None


# Pydantic models
class NoteCreate(BaseModel):
    video_id: str
    timestamp: float
    note_text: str


class NoteResponse(BaseModel):
    id: int
    video_id: str
    timestamp: float
    note_text: str
    created_at: datetime


# Database connection
async def get_db_pool():
    global db_pool
    if db_pool is None:
        DATABASE_URL = os.getenv("DATABASE_URL")
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL not found in environment variables")
        db_pool = await asyncpg.create_pool(DATABASE_URL)
    return db_pool


@app.on_event("startup")
async def startup():
    """Initialize database connection and create tables"""
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        # Create notes table if it doesn't exist
        await conn.execute("""
                           CREATE TABLE IF NOT EXISTS notes
                           (
                               id
                               SERIAL
                               PRIMARY
                               KEY,
                               video_id
                               VARCHAR
                           (
                               20
                           ) NOT NULL,
                               timestamp FLOAT NOT NULL,
                               note_text TEXT NOT NULL,
                               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                               )
                           """)

        # Create index on video_id for faster lookups
        await conn.execute("""
                           CREATE INDEX IF NOT EXISTS idx_video_id
                               ON notes(video_id)
                           """)


@app.on_event("shutdown")
async def shutdown():
    """Close database connection"""
    global db_pool
    if db_pool:
        await db_pool.close()


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "ok", "message": "YouTube Notes API is running"}


@app.post("/notes", response_model=NoteResponse)
async def create_note(note: NoteCreate):
    """Create a new note for a video"""
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
                                  INSERT INTO notes (video_id, timestamp, note_text)
                                  VALUES ($1, $2, $3) RETURNING id, video_id, timestamp, note_text, created_at
                                  """, note.video_id, note.timestamp, note.note_text)

        return NoteResponse(**dict(row))


@app.get("/notes/{video_id}", response_model=List[NoteResponse])
async def get_notes(video_id: str):
    """Get all notes for a specific video, ordered by timestamp"""
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
                                SELECT id, video_id, timestamp, note_text, created_at
                                FROM notes
                                WHERE video_id = $1
                                ORDER BY timestamp ASC
                                """, video_id)

        return [NoteResponse(**dict(row)) for row in rows]


@app.get("/notes/search/{query}", response_model=List[NoteResponse])
async def search_notes(query: str):
    """Search notes by text content"""
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
                                SELECT id, video_id, timestamp, note_text, created_at
                                FROM notes
                                WHERE note_text ILIKE $1
                                ORDER BY created_at DESC
                                """, f"%{query}%")

        return [NoteResponse(**dict(row)) for row in rows]


@app.delete("/notes/{note_id}")
async def delete_note(note_id: int):
    """Delete a specific note"""
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        result = await conn.execute("""
                                    DELETE
                                    FROM notes
                                    WHERE id = $1
                                    """, note_id)

        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Note not found")

        return {"message": "Note deleted successfully"}


@app.put("/notes/{note_id}", response_model=NoteResponse)
async def update_note(note_id: int, note_text: str):
    """Update a note's text"""
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
                                  UPDATE notes
                                  SET note_text = $1
                                  WHERE id = $2 RETURNING id, video_id, timestamp, note_text, created_at
                                  """, note_text, note_id)

        if not row:
            raise HTTPException(status_code=404, detail="Note not found")

        return NoteResponse(**dict(row))


@app.get("/videos/recent")
async def get_recent_videos():
    """Get list of recently noted videos"""
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
                                SELECT video_id,
                                       COUNT(*)        as note_count,
                                       MAX(created_at) as last_note_at
                                FROM notes
                                GROUP BY video_id
                                ORDER BY last_note_at DESC LIMIT 20
                                """)

        return [dict(row) for row in rows]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)