import asyncio
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pyrogram import Client, filters, idle
from pyrogram.errors import RPCError
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
from yt_dlp import YoutubeDL

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("yashi-music")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_ID_RAW = os.getenv("API_ID", "").strip()
API_HASH = os.getenv("API_HASH", "").strip()
SESSION_STRING = os.getenv("SESSION_STRING", "").strip()
OWNER_ID_RAW = os.getenv("OWNER_ID", "").strip()
BOT_NAME = os.getenv("BOT_NAME", "Yashi Music").strip()

if not all([BOT_TOKEN, API_ID_RAW, API_HASH, SESSION_STRING, OWNER_ID_RAW]):
    missing = [
        name for name, value in {
            "BOT_TOKEN": BOT_TOKEN,
            "API_ID": API_ID_RAW,
            "API_HASH": API_HASH,
            "SESSION_STRING": SESSION_STRING,
            "OWNER_ID": OWNER_ID_RAW,
        }.items() if not value
    ]
    raise RuntimeError("Missing required environment variables: " + ", ".join(missing))

API_ID = int(API_ID_RAW)
OWNER_ID = int(OWNER_ID_RAW)

bot = Client(
    "yashi_music_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
)
user = Client(
    "yashi_music_user",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
    in_memory=True,
)
calls = PyTgCalls(user)

@dataclass
class Track:
    title: str
    webpage_url: str
    duration: str
    requested_by: str
    requester_id: int

@dataclass
class ChatState:
    queue: deque = field(default_factory=deque)
    current: Optional[Track] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

chats: dict[int, ChatState] = {}
started_at = time.time()

def get_state(chat_id: int) -> ChatState:
    return chats.setdefault(chat_id, ChatState())

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

def duration_text(seconds) -> str:
    try:
        seconds = int(seconds or 0)
    except (ValueError, TypeError):
        return "Live/unknown"
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else "Unknown"

def search_youtube(query: str) -> Optional[Track]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "default_search": "ytsearch1",
        "noplaylist": True,
        "socket_timeout": 15,
    }
    with YoutubeDL(opts) as ydl:
        data = ydl.extract_info(query if query.startswith(("http://", "https://")) else f"ytsearch1:{query}", download=False)
    if data and data.get("entries"):
        data = next((x for x in data["entries"] if x), None)
    if not data:
        return None
    url = data.get("webpage_url") or data.get("url")
    if url and not url.startswith("http"):
        url = "https://www.youtube.com/watch?v=" + url
    if not url:
        return None
    return Track(
        title=str(data.get("title") or "Unknown title")[:180],
        webpage_url=url,
        duration=duration_text(data.get("duration")),
        requested_by="",
        requester_id=0,
    )

def stream_url(url: str) -> str:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "noplaylist": True,
        "socket_timeout": 20,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    direct = info.get("url")
    if not direct:
        raise RuntimeError("YouTube did not return a playable audio URL.")
    return direct

async def play_track(chat_id: int, track: Track):
    state = get_state(chat_id)
    direct_url = await asyncio.to_thread(stream_url, track.webpage_url)
    await calls.play(chat_id, MediaStream(direct_url))
    state.current = track

async def start_next(chat_id: int):
    state = get_state(chat_id)
    async with state.lock:
        if not state.queue:
            state.current = None
            return False
        track = state.queue.popleft()
        try:
            await play_track(chat_id, track)
            return True
        except Exception:
            log.exception("Failed to start queued track in %s", chat_id)
            state.current = None
            return await start_next_unlocked(chat_id, state)

async def start_next_unlocked(chat_id: int, state: ChatState):
    if not state.queue:
        state.current = None
        return False
    track = state.queue.popleft()
    try:
        await play_track(chat_id, track)
        return True
    except Exception:
        log.exception("Failed to start queued track in %s", chat_id)
        state.current = None
        return await start_next_unlocked(chat_id, state)

async def send_track(chat_id: int, track: Track, position: Optional[int] = None):
    label = f"**Now playing:**" if position is None else f"**Added to queue (#{position}):**"
    await bot.send_message(
        chat_id,
        f"{label} [{track.title}]({track.webpage_url})\n"
        f"Duration: `{track.duration}`\n"
        f"Requested by: {track.requested_by}",
        disable_web_page_preview=True,
    )

@bot.on_message(filters.command(["start", "help"]))
async def start_handler(_, message):
    text = (
        f"🎵 **{BOT_NAME}**\n\n"
        "YouTube music for Telegram voice chats.\n\n"
        "**Commands**\n"
        "`/play <song name or YouTube URL>` — play/search\n"
        "`/pause` — pause playback\n"
        "`/resume` — resume playback\n"
        "`/skip` — skip current track\n"
        "`/stop` — stop and clear queue\n"
        "`/queue` — show upcoming tracks\n"
        "`/admin` — admin commands\n"
        "`/ping` — check bot status\n\n"
        "Use commands in the group where its voice chat is active. "
        "The linked user account must be in the group and have permission to speak."
    )
    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Help", callback_data="help"),
             InlineKeyboardButton("Ping", callback_data="ping")]
        ]),
        disable_web_page_preview=True,
    )

@bot.on_callback_query(filters.regex("^help$"))
async def help_callback(_, query):
    await query.answer()
    await query.message.reply_text("Use `/play song name`, `/pause`, `/resume`, `/skip`, `/stop`, `/queue`.")

@bot.on_callback_query(filters.regex("^ping$"))
async def ping_callback(_, query):
    await query.answer("Yashi Music is online.", show_alert=True)

@bot.on_message(filters.command("ping"))
async def ping_handler(_, message):
    await message.reply_text(f"🏓 Pong! `{int(time.time() - started_at)}s` since startup.")

