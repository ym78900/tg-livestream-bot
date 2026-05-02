# Iran International Telegram Live Stream — Setup Guide

## What this does

Streams Iran International TV (24/7) into a Telegram channel as a **WebRTC voice chat**
using a Telegram user account (not a bot). Viewers join the voice chat inside the channel
and receive live audio + video with ~1-2 second latency.

The stream runs as a systemd service on a Linux server and auto-restarts on crash or reboot.

---

## Architecture

```
Iran International HLS source (240p, 369kbps)
    ↓
pytgcalls v2.2.12 + ntgcalls v2.2.1b3
    spawns two internal ffmpeg processes (audio + video)
    VP8-encodes and streams via WebRTC
    ↓
Telegram voice chat (group call) in the channel
    ↓
Viewers — Telegram handles all distribution (CDN/SFU)
    adaptive bitrate per viewer, ~1-2s latency
```

### Key design decisions

| Decision | Reason |
|---|---|
| WebRTC group call (not RTMP livestream) | Adaptive bitrate for weak connections, low latency, smooth playback |
| Streams as channel identity | Viewers see the channel as the broadcaster, not a personal account |
| All viewers muted (`join_muted=True`) | Prevents anyone from accidentally broadcasting |
| Bot unmutes itself after joining | `join_muted` applies to everyone including the broadcaster |
| 240p source (`chunklist_b341000.m3u8`) | ntgcalls VP8-encodes anyway — higher source res doesn't improve output quality |
| 15fps | Reduces VP8 output bitrate ~40% with minimal visual impact on news content |
| A/V sync fix (`-itsoffset 0.04`) | Source HLS has 32ms video-ahead offset baked in; 40ms corrects it perceptually |
| 3-failure monitor threshold | `GetFullChannel` is rate-limited when viewers join/leave — avoids false restarts |

---

## Stack

- **Python 3.12** (Ubuntu 24.04)
- **hydrogram** — Telegram MTProto client (user account, not bot API)
- **tgcrypto** — fast crypto for hydrogram
- **py-tgcalls 2.2.12** — voice chat joining and streaming
- **ntgcalls 2.2.1b3** — WebRTC engine (spawned by pytgcalls internally)
- **ffmpeg** — spawned internally by ntgcalls to decode HLS
- **python-dotenv** — loads credentials from `.env`

---

## Server requirements

- **OS**: Ubuntu 22.04 or 24.04 (tested on 24.04)
- **CPU**: 1 vCPU minimum (ffmpeg at ~9% CPU in steady state)
- **RAM**: 512MB minimum (~234MB used in steady state)
- **Network**: any — server only sends one WebRTC stream to Telegram regardless of viewer count
- **ffmpeg**: must be installed system-wide (`apt install ffmpeg`)
- **Python**: 3.11 or 3.12

Current server: DigitalOcean `ubuntu-s-1vcpu-512mb-10gb-fra1` at `164.90.215.95`

---

## Credentials

All credentials live in `.env` in the project root (not in the repo).

```
API_ID=1419283
API_HASH=e4f16b868c315c46c6536722f433dfd1
CHANNEL_ID=-1003948701374
HLS_URL=https://live.livetvstream.co.uk/LS-63503-4/index.m3u8
PHONE=+88801365929
```

| Variable | Description |
|---|---|
| `API_ID` / `API_HASH` | Telegram app credentials from my.telegram.org |
| `CHANNEL_ID` | Target channel (negative integer, supergroup/channel format) |
| `HLS_URL` | Iran International HLS master playlist — code auto-selects 240p chunklist |
| `PHONE` | Phone number of the Telegram user account used as broadcaster |

### HLS source details

The master playlist at `HLS_URL` offers three quality levels:

| Quality | Resolution | Bitrate | Chunklist |
|---|---|---|---|
| 720p | 1280×720 | 1306 kbps | `chunklist_b1196000.m3u8` |
| 360p | 640×360 | 881 kbps | `chunklist_b806000.m3u8` |
| **240p (used)** | **426×240** | **369.5 kbps** | **`chunklist_b341000.m3u8`** |

- Video: H.264 Constrained Baseline, 25fps source (downsampled to 15fps), YUV 4:2:0
- Audio: AAC-LC, 48kHz, stereo

---

## Files

| File | Location | In repo? |
|---|---|---|
| `main.py` | project root | ✅ yes |
| `requirements.txt` | project root | ✅ yes |
| `SETUP.md` | project root | ✅ yes |
| `.env` | project root | ❌ no — create manually |
| `user.session` | project root | ❌ no — copy from original machine or re-auth |

---

## Fresh deployment — step by step

### 1. Provision server

Ubuntu 24.04 LTS. After SSH in as root:

```bash
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv ffmpeg git
```

Verify ffmpeg:
```bash
ffmpeg -version  # must be 4.x or higher
```

### 2. Clone the repo

```bash
cd /root
git clone https://github.com/ym78900/tg-livestream-bot.git
cd tg-livestream-bot
```

### 3. Create virtual environment and install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

This installs pytgcalls 2.2.12 + ntgcalls 2.2.1b3 + hydrogram + tgcrypto + python-dotenv.

Verify ntgcalls installed correctly:
```bash
python3 -c "import ntgcalls; print('ntgcalls OK')"
```

### 4. Create .env file

```bash
cat > .env << 'EOF'
API_ID=1419283
API_HASH=e4f16b868c315c46c6536722f433dfd1
CHANNEL_ID=-1003948701374
HLS_URL=https://live.livetvstream.co.uk/LS-63503-4/index.m3u8
PHONE=+88801365929
EOF
```

### 5. Copy or create user.session

The `user.session` file is a saved Telegram login for the broadcaster account.
It must be present before starting the service.

