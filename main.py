import asyncio
import os
from dotenv import load_dotenv
from hydrogram import Client
from hydrogram.raw.functions.phone import CreateGroupCall, DiscardGroupCall, ToggleGroupCallSettings
from hydrogram.raw.functions.channels import GetFullChannel
from hydrogram.raw.types import InputGroupCall
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality

load_dotenv()

API_ID     = int(os.getenv("API_ID"))
API_HASH   = os.getenv("API_HASH")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
HLS_URL    = os.getenv("HLS_URL")
PHONE      = os.getenv("PHONE")

# Use 240p audio track directly
AUDIO_URL = HLS_URL.replace("index.m3u8", "chunklist_b341000.m3u8") if "index.m3u8" in HLS_URL else HLS_URL


async def ensure_voice_chat(user, peer):
    """Ensure a regular (non-RTMP) voice chat exists in the channel."""
    from random import randint
    chat = await user.invoke(GetFullChannel(channel=peer))
    existing_call = chat.full_chat.call

    if existing_call:
        # Discard it — could be a leftover RTMP stream
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
    # Lock the mic — no one can speak or request to speak
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
    peer = await user.resolve_peer(CHANNEL_ID)

    while True:
        try:
            await ensure_voice_chat(user, peer)

            print("[stream] Joining voice chat with audio stream...")
            await tgcalls.play(
                CHANNEL_ID,
                MediaStream(
                    AUDIO_URL,
                    audio_parameters=AudioQuality.HIGH,
                    video_flags=MediaStream.Flags.IGNORE,
                    ffmpeg_parameters="-re -rtbufsize 30M -max_delay 30000000",
                ),
            )
            print("[stream] Streaming. Waiting for stream to end...")

            # Wait until the stream ends or errors
            while CHANNEL_ID in [c for c in await tgcalls.calls]:
                await asyncio.sleep(10)

            print("[stream] Stream ended. Restarting in 5s...")

        except Exception as e:
            print(f"[stream] Error: {e}. Retrying in 10s...")
            try:
                await tgcalls.leave_call(CHANNEL_ID)
            except Exception:
                pass

        await asyncio.sleep(10)


async def main():
    print("[bot] Starting user session...")
    user = Client("user", api_id=API_ID, api_hash=API_HASH, phone_number=PHONE)
    tgcalls = PyTgCalls(user)

    await user.start()
    await tgcalls.start()
    print("[bot] Logged in.")

    chat = await user.get_chat(CHANNEL_ID)
    print(f"[bot] Channel: {chat.title} ({CHANNEL_ID})")
    print("[bot] Starting 24/7 audio stream...")

    try:
        await stream_loop(user, tgcalls)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[bot] Stopping...")
    finally:
        try:
            await tgcalls.leave_group_call(CHANNEL_ID)
        except Exception:
            pass
        await user.stop()


if __name__ == "__main__":
    asyncio.run(main())
