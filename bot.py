"""Duplicate Detector Bot — channel mein duplicate files/messages pakadta hai.

Kaam:
- Channel mein add karo (admin, "Delete Messages" permission ke saath).
- Har nayi post (file ya text) ko read karta hai, naam + size ya text note karta hai.
- Jab ek hi naam + ek hi size ki file dobara aaye (ya ek hi text dobara aaye),
  to owner ko DM mein alert bhejta hai, delete ke options ke saath:
  Delete All / Keep First, Delete Rest / Delete Selected / Keep.
- Sirf nayi posts watch hoti hain (bot add hone ke baad ki) — purana history
  Bot API se read nahi hota.
"""
import os
import json
import time
import hashlib
import logging
from datetime import datetime

from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("dup_detector")

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "7966027018"))

DB_FILE = "files.json"
MAX_RECORDS = 5000
MIN_TEXT_LEN = 20  # isse chhota text duplicate nahi mana jata

db = {"records": [], "ignored": [], "alerts": {}}


def load_db():
    global db
    try:
        with open(DB_FILE) as f:
            data = json.load(f)
        db["records"] = data.get("records", [])
        db["ignored"] = data.get("ignored", [])
        db["alerts"] = data.get("alerts", {})
    except Exception:
        pass


def save_db():
    try:
        with open(DB_FILE, "w") as f:
            json.dump(db, f)
    except Exception as e:
        log.warning(f"db save fail: {e}")


load_db()


def human_size(n: int) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


def msg_link(chat_id: int, username, msg_id: int) -> str:
    if username:
        return f"https://t.me/{username}/{msg_id}"
    cid = str(chat_id)
    if cid.startswith("-100"):
        cid = cid[4:]
    elif cid.startswith("-"):
        cid = cid[1:]
    return f"https://t.me/c/{cid}/{msg_id}"


def media_of(message: Message):
    """Post mein file hai to (kind, name, size, unique_id) do, warna None."""
    m = message.document or message.video or message.audio or message.animation
    if m is not None:
        name = getattr(m, "file_name", None) or "unnamed"
        return ("media", name, int(getattr(m, "file_size", 0) or 0),
                getattr(m, "file_unique_id", ""))
    if message.photo is not None:
        # photo ka koi naam nahi hota — size + dimensions se pehchano
        ph = message.photo
        name = f"photo_{ph.width}x{ph.height}.jpg"
        return ("media", name, int(getattr(ph, "file_size", 0) or 0),
                getattr(ph, "file_unique_id", ""))
    if message.voice is not None:
        v = message.voice
        return ("media", "voice.ogg", int(getattr(v, "file_size", 0) or 0),
                getattr(v, "file_unique_id", ""))
    if message.video_note is not None:
        v = message.video_note
        return ("media", "video_note.mp4", int(getattr(v, "file_size", 0) or 0),
                getattr(v, "file_unique_id", ""))
    return None


def text_key(message: Message):
    """Sirf-text wali post ka duplicate key (None = text duplicate nahi)."""
    text = (message.text or message.caption or "").strip()
    if message.document or message.video or message.audio or message.animation \
            or message.photo or message.voice or message.video_note:
        return None  # file wali post ka text/caption duplicate key nahi
    if len(text) < MIN_TEXT_LEN or text.startswith("/"):
        return None
    h = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:16]
    return ("text", h, text)


def find_copies(chat_id: int, key: str):
    return [r for r in db["records"]
            if r["chat_id"] == chat_id and r["key"] == key]


def alert_keyboard(alert_id: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Delete All", callback_data=f"dup_del_all:{alert_id}")],
        [InlineKeyboardButton("🧹 Keep First, Delete Rest",
                              callback_data=f"dup_keep_first:{alert_id}")],
        [InlineKeyboardButton("🎯 Delete Selected",
                              callback_data=f"dup_pick:{alert_id}")],
        [InlineKeyboardButton("✅ Keep All (dobara alert mat karo)",
                              callback_data=f"dup_keep:{alert_id}")],
    ])