@bot.on_message(filters.command("play") & filters.group)
async def play_handler(_, message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: `/play song name`")
    query = " ".join(message.command[1:])
    status = await message.reply_text("🔎 Searching YouTube…")
    try:
        track = await asyncio.to_thread(search_youtube, query)
        if not track:
            return await status.edit_text("No YouTube result found. Try a different title or URL.")
        requester = message.from_user
        track.requested_by = requester.mention if requester else "Unknown"
        track.requester_id = requester.id if requester else 0
        chat_id = message.chat.id
        state = get_state(chat_id)
        async with state.lock:
            if state.current is None:
                try:
                    await play_track(chat_id, track)
                    await status.edit_text(
                        f"🎶 **Now playing:** [{track.title}]({track.webpage_url})\n"
                        f"Duration: `{track.duration}`",
                        disable_web_page_preview=True,
                    )
                except Exception as e:
                    log.exception("Playback failed")
                    await status.edit_text(
                        "Could not start playback. Confirm the user account is in this group, "
                        "a voice chat is active, and the account can speak.\n"
                        f"Error: `{type(e).__name__}: {str(e)[:180]}`"
                    )
            else:
                state.queue.append(track)
                await status.edit_text(
                    f"➕ Added to queue (#{len(state.queue)}): [{track.title}]({track.webpage_url})",
                    disable_web_page_preview=True,
                )
    except Exception as e:
        log.exception("Search failed")
        await status.edit_text(f"Search failed: `{type(e).__name__}: {str(e)[:180]}`")

@bot.on_message(filters.command("pause") & filters.group)
async def pause_handler(_, message):
    try:
        await calls.pause_stream(message.chat.id)
        await message.reply_text("⏸️ Paused.")
    except Exception as e:
        await message.reply_text(f"Couldn't pause: `{type(e).__name__}`")

@bot.on_message(filters.command("resume") & filters.group)
async def resume_handler(_, message):
    try:
        await calls.resume_stream(message.chat.id)
        await message.reply_text("▶️ Resumed.")
    except Exception as e:
        await message.reply_text(f"Couldn't resume: `{type(e).__name__}`")

@bot.on_message(filters.command("skip") & filters.group)
async def skip_handler(_, message):
    chat_id = message.chat.id
    try:
        await calls.leave_call(chat_id)
    except Exception:
        pass
    state = get_state(chat_id)
    state.current = None
    if await start_next(chat_id):
        state = get_state(chat_id)
        await send_track(chat_id, state.current)
    else:
        await message.reply_text("Queue is empty. Playback stopped.")

@bot.on_message(filters.command("stop") & filters.group)
async def stop_handler(_, message):
    chat_id = message.chat.id
    try:
        await calls.leave_call(chat_id)
    except Exception:
        pass
    state = get_state(chat_id)
    state.current = None
    state.queue.clear()
    await message.reply_text("⏹️ Playback stopped and queue cleared.")

@bot.on_message(filters.command("queue") & filters.group)
async def queue_handler(_, message):
    state = get_state(message.chat.id)
    lines = []
    if state.current:
        lines.append(f"**Now:** {state.current.title}")
    if state.queue:
        lines.extend(f"{i}. {track.title}" for i, track in enumerate(list(state.queue)[:15], 1))
    if not lines:
        return await message.reply_text("Queue is empty.")
    await message.reply_text("📃 **Music Queue**\n\n" + "\n".join(lines))

@bot.on_message(filters.command("admin"))
async def admin_handler(_, message):
    if not message.from_user or not is_owner(message.from_user.id):
        return await message.reply_text("Owner only.")
    await message.reply_text(
        "**Yashi Music Admin**\n"
        "`/stats` — runtime and active queues\n"
        "`/broadcast <text>` — broadcast to chats the bot has seen (session-memory only)\n"
        "`/auth <user_id>` — not implemented in this starter; admin allow-list is owner-only\n"
        "`/maintenance` — not implemented in this starter"
    )

@bot.on_message(filters.command("stats"))
async def stats_handler(_, message):
    if not message.from_user or not is_owner(message.from_user.id):
        return await message.reply_text("Owner only.")
    active = sum(1 for s in chats.values() if s.current)
    queued = sum(len(s.queue) for s in chats.values())
    await message.reply_text(
        f"**Yashi Music Stats**\nUptime: `{int(time.time() - started_at)}s`\n"
        f"Tracked chats: `{len(chats)}`\nPlaying: `{active}`\nQueued tracks: `{queued}`"
    )

@bot.on_message(filters.command("broadcast"))
async def broadcast_handler(_, message):
    if not message.from_user or not is_owner(message.from_user.id):
        return await message.reply_text("Owner only.")
    if len(message.command) < 2:
        return await message.reply_text("Usage: `/broadcast your message`")
    text_to_send = message.text.split(maxsplit=1)[1]
    sent = failed = 0
    # This intentionally broadcasts only to groups currently tracked in memory.
    for chat_id in list(chats):
        try:
            await bot.send_message(chat_id, text_to_send)
            sent += 1
        except Exception:
            failed += 1
    await message.reply_text(f"Broadcast complete. Sent: `{sent}`, failed: `{failed}`.")

@bot.on_message(filters.command("maintenance"))
async def maintenance_handler(_, message):
    if not message.from_user or not is_owner(message.from_user.id):
        return await message.reply_text("Owner only.")
    await message.reply_text("Maintenance toggle is not enabled in this starter build.")

async def main():
    await bot.start()
    await user.start()
    await calls.start()
    me = await bot.get_me()
    user_me = await user.get_me()
    log.info("Bot started as @%s; streaming account id=%s", me.username, user_me.id)
    print(f"{BOT_NAME} is running. Bot: @{me.username}; streaming account id: {user_me.id}")
    await idle()
    await calls.stop()
    await user.stop()
    await bot.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
