# Yashi Music Bot

Starter project for a Telegram music bot with YouTube search, basic voice-chat controls, and owner-only admin commands.

## Important limitations

- This is a starter implementation and must be tested against a real Telegram group voice chat before treating it as production-ready.
- Render free Web Services sleep after 15 minutes without inbound HTTP/WebSocket traffic and have ephemeral storage. They are not a reliable 24/7 voice-chat host.
- The `/broadcast` starter only targets group IDs currently tracked in memory. It is not a persistent broadcast database.
- `/auth` and `/maintenance` are informational placeholders in this starter; they are not implemented as full controls yet.
- YouTube playback availability may vary by region, source, or YouTube changes. Use content you have permission to stream.

## Required environment variables

- `BOT_TOKEN`: token from @BotFather
- `API_ID`, `API_HASH`: from https://my.telegram.org
- `SESSION_STRING`: Pyrogram session string for the separate user account
- `OWNER_ID`: your numeric Telegram user ID
- `BOT_NAME`: optional, defaults to Yashi Music

Never commit real tokens or session strings to GitHub. Generate a separate Telegram user session only for this bot and protect it like a password.

## Render

Build command: `pip install -r requirements.txt`
Start command: `python main.py`

This service is a long-running process, while Render Free is designed around web services and can sleep when inactive. The project has not been deployed or runtime-tested from this generated archive.
