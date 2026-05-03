import asyncio
import os
import traceback
from dotenv import load_dotenv
from hydrogram import Client
from hydrogram.raw.functions.phone import CreateGroupCall, DiscardGroupCall, ToggleGroupCallSettings, EditGroupCallParticipant
from hydrogram.raw.functions.channels import GetFullChannel
from hydrogram.raw.types import InputGroupCall
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, GroupCallConfig, VideoQuality
from pytgcalls.types.raw import VideoParameters

load_dotenv()

API_ID     = int(os.getenv("API_ID"))
API_HASH   = os.getenv("API_HASH")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
HLS_URL    = os.getenv("HLS_URL")
PHONE      = os.getenv("PHONE")

# Use 240p chunklist directly
STREAM_URL = HLS_URL.replace("index.m3u8", "chunklist_b341000.m3u8") if "index.m3u8" in HLS_URL else HLS_URL


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
        title="IranIntlLive",
    ))
    chat = await user.invoke(GetFullChannel(channel=peer))
    try:
        await user.invoke(ToggleGroupCallSettings(
            call=chat.full_chat.call,
            reset_invite_hash=False,
            join_muted=True,
            hidden_listeners=True,
        ))
    except Exception:
        pass
    print("[call] Voice chat created, all participants muted.")


NOTIFY_USER_ID = int(os.getenv("NOTIFY_USER_ID", "73875473"))


async def notify(user, text):
    """Send an alert to the owner's private Telegram."""
    try:
        await user.send_message(NOTIFY_USER_ID, text)
    except Exception as e:
        print(f"[notify] Failed to send alert: {e}")



async def reconnect(user, tgcalls):
    """Reconnect the hydrogram MTProto session and pytgcalls."""
    print("[bot] Reconnecting MTProto session...")
    try:
        await tgcalls.leave_call(CHANNEL_ID)
    except Exception:
        pass
    try:
        await user.stop()
    except Exception:
        pass
    await asyncio.sleep(5)
    await user.start()
    await tgcalls.start()
    print("[bot] Reconnected.")


async def stream_loop(user, tgcalls):
    peer = await user.resolve_peer(CHANNEL_ID)

    while True:
        try:
            await ensure_voice_chat(user, peer)

            print("[stream] Joining voice chat as channel...")
            await tgcalls.play(
                CHANNEL_ID,
                MediaStream(
                    STREAM_URL,
                    audio_parameters=AudioQuality.HIGH,
                    video_parameters=VideoParameters(426, 240, 15),
                    ffmpeg_parameters="--video ---start -itsoffset 0.04",
                ),
                config=GroupCallConfig(join_as=peer),
            )
            # Unmute the channel after joining — join_muted=True applies to all
            # participants including the broadcaster itself if it joins after the
            # setting is enabled.
            chat = await user.invoke(GetFullChannel(channel=peer))
            try:
                await user.invoke(EditGroupCallParticipant(
                    call=chat.full_chat.call,
                    participant=peer,
                    muted=False,
                ))
                print("[stream] Unmuted channel stream.")
            except Exception as e:
                print(f"[stream] Unmute warning: {e}")
            print("[stream] Streaming. Monitoring...")

            consecutive_failures = 0
            while CHANNEL_ID in [c for c in await tgcalls.calls]:
                await asyncio.sleep(30)
                try:
                    ch = await user.invoke(GetFullChannel(channel=peer))
                    consecutive_failures = 0
                    if ch.full_chat.call is None:
                        print("[stream] Telegram call dropped externally. Restarting...")
                        break
                except Exception as e:
                    consecutive_failures += 1
                    print(f"[stream] Monitor warning ({consecutive_failures}/3): {e}")
                    if consecutive_failures >= 3:
                        print("[stream] 3 consecutive monitor failures. Restarting...")
                        await notify(user, "⚠️ [tg-stream] 3 consecutive monitor failures — restarting stream")
                        break

            print("[stream] Stream ended. Restarting in 5s...")

        except AttributeError as e:
            # hydrogram connection dropped (protocol is None) — reconnect the session
            if "NoneType" in str(e) and "send" in str(e):
                print(f"[bot] MTProto connection lost — reconnecting...")
                await notify(user, "⚠️ [tg-stream] MTProto connection lost — reconnecting...")
                try:
                    await reconnect(user, tgcalls)
                    peer = await user.resolve_peer(CHANNEL_ID)
                    await notify(user, "✅ [tg-stream] Reconnected successfully")
                except Exception as re:
                    print(f"[bot] Reconnect failed: {re} — retrying in 15s...")
                    await notify(user, f"❌ [tg-stream] Reconnect failed: {re}")
                    await asyncio.sleep(15)
            else:
                print(f"[stream] Error: {e}")
                traceback.print_exc()
                await notify(user, f"❌ [tg-stream] Error: {e}")
                await asyncio.sleep(10)
            continue

        except Exception as e:
            print(f"[stream] Error: {e}")
            traceback.print_exc()
            print("[stream] Retrying in 10s...")
            await notify(user, f"❌ [tg-stream] Error: {e}")
            try:
                await tgcalls.leave_call(CHANNEL_ID)
            except Exception:
                pass

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
        try:
            await tgcalls.leave_call(CHANNEL_ID)
        except Exception:
            pass
        await user.stop()


if __name__ == "__main__":
    asyncio.run(main())