def alert_text(alert: dict) -> str:
    lines = [
        "⚠️ **Duplicate mila!**",
        "",
        f"📁 File: `{alert['name']}`",
    ]
    if alert["kind"] == "media":
        lines.append(f"📦 Size: {human_size(alert['size'])}")
    lines.append(f"📺 Channel: {alert['chat_title']}")
    lines.append(f"🔢 Copies: {len(alert['msg_ids'])}")
    lines.append("")
    for i, (mid, date) in enumerate(zip(alert["msg_ids"], alert["dates"]), 1):
        link = msg_link(alert["chat_id"], alert.get("username"), mid)
        lines.append(f"{i}️⃣ [{date}]({link})")
    lines.append("")
    lines.append("Kya karna hai?")
    return "\n".join(lines)


async def send_owner_alert(alert: dict):
    alert_id = alert["alert_id"]
    try:
        await bot.send_message(
            OWNER_ID, alert_text(alert),
            reply_markup=alert_keyboard(alert_id),
            disable_web_page_preview=True,
        )
        log.info(f"alert sent to owner: {alert_id} ({alert['name']})")
    except Exception as e:
        log.warning(f"owner ko alert nahi bhej paya (owner ne /start nahi kiya hoga?): {e}")


# ---------- Bot ----------

bot = Client("dup_detector", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    await message.reply_text(
        "👋 Main **Duplicate Detector Bot** hoon!\n\n"
        "Mujhe apne channel mein **admin** banao (\"Delete Messages\" "
        "permission ke saath), phir main har nayi file/message ko watch karunga.\n\n"
        "• Ek hi naam + ek hi size ki file dobara aaye to main yahin DM mein "
        "bata dunga, delete ke options ke saath.\n"
        "• Ek hi text dobara aaye to bhi alert aayega.\n\n"
        "Commands:\n"
        "/stats — kitni files track ho rahi hain\n"
        "/duplicates — haal ke duplicates\n"
        "/help — madad"
    )


@bot.on_message(filters.command("help") & filters.private)
async def help_handler(client: Client, message: Message):
    await message.reply_text(
        "❓ **Help**\n\n"
        "1. Mujhe channel mein admin banao (Delete Messages ON).\n"
        "2. Channel mein jo bhi nayi file/text aayegi, main use note kar lunga.\n"
        "3. Duplicate mile to is DM mein alert aayega — Delete All, "
        "Keep First, Delete Selected ya Keep chun lo.\n\n"
        "Note: main sirf add hone ke **baad** ki posts dekh sakta hoon, "
        "purana channel history Bot API se read nahi hota."
    )


@bot.on_message(filters.command("stats") & filters.private)
async def stats_handler(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply_text("❌ Sirf owner use kar sakta hai.")
        return
    channels = sorted({r["chat_title"] for r in db["records"]})
    dup_groups = len(db["alerts"])
    await message.reply_text(
        "📊 **Stats**\n\n"
        f"• Tracked files/messages: {len(db['records'])}\n"
        f"• Duplicate groups mile: {dup_groups}\n"
        f"• Channels: {len(channels)}\n" +
        ("\n".join(f"  – {c}" for c in channels) if channels else "  (koi nahi)")
    )


@bot.on_message(filters.command("duplicates") & filters.private)
async def duplicates_handler(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply_text("❌ Sirf owner use kar sakta hai.")
        return
    alerts = sorted(db["alerts"].values(), key=lambda a: a["time"], reverse=True)[:10]
    if not alerts:
        await message.reply_text("Abhi tak koi duplicate nahi mila.")
        return
    lines = ["🧾 **Haal ke duplicates:**\n"]
    for a in alerts:
        lines.append(f"• `{a['name']}` — {len(a['msg_ids'])} copies, "
                     f"{a['chat_title']} ({a['status']})")
    await message.reply_text("\n".join(lines))


@bot.on_chat_member_updated()
async def added_handler(client: Client, update):
    """Bot kisi channel mein add/admin bana to owner ko batao."""
    try:
        chat = update.chat
        new = update.new_chat_member
        if new is None or new.user is None:
            return
        me = await client.get_me()
        if new.user.id != me.id:
            return
        if new.status not in ("administrator", "member"):
            return
        if chat.type not in ("channel", "supergroup"):
            return
        try:
            await client.send_message(
                OWNER_ID,
                f"✅ Channel **{chat.title}** mein add ho gaya!\n"
                "Duplicate watch ON hai.\n"
                "Delete karne ke liye mujhe \"Delete Messages\" permission "
                "ke saath admin banao.",
            )
        except Exception as e:
            log.warning(f"added-notify fail: {e}")
    except Exception as e:
        log.warning(f"chat_member update fail: {e}")


@bot.on_message(filters.channel)
async def channel_post_handler(client: Client, message: Message):
    """Har channel post: file/text note karo, duplicate ho to owner ko alert karo."""
    try:
        chat = message.chat
        chat_id = chat.id
        title = chat.title or str(chat_id)
        date = message.date.strftime("%d %b %H:%M") if message.date else ""

        media = media_of(message)
        tk = text_key(message)
        if media is None and tk is None:
            return  # na file, na kaam ka text

        if media is not None:
            kind, name, size, unique_id = media
            key = f"media:{name}|{size}"
            display_name = name
            display_size = size
        else:
            kind, h, text = tk
            key = f"text:{h}"
            display_name = (text[:60] + "…") if len(text) > 60 else text
            display_size = 0
            unique_id = ""

        # exact same file dobara upload hua ho to unique_id se bhi pakdo
        copies = find_copies(chat_id, key)
        if media is not None and unique_id:
            for r in db["records"]:
                if (r["chat_id"] == chat_id and r.get("unique_id") == unique_id
                        and r["msg_id"] != message.id and r not in copies):
                    copies.append(r)

        # record save karo
        db["records"].append({
            "key": key, "kind": kind, "name": display_name, "size": display_size,
            "msg_id": message.id, "chat_id": chat_id, "chat_title": title,
            "date": date, "unique_id": unique_id,
        })
        if len(db["records"]) > MAX_RECORDS:
            db["records"] = db["records"][-MAX_RECORDS:]
        save_db()

        if not copies:
            return  # pehli baar — koi duplicate nahi
        if key in db["ignored"]:
            return  # owner ne Keep kiya hua hai

        all_copies = sorted(copies + [db["records"][-1]], key=lambda r: r["msg_id"])
        alert_id = f"{chat_id}_{message.id}_{int(time.time())}"
        alert = {
            "alert_id": alert_id, "kind": kind, "name": display_name,
            "size": display_size, "chat_id": chat_id, "chat_title": title,
            "username": getattr(chat, "username", None),
            "msg_ids": [r["msg_id"] for r in all_copies],
            "dates": [r["date"] for r in all_copies],
            "key": key, "time": int(time.time()), "status": "pending",
        }
        db["alerts"][alert_id] = alert
        save_db()
        await send_owner_alert(alert)
    except Exception as e:
        log.warning(f"channel post handle fail: {e}")


@bot.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    if query.from_user.id != OWNER_ID:
        await query.answer("❌ Sirf owner.", show_alert=True)
        return
    data = (query.data or "")
    parts = data.split(":")
    action = parts[0]
    try:
        if action == "dup_del_all":
            alert = db["alerts"].get(parts[1])
            if not alert:
                await query.answer("Alert nahi mila.", show_alert=True)
                return
            await delete_copies(alert, alert["msg_ids"])
            alert["status"] = "deleted_all"
            save_db()
            await query.message.edit_text(
                f"✅ **Deleted all {len(alert['msg_ids'])} copies**\n"
                f"📁 `{alert['name']}` — {alert['chat_title']}")
            await query.answer("Sab delete kar diye!")

        elif action == "dup_keep_first":
            alert = db["alerts"].get(parts[1])
            if not alert:
                await query.answer("Alert nahi mila.", show_alert=True)
                return
            keep = alert["msg_ids"][0]
            rest = alert["msg_ids"][1:]
            await delete_copies(alert, rest)
            alert["status"] = "kept_first"
            save_db()
            await query.message.edit_text(
                f"✅ **Pehli copy rakhi, baaki {len(rest)} delete kar diye**\n"
                f"📁 `{alert['name']}` — {alert['chat_title']}")
            await query.answer("Ho gaya!")

        elif action == "dup_pick":
            alert = db["alerts"].get(parts[1])
            if not alert:
                await query.answer("Alert nahi mila.", show_alert=True)
                return
            buttons = []
            for i, (mid, date) in enumerate(zip(alert["msg_ids"], alert["dates"])):
                buttons.append([InlineKeyboardButton(
                    f"🗑 Copy {i + 1} — {date}",
                    callback_data=f"dup_one:{alert['alert_id']}:{i}")])
            buttons.append([InlineKeyboardButton("⬅ Back",
                                                 callback_data=f"dup_back:{alert['alert_id']}")])
            await query.message.edit_text(
                alert_text(alert) + "\nKaunsi copy delete karni hai?",
                reply_markup=InlineKeyboardMarkup(buttons),
                disable_web_page_preview=True)
            await query.answer()

        elif action == "dup_one":
            alert = db["alerts"].get(parts[1])
            if not alert:
                await query.answer("Alert nahi mila.", show_alert=True)
                return
            idx = int(parts[2])
            mid = alert["msg_ids"][idx]
            await delete_copies(alert, [mid])
            del alert["msg_ids"][idx]
            del alert["dates"][idx]
            alert["status"] = "partial"
            save_db()
            if alert["msg_ids"]:
                buttons = []
                for i, (m, d) in enumerate(zip(alert["msg_ids"], alert["dates"])):
                    buttons.append([InlineKeyboardButton(
                        f"🗑 Copy {i + 1} — {d}",
                        callback_data=f"dup_one:{alert['alert_id']}:{i}")])
                buttons.append([InlineKeyboardButton(
                    "⬅ Back", callback_data=f"dup_back:{alert['alert_id']}")])
                await query.message.edit_text(
                    alert_text(alert) + "\nKaunsi copy delete karni hai?",
                    reply_markup=InlineKeyboardMarkup(buttons),
                    disable_web_page_preview=True)
            else:
                await query.message.edit_text(
                    f"✅ **Sab copies delete kar di**\n📁 `{alert['name']}`")
            await query.answer("Delete kar di!")

        elif action == "dup_back":
            alert = db["alerts"].get(parts[1])
            if not alert:
                await query.answer("Alert nahi mila.", show_alert=True)
                return
            await query.message.edit_text(
                alert_text(alert), reply_markup=alert_keyboard(alert["alert_id"]),
                disable_web_page_preview=True)
            await query.answer()

        elif action == "dup_keep":
            alert = db["alerts"].get(parts[1])
            if not alert:
                await query.answer("Alert nahi mila.", show_alert=True)
                return
            if alert["key"] not in db["ignored"]:
                db["ignored"].append(alert["key"])
            alert["status"] = "kept"
            save_db()
            await query.message.edit_text(
                f"✅ **Kept** — `{alert['name']}` ke liye dobara alert nahi aayega.")
            await query.answer("Rakh liya!")
    except Exception as e:
        log.warning(f"callback fail: {e}")
        try:
            await query.answer(f"Error: {e}", show_alert=True)
        except Exception:
            pass


async def delete_copies(alert: dict, msg_ids: list):
    """Channel se copies delete karo, aur unke records DB se hatao."""
    if not msg_ids:
        return
    try:
        await bot.delete_messages(alert["chat_id"], msg_ids)
        log.info(f"deleted {len(msg_ids)} msg(s) from {alert['chat_id']}")
    except Exception as e:
        log.warning(f"delete fail (admin/delete permission check karo): {e}")
        raise
    gone = set(msg_ids)
    db["records"] = [r for r in db["records"]
                     if not (r["chat_id"] == alert["chat_id"] and r["msg_id"] in gone)]
    save_db()


async def main():
    log.info("Duplicate Detector Bot start ho raha hai...")
    await bot.start()
    me = await bot.get_me()
    log.info(f"Bot online hai: @{me.username} (id {me.id})")
    log.info("Channel posts watch kar raha hoon. /start se DM mein test karo.")
    from pyrogram import idle
    await idle()
    await bot.stop()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
