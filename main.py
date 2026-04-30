import asyncio
import os
import subprocess
from dotenv import load_dotenv
from hydrogram import Client
from hydrogram.raw.functions.phone import (
    CreateGroupCall,
    DiscardGroupCall,
    GetGroupCallStreamRtmpUrl,
)
from hydrogram.raw.functions.channels import GetFullChannel
from hydrogram.raw.types import Updates, UpdateGroupCall, GroupCall, InputGroupCall

load_dotenv()

API_ID   = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))   # e.g. -1003948701374
YT_URL   = os.getenv("HLS_URL")             # https://www.youtube.com/@IRANINTL/live
PHONE    = os.getenv("PHONE")

ffmpeg_proc: subprocess.Popen = None


async def get_or_create_rtmp(user, peer) -> tuple[str, str]:
    """Discard any existing non-RTMP call, ensure an RTMP live stream exists, return (url, key)."""
    from random import randint

    # Check what call currently exists
    chat = await user.invoke(GetFullChannel(channel=peer))
    existing_call = chat.full_chat.call

    if existing_call:
        # Check if it's already an RTMP stream
        try:
            result = await user.invoke(GetGroupCallStreamRtmpUrl(peer=peer, revoke=True))
            print("[rtmp] Got fresh key for existing RTMP stream")
            return result.url, result.key
        except Exception:
            # Not an RTMP stream — discard it
            print("[rtmp] Existing call is not RTMP — discarding...")
            await user.invoke(DiscardGroupCall(
                call=InputGroupCall(id=existing_call.id, access_hash=existing_call.access_hash)
            ))
            await asyncio.sleep(2)

    # Create a fresh RTMP live stream
    print("[rtmp] Creating RTMP live stream...")
    await user.invoke(CreateGroupCall(
        peer=peer,
        random_id=randint(1, 2**31 - 1),
        rtmp_stream=True,
        title="Live",
    ))
    result = await user.invoke(GetGroupCallStreamRtmpUrl(peer=peer, revoke=False))
    print("[rtmp] RTMP live stream created, got key")
    return result.url, result.key


def start_ffmpeg(rtmp_url: str, stream_key: str):
    """Launch yt-dlp piped into ffmpeg to push YouTube live to Telegram RTMP."""
    global ffmpeg_proc
    dest = f"{rtmp_url}{stream_key}"
    ytdlp = os.path.join(os.path.dirname(os.sys.executable), "yt-dlp")
    cookies = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")

    ytdlp_cmd = [
        ytdlp,
        "-f", "bestvideo[vcodec^=avc1]+bestaudio/best",
        "--no-warnings",
        "--cookies", cookies,
        "-o", "-",           # pipe raw stream to stdout
        "--no-part",
        YT_URL,
    ]

    ffmpeg_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-i", "pipe:0",      # read from stdin (yt-dlp pipe)
        "-copyts", "-start_at_zero",
        # Video: black frame (required by Telegram RTMP)
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-profile:v", "baseline",
        "-level", "3.1",
        "-b:v", "10k",
        "-maxrate", "10k",
        "-bufsize", "5k",
        "-r", "1",
        "-g", "1",
        "-s", "128x72",
        "-vf", "geq=0:128:128",
        # Audio
        "-c:a", "aac",
        "-b:a", "64k",
        "-ar", "44100",
        "-ac", "2",
        # Output: RTMP
        "-f", "flv",
        dest,
    ]

    print("[yt-dlp] Starting download pipe...")
    ytdlp_proc = subprocess.Popen(ytdlp_cmd, stdout=subprocess.PIPE)
    print("[ffmpeg] Starting push to Telegram RTMP...")
    ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=ytdlp_proc.stdout)
    ytdlp_proc.stdout.close()  # allow yt-dlp to receive SIGPIPE if ffmpeg exits
    return ytdlp_proc, ffmpeg_proc


async def stream_loop(user, peer):
    global ffmpeg_proc
    while True:
        ytdlp_proc = None
        try:
            rtmp_url, stream_key = await get_or_create_rtmp(user, peer)
            ytdlp_proc, ffmpeg_proc = start_ffmpeg(rtmp_url, stream_key)
            print("[stream] Stream is live. Watching ffmpeg process...")
            while ffmpeg_proc.poll() is None:
                await asyncio.sleep(5)
            print(f"[stream] ffmpeg exited (code {ffmpeg_proc.returncode}). Restarting in 5s...")
        except Exception as e:
            print(f"[stream] Error: {e}. Retrying in 10s...")
            await asyncio.sleep(10)
            continue
        finally:
            if ytdlp_proc and ytdlp_proc.poll() is None:
                ytdlp_proc.terminate()
            if ffmpeg_proc and ffmpeg_proc.poll() is None:
                ffmpeg_proc.terminate()
        await asyncio.sleep(5)


async def main():
    print("[bot] Starting user session...")
    user = Client("user", api_id=API_ID, api_hash=API_HASH, phone_number=PHONE)
    await user.start()
    print("[bot] Logged in.")

    # Get the full InputChannel (needs access_hash)
    chat = await user.get_chat(CHANNEL_ID)
    peer = await user.resolve_peer(CHANNEL_ID)

    print(f"[bot] Resolved channel: {chat.title} ({CHANNEL_ID})")
    print("[bot] Starting 24/7 RTMP live stream...")

    try:
        await stream_loop(user, peer)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[bot] Stopping...")
    finally:
        if ffmpeg_proc and ffmpeg_proc.poll() is None:
            ffmpeg_proc.terminate()
        await user.stop()


if __name__ == "__main__":
    asyncio.run(main())