**Option A — copy from existing machine (preferred):**
```bash
# Run this on the machine that already has the session:
scp /root/tg-livestream-bot/user.session root@NEW_SERVER_IP:/root/tg-livestream-bot/user.session
```

**Option B — authenticate fresh (if session file is lost):**
```bash
source venv/bin/activate
python3 -c "
from hydrogram import Client
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
async def auth():
    client = Client('user', api_id=int(os.getenv('API_ID')), api_hash=os.getenv('API_HASH'), phone_number=os.getenv('PHONE'))
    await client.start()
    print('Authenticated. user.session created.')
    await client.stop()
asyncio.run(auth())
"
```
This will prompt for the SMS/Telegram code sent to `PHONE`. Enter it.
A `user.session` file will be created in the project root.

### 6. Install systemd service

```bash
cat > /etc/systemd/system/tg-stream.service << 'EOF'
[Unit]
Description=Telegram Live Stream Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/tg-livestream-bot
ExecStart=/root/tg-livestream-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

```bash
systemctl daemon-reload
systemctl enable tg-stream
systemctl start tg-stream
```

### 7. Verify it's working

```bash
# Check service status
systemctl status tg-stream

# Watch live logs
journalctl -u tg-stream -f
```

Expected healthy log output:
```
[bot] Starting user session...
[bot] Logged in.
[bot] Channel: Iran international live (-1003948701374)
[bot] Starting 24/7 A/V stream...
[call] Discarding existing call to create fresh voice chat...
[call] Creating voice chat...
[call] Voice chat created, all participants muted.
[stream] Joining voice chat as channel...
[stream] Unmuted channel stream.
[stream] Streaming. Monitoring...
```

---

## Management

### View logs
```bash
journalctl -u tg-stream -f           # live tail
journalctl -u tg-stream -n 50        # last 50 lines
```

### Restart / stop / start
```bash
systemctl restart tg-stream
systemctl stop tg-stream
systemctl start tg-stream
```

### Deploy a code change
```bash
# On local machine:
scp main.py root@SERVER_IP:/root/tg-livestream-bot/main.py
ssh root@SERVER_IP "systemctl restart tg-stream"
```

---

## Rollback

Last known-good commit: **`ab8b3d9`**

```bash
# On local machine:
git checkout ab8b3d9 -- main.py
scp main.py root@SERVER_IP:/root/tg-livestream-bot/main.py
ssh root@SERVER_IP "systemctl restart tg-stream"
```

---

## How the code works (main.py walkthrough)

### `ensure_voice_chat(user, peer)`
1. Calls `GetFullChannel` to check if a voice chat already exists
2. If one exists, discards it (`DiscardGroupCall`) — ensures a clean slate
3. Creates a new WebRTC voice chat (`CreateGroupCall`) with title `IranIntlLive`
4. Attempts `ToggleGroupCallSettings` with `join_muted=True` (mutes all new joiners)
   - Note: `hidden_listeners=True` is passed but silently ignored by Telegram's API
     for WebRTC group calls — only works for RTMP livestream mode which was tested
     and abandoned due to no adaptive bitrate for regular channels
5. Returns — call is ready for streaming

### `stream_loop(user, tgcalls)`
1. Resolves the channel peer
2. Calls `ensure_voice_chat()` to create/recreate the call
3. Calls `tgcalls.play()` with:
   - Source: 240p HLS chunklist
   - Audio: HIGH quality (48kHz stereo)
   - Video: 426×240 @ 15fps
   - ffmpeg parameter: `-itsoffset 0.04` on video to compensate 40ms source A/V offset
   - `join_as=peer` — streams as the channel identity, not personal account
4. After joining, calls `EditGroupCallParticipant(muted=False)` to unmute the channel
   (because `join_muted=True` also mutes the broadcaster itself)
5. Monitor loop every 30 seconds:
   - Checks `tgcalls.calls` — is pytgcalls still in the call?
   - Calls `GetFullChannel` — does Telegram still have an active call?
   - Rate limit errors count toward a 3-failure threshold before restarting
     (prevents false restarts when viewers join/leave causing Telegram rate limits)
6. On any failure or call drop: leaves call, sleeps 5s, loops back to step 2

### `main()`
1. Creates `hydrogram.Client` (MTProto user session)
2. Creates `PyTgCalls` (WebRTC engine)
3. Starts both
4. Runs `stream_loop()` forever
5. On exit: gracefully leaves call and stops client

---

## Known limitations & investigated dead ends

### `hidden_listeners` — not settable for WebRTC calls
The `GroupCall` object has a `listeners_hidden` flag (bit 13) but Telegram's
`toggleGroupCallSettings` API does not expose a parameter to set it.
It is only automatically set to `True` when the call is created with `rtmp_stream=True`.

### RTMP livestream mode — tested and abandoned
Switching to `rtmp_stream=True` + ffmpeg RTMP push gives `listeners_hidden=True`
but loses adaptive bitrate. Telegram does NOT transcode RTMP streams into multiple
quality tiers for regular channels — only for verified/official broadcast accounts.
Result: viewers with weak connections experience buffering every few seconds.
WebRTC group call kept because Telegram's SFU handles per-viewer adaptive bitrate automatically.

### pytgcalls ffmpeg parameters format
`MediaStream(ffmpeg_parameters=...)` uses a custom parsing format:
- `--audio` / `--video` — target which stream the parameters apply to
- `---start` / `---mid` / `---end` — where in the ffmpeg command to insert them
- Example: `"--video ---start -itsoffset 0.04"` inserts `-itsoffset 0.04` before `-i` in the video ffmpeg process only

---

## GitHub repository

`https://github.com/ym78900/tg-livestream-bot`
