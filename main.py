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
    """Launch ffmpeg reading directly from HLS URL → Telegram RTMP."""
    global ffmpeg_proc
    dest = f"{rtmp_url}{stream_key}"

    # Use the 720p chunklist directly to avoid master-playlist codec probe warnings
    hls_url = YT_URL.replace("index.m3u8", "chunklist_b1196000.m3u8") if "index.m3u8" in YT_URL else YT_URL

    ffmpeg_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-analyzeduration", "3000000",
        "-probesize", "5000000",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-i", hls_url,
        "-c", "copy",
        "-f", "flv", dest,
    ]

    print("[ffmpeg] Starting push to Telegram RTMP...")
    ffmpeg_proc = subprocess.Popen(ffmpeg_cmd)
    return ffmpeg_proc


async def stream_loop(user, peer):
    global ffmpeg_proc
    while True:
        try:
            rtmp_url, stream_key = await get_or_create_rtmp(user, peer)
            ffmpeg_proc = start_ffmpeg(rtmp_url, stream_key)
            print("[stream] Stream is live. Watching ffmpeg process...")
            while ffmpeg_proc.poll() is None:
                await asyncio.sleep(5)
            print(f"[stream] ffmpeg exited (code {ffmpeg_proc.returncode}). Restarting in 5s...")
        except Exception as e:
            print(f"[stream] Error: {e}. Retrying in 10s...")
            await asyncio.sleep(10)
            continue
        finally:
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
