import asyncio
import os
import subprocess
from dotenv import load_dotenv
from hydrogram import Client
from hydrogram.raw.functions.phone import CreateGroupCall, DiscardGroupCall, ToggleGroupCallSettings
from hydrogram.raw.functions.channels import GetFullChannel
from hydrogram.raw.types import InputGroupCall
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, GroupCallConfig, VideoQuality

load_dotenv()

API_ID     = int(os.getenv("API_ID"))
API_HASH   = os.getenv("API_HASH")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
HLS_URL    = os.getenv("HLS_URL")
PHONE      = os.getenv("PHONE")

# Use 240p chunklist directly
STREAM_URL = HLS_URL.replace("index.m3u8", "chunklist_b341000.m3u8") if "index.m3u8" in HLS_URL else HLS_URL

AUDIO_PIPE = "/tmp/tg_audio.pipe"
VIDEO_PIPE = "/tmp/tg_video.pipe"

ffmpeg_proc: subprocess.Popen = None


def create_pipes():
    for pipe in (AUDIO_PIPE, VIDEO_PIPE):
        if not os.path.exists(pipe):
            os.mkfifo(pipe)


def start_ffmpeg():
    global ffmpeg_proc
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-rtbufsize", "30M",
        "-i", STREAM_URL,
        # audio → raw PCM
        "-map", "0:a",
        "-f", "s16le", "-ac", "2", "-ar", "48000",
        AUDIO_PIPE,
        # video → raw YUV420p
        "-map", "0:v",
        "-f", "rawvideo", "-pix_fmt", "yuv420p",
        "-vf", "scale=640:360", "-r", "30",
        VIDEO_PIPE,
    ]
    print("[ffmpeg] Starting single A/V process...")
    ffmpeg_proc = subprocess.Popen(cmd)
    return ffmpeg_proc


async def ensure_voice_chat(user, peer):
    """Ensure a regular (non-RTMP) voice chat exists in the channel."""
    from random import randint
    chat = await user.invoke(GetFullChannel(channel=peer))
    existing_call = chat.full_chat.call

    if existing_call:
        print("[call] Discarding existing call to create fresh voice chat...")
        await user.invoke(DiscardGroupCall(
            call=InputGroupCall(id=existing_call.id, access_hash=existing_call.access_hash)
        ))
        await asyncio.sleep(2)

    print("[call] Creating voice chat...")
    await user.invoke(CreateGroupCall(
        peer=peer,
        random_id=randint(1, 2**31 - 1),
        title="Radio",
    ))
    chat = await user.invoke(GetFullChannel(channel=peer))
    try:
        await user.invoke(ToggleGroupCallSettings(
            call=chat.full_chat.call,
            reset_invite_hash=False,
            join_muted=True,
        ))
    except Exception:
        pass
    print("[call] Voice chat created, all participants muted.")


async def stream_loop(user, tgcalls):
    global ffmpeg_proc
    peer = await user.resolve_peer(CHANNEL_ID)
    create_pipes()

    while True:
        try:
            await ensure_voice_chat(user, peer)

            # Start single ffmpeg process for synced A/V
            ffmpeg_proc = start_ffmpeg()

            print("[stream] Joining voice chat as channel...")
            await tgcalls.play(
                CHANNEL_ID,
                MediaStream(
                    VIDEO_PIPE,
                    audio_path=AUDIO_PIPE,
                    audio_parameters=AudioQuality.HIGH,
                    video_parameters=VideoQuality.SD_360p,
                ),
                config=GroupCallConfig(join_as=peer),
            )
            print("[stream] Streaming. Waiting for stream to end...")

            while ffmpeg_proc.poll() is None and CHANNEL_ID in [c for c in await tgcalls.calls]:
                await asyncio.sleep(10)

            print("[stream] Stream ended. Restarting in 5s...")

        except Exception as e:
            print(f"[stream] Error: {e}. Retrying in 10s...")
            try:
                await tgcalls.leave_call(CHANNEL_ID)
            except Exception:
                pass
        finally:
            if ffmpeg_proc and ffmpeg_proc.poll() is None:
                ffmpeg_proc.terminate()

        await asyncio.sleep(5)


async def main():
    print("[bot] Starting user session...")
    user = Client("user", api_id=API_ID, api_hash=API_HASH, phone_number=PHONE)
    tgcalls = PyTgCalls(user)

    await user.start()
    await tgcalls.start()
    print("[bot] Logged in.")

    chat = await user.get_chat(CHANNEL_ID)
    print(f"[bot] Channel: {chat.title} ({CHANNEL_ID})")
    print("[bot] Starting 24/7 A/V stream...")

    try:
        await stream_loop(user, tgcalls)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[bot] Stopping...")
    finally:
        if ffmpeg_proc and ffmpeg_proc.poll() is None:
            ffmpeg_proc.terminate()
        try:
            await tgcalls.leave_call(CHANNEL_ID)
        except Exception:
            pass
        await user.stop()


if __name__ == "__main__":
    asyncio.run(main())
