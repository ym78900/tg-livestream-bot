# Telegram RTMP Live Stream Bot — Setup Guide

## What this does
Streams a YouTube live stream into a Telegram channel's live stream feature (RTMP),
using a throwaway Telegram user account. Viewers see a proper live stream UI in the channel.

## Stack
- Python 3.10+
- hydrogram (Telegram MTProto client)
- ffmpeg (stream encoding + RTMP push)
- yt-dlp (YouTube URL extraction)

## Current stream settings
- Source: YouTube live (configured in .env)
- Video: black frame @ 10kbps (Telegram RTMP requires a video track)
- Audio: 64kbps stereo AAC
- Total bitrate: ~74kbps
- Mode: Telegram RTMP live stream (proper broadcast UI)

## Files needed
- `main.py` — the bot (in this repo)
- `requirements.txt` — dependencies (in this repo)
- `.env` — credentials (NOT in repo, create from .env.example)
- `user.session` — saved Telegram login (NOT in repo, copy from original machine)

## Step-by-step setup on a new machine

### 1. Install system dependencies
```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y python3 python3-pip python3-venv ffmpeg

# macOS
brew install python ffmpeg
```

### 2. Clone the repo
```bash
git clone https://github.com/ym78900/tg-livestream-bot.git
cd tg-livestream-bot
```

### 3. Create virtual environment and install dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Create .env file
```bash
cp .env.example .env
```
Fill in `.env` with:
```
API_ID=1419283
API_HASH=e4f16b868c315c46c6536722f433dfd1
CHANNEL_ID=-1003948701374
HLS_URL=https://www.youtube.com/watch?v=5JDxjsAVaGk
PHONE=+88801365929
```

### 5. Copy user.session from original machine
The `user.session` file contains the saved Telegram login for the throwaway account.
Copy it to the project root:
```bash
# From original machine, run:
scp ~/tg-livestream-bot/user.session user@newserver:~/tg-livestream-bot/user.session
```
If you don't have it, the bot will ask for a login code on first run (SMS to +88801365929).

### 6. Run the bot
```bash
source venv/bin/activate
python main.py
```

### 7. Run persistently (keep alive after terminal closes)

#### Using screen (simplest):
```bash
screen -S stream
source venv/bin/activate
python main.py
# Detach: Ctrl+A then D
# Reattach: screen -r stream
```

#### Using systemd (recommended for Linux servers):
```bash
sudo nano /etc/systemd/system/tg-stream.service
```
Paste:
```ini
[Unit]
Description=Telegram Live Stream Bot
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/tg-livestream-bot
ExecStart=/home/YOUR_USERNAME/tg-livestream-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable tg-stream
sudo systemctl start tg-stream
sudo systemctl status tg-stream
```

## Notes for AI assistant
- The throwaway account phone is +88801365929
- The channel ID is -1003948701374
- The bot discards any existing voice chat and creates a fresh RTMP live stream on startup
- Stream key is refreshed on every restart (revoke=True)
- ffmpeg reconnects automatically if YouTube HLS drops
- If the stream shows as a "group chat" instead of live stream, the bot will auto-discard and recreate it as RTMP
- The pytgcalls/WebRTC approach was abandoned — RTMP is the correct method for proper live stream UI
