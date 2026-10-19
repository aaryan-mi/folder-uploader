import asyncio
import os
import json
import time

# Workaround for Python 3.12+ asyncio event loop initialization with Pyrogram
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import config

app = Client(
    "folder_backup_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN
)

HISTORY_FILE = "backup_history.json"
SETTINGS_FILE = "user_settings.json"
ACTIVE_BACKUPS = {}   # {user_id: {"cancelled": bool}}
LAST_SCANNED = {}     # {user_id: folder_path}
NAV_STATE = {}        # {user_id: {"path": str, "subfolders": list, "page": int}}

def humanbytes(size):
    if not size:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            break
        size /= 1024.0
    return f"{size:.2f} {unit}"

# === History & Settings Helpers ===
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_history(history):
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception:
        pass

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass

def get_user_settings(user_id):
    settings = load_settings()
    uid = str(user_id)
    if uid not in settings:
        settings[uid] = {
            "target_chat": None,       # None = private chat, or channel ID/username
            "target_name": "Private Chat",
            "use_captions": True       # True/False
        }
    return settings[uid]

def update_user_settings(user_id, key, value):
    settings = load_settings()
    uid = str(user_id)
    if uid not in settings:
        settings[uid] = {
            "target_chat": None,
            "target_name": "Private Chat",
            "use_captions": True
        }
    settings[uid][key] = value
    save_settings(settings)
    return settings[uid]

def get_folder_files(folder_path):
    all_files = []
    for root, _, files in os.walk(folder_path):
        for f in files:
            full_path = os.path.join(root, f)
            try:
                size = os.path.getsize(full_path)
                mtime = os.path.getmtime(full_path)
                all_files.append((full_path, size, mtime))
            except Exception:
                pass
    return all_files

async def file_progress(current, total, client, status_msg, start_time, user_id, file_index, total_files, filename):
    if ACTIVE_BACKUPS.get(user_id, {}).get("cancelled"):
        client.stop_transmission()
        return

    now = time.time()
    diff = now - start_time
    if round(diff % 3.0) == 0 or current == total:
        pct = (current * 100) / total if total > 0 else 0
        speed = current / diff if diff > 0 else 0
        eta = round((total - current) / speed) if speed > 0 else 0

        filled = int(10 * current // total) if total > 0 else 0
        bar = '█' * filled + '░' * (10 - filled)

        text = (
            f"📦 **Batch Backup in Progress**\n"
            f"📄 **File [{file_index}/{total_files}]:** `{filename}`\n\n"
            f"[{bar}] {pct:.1f}%\n"
            f"⚡ **Speed:** {humanbytes(speed)}/s\n"
            f"📊 **Size:** {humanbytes(current)} / {humanbytes(total)}\n"
            f"⏱️ **ETA:** {eta}s"
        )
        try:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel Backup", callback_data=f"cancel_backup_{user_id}")]
            ])
            await status_msg.edit_text(text, reply_markup=markup)
        except Exception:
            pass

def get_browser_view(user_id: int, target_path: str = None, page: int = 0):
    if not target_path or not os.path.exists(target_path):
        # Auto-pick root: on Android /sdcard, on PC user home
        if os.path.exists("/sdcard"):
            target_path = "/sdcard"
        elif os.path.exists(os.path.expanduser("~")):
            target_path = os.path.expanduser("~")
        else:
            target_path = "."

    target_path = os.path.abspath(target_path)
    subfolders = []
    file_count = 0
    total_size = 0

    try:
        with os.scandir(target_path) as entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False) and not entry.name.startswith("."):
                        subfolders.append(entry.name)
                    elif entry.is_file(follow_symlinks=False) and not entry.name.startswith("."):
                        file_count += 1
                        total_size += entry.stat().st_size
                except Exception:
                    pass
    except Exception as e:
        return f"❌ Cannot access `{target_path}`: {e}", None

    subfolders.sort(key=lambda s: s.lower())

    NAV_STATE[user_id] = {
        "path": target_path,
        "subfolders": subfolders,
        "page": page
    }

    PAGE_SIZE = 8
    start_idx = page * PAGE_SIZE
    page_subs = subfolders[start_idx:start_idx + PAGE_SIZE]

    buttons = []
    row = []
    for i, name in enumerate(page_subs):
        idx = start_idx + i
        label = f"📁 {name[:14]}…" if len(name) > 14 else f"📁 {name}"
        row.append(InlineKeyboardButton(label, callback_data=f"nav_f_{idx}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # Pagination buttons
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"nav_p_{page-1}"))
    if start_idx + PAGE_SIZE < len(subfolders):
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"nav_p_{page+1}"))
    if nav_row:
        buttons.append(nav_row)

    # Actions row
    action_row = []
    parent = os.path.dirname(target_path)
    if parent and parent != target_path and os.path.exists(parent):
        action_row.append(InlineKeyboardButton("⬆️ Up Level", callback_data="nav_up"))
    action_row.append(InlineKeyboardButton("🔄 Refresh", callback_data="nav_refresh"))
    buttons.append(action_row)

    # THE BIG BUTTON: Upload everything in this folder
    buttons.append([
        InlineKeyboardButton(f"🚀 Upload This Folder ({file_count} files, {humanbytes(total_size)})", callback_data="nav_upload_curr")
    ])

    text = (
        f"📂 **Current Folder:**\n`{target_path}`\n\n"
        f"• **Files directly inside:** {file_count} ({humanbytes(total_size)})\n"
        f"• **Subfolders found:** {len(subfolders)}\n\n"
        f"👉 Tap any subfolder to enter it, or tap the button below to upload."
    )
    return text, InlineKeyboardMarkup(buttons)

def build_menu_markup(user_id: int):
    st = get_user_settings(user_id)
    captions_label = "📝 Captions: ON ✅" if st["use_captions"] else "📝 Captions: OFF ❌"
    target_label = f"📢 Destination: {st['target_name']}"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📁 Browse Phone Folders (Interactive)", callback_data="open_browser")],
        [InlineKeyboardButton(target_label, callback_data="show_channel_help")],
        [InlineKeyboardButton(captions_label, callback_data="toggle_captions")],
        [
            InlineKeyboardButton("📊 Check History", callback_data="check_history"),
            InlineKeyboardButton("🔄 Reset History", callback_data="reset_history")
        ]
    ])

@app.on_message(filters.command("start") | filters.command("settings"))
async def start_handler(client: Client, message: Message):
    user_id = message.from_user.id
    st = get_user_settings(user_id)

    await message.reply_text(
        f"📂 **Phone Folder Backup Bot (2GB Mode)**\n\n"
        f"🎯 **Current Destination:** `{st['target_name']}`\n"
        f"📝 **Captions:** `{'ENABLED' if st['use_captions'] else 'DISABLED (Clean Mode)'}`\n\n"
        f"**How to configure a Channel:**\n"
        f"1. Create a channel & add this bot as an **Administrator**.\n"
        f"2. Send: `/set_channel @your_channel` or channel link.\n"
        f"3. Send `/captions off` if you prefer no captions in your channel!\n\n"
        f"**Commands:**\n"
        f"• `/scan <folder>` - Preview files in a folder\n"
        f"• `/backup <folder>` - Upload folder contents\n"
        f"• `/set_channel <@channel>` - Set upload channel\n"
        f"• `/clear_channel` - Reset to private chat\n"
        f"• `/captions <on/off>` - Toggle captions\n"
        f"• `/cancel` - Stop active backup",
        reply_markup=build_menu_markup(user_id)
    )

@app.on_message(filters.command("set_channel"))
async def set_channel_cmd(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text(
            "ℹ️ Usage: `/set_channel <@channel_username or link or ID>`\n"
            "Example: `/set_channel @my_storage_channel`\n\n"
            "⚠️ Make sure to add this bot as an **Admin** in the channel first!"
        )
        return

    channel_input = parts[1].strip()

    # Clean up t.me links
    if "t.me/" in channel_input:
        channel_input = channel_input.split("t.me/")[-1].replace("/", "").strip()
        if not channel_input.startswith("@") and not channel_input.startswith("-"):
            channel_input = "@" + channel_input

    # Parse numeric channel ID if applicable
    try:
        if channel_input.startswith("-100") or (channel_input.startswith("-") and channel_input[1:].isdigit()):
            channel_input = int(channel_input)
    except Exception:
        pass

    try:
        chat = await client.get_chat(channel_input)
        target_name = f"@{chat.username}" if chat.username else f"Channel: {chat.title}"

        # Default captions to False for channels as requested by user!
        update_user_settings(message.from_user.id, "target_chat", chat.id)
        update_user_settings(message.from_user.id, "target_name", target_name)
        update_user_settings(message.from_user.id, "use_captions", False)

        await message.reply_text(
            f"✅ **Channel Linked Successfully!**\n\n"
            f"📢 **Destination:** `{target_name}`\n"
            f"📝 **Captions:** Automatically set to **OFF** for clean uploads.\n"
            f"(You can turn captions back on anytime with `/captions on` or in `/settings`)."
        )
    except Exception as e:
        await message.reply_text(
            f"❌ Could not access channel: `{e}`\n\n"
            f"Please verify:\n"
            f"1. The username or ID is correct.\n"
            f"2. You added this bot to the channel as an **Administrator** with permission to post messages."
        )

@app.on_message(filters.command("clear_channel"))
async def clear_channel_cmd(client: Client, message: Message):
    update_user_settings(message.from_user.id, "target_chat", None)
    update_user_settings(message.from_user.id, "target_name", "Private Chat")
    update_user_settings(message.from_user.id, "use_captions", True)
    await message.reply_text("✅ Target reset to **Private Chat** (Captions: ON).")

@app.on_message(filters.command("captions"))
async def captions_cmd(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    user_id = message.from_user.id
    if len(parts) < 2:
        st = get_user_settings(user_id)
        await message.reply_text(f"📝 Current captions status: **{'ON' if st['use_captions'] else 'OFF'}**.\nUsage: `/captions on` or `/captions off`")
        return

    val = parts[1].strip().lower()
    if val in ["on", "true", "yes", "1"]:
        update_user_settings(user_id, "use_captions", True)
        await message.reply_text("✅ Captions **ENABLED**.")
    elif val in ["off", "false", "no", "0"]:
        update_user_settings(user_id, "use_captions", False)
        await message.reply_text("✅ Captions **DISABLED** (Clean Upload Mode).")
    else:
        await message.reply_text("ℹ️ Please specify `on` or `off` (e.g., `/captions off`).")

@app.on_message(filters.command("scan"))
async def scan_command(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("ℹ️ Usage: `/scan <folder_path>`\nExample: `/scan /sdcard/Download` or `/scan ./downloads`")
        return

    folder = parts[1].strip()
    if not os.path.exists(folder):
        await message.reply_text(f"❌ Folder not found: `{folder}`")
        return

    files = get_folder_files(folder)
    total_size = sum(f[1] for f in files)
    history = load_history()
    already_uploaded = sum(1 for f in files if f[0] in history)
    pending = len(files) - already_uploaded

    LAST_SCANNED[message.from_user.id] = folder

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Start Backup Now", callback_data="start_scanned_backup")]
    ])

    st = get_user_settings(message.from_user.id)
    await message.reply_text(
        f"🔍 **Scan Results:** `{folder}`\n\n"
        f"• **Destination:** `{st['target_name']}`\n"
        f"• **Captions:** `{'ON' if st['use_captions'] else 'OFF'}`\n"
        f"• **Total Files:** {len(files)}\n"
        f"• **Total Size:** {humanbytes(total_size)}\n"
        f"• **Already Backed Up:** {already_uploaded}\n"
        f"• **New Files to Upload:** {pending}",
        reply_markup=keyboard
    )

@app.on_message(filters.command("backup"))
async def backup_command(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("ℹ️ Usage: `/backup <folder_path>`\nExample: `/backup /sdcard/Download`")
        return

    folder = parts[1].strip()
    await run_backup(client, message.from_user.id, folder, message)

@app.on_message(filters.command("cancel"))
async def cancel_command(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in ACTIVE_BACKUPS:
        ACTIVE_BACKUPS[user_id]["cancelled"] = True
        await message.reply_text("🛑 Cancelling active backup...")
    else:
        await message.reply_text("ℹ️ No active backup running.")

# === Inline Callbacks ===
@app.on_callback_query(filters.regex(r"^toggle_captions$"))
async def handle_toggle_captions(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    st = get_user_settings(user_id)
    new_val = not st["use_captions"]
    update_user_settings(user_id, "use_captions", new_val)
    await callback.answer(f"Captions set to {'ON' if new_val else 'OFF'}")
    try:
        await callback.message.edit_reply_markup(reply_markup=build_menu_markup(user_id))
    except Exception:
        pass

@app.on_callback_query(filters.regex(r"^show_channel_help$"))
async def handle_channel_help(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    st = get_user_settings(user_id)
    await callback.answer()
    await callback.message.reply_text(
        f"📢 **Channel Upload Settings**\n\n"
        f"Current Destination: `{st['target_name']}`\n\n"
        f"To change target channel:\n"
        f"1. Add this bot as an **Admin** in your channel.\n"
        f"2. Send: `/set_channel @channel_username`\n\n"
        f"To switch back to direct private chat:\n"
        f"Send: `/clear_channel`"
    )

@app.on_callback_query(filters.regex(r"^preset_"))
async def handle_preset(client: Client, callback: CallbackQuery):
    preset = callback.data.split("_")[1]
    folder = "/sdcard/DCIM/Camera" if preset == "camera" else "/sdcard/Download"
    
    if not os.path.exists(folder):
        await callback.answer(f"Path {folder} not found on this machine. Use /scan <custom_path>.", show_alert=True)
        return

    await callback.answer()
    await run_backup(client, callback.from_user.id, folder, callback.message)

@app.on_callback_query(filters.regex(r"^start_scanned_backup$"))
async def handle_start_backup_btn(client: Client, callback: CallbackQuery):
    folder = LAST_SCANNED.get(callback.from_user.id)
    if not folder or not os.path.exists(folder):
        await callback.answer("Scanned folder not found or session expired. Run /scan again.", show_alert=True)
        return
    await callback.answer()
    await run_backup(client, callback.from_user.id, folder, callback.message)

@app.on_callback_query(filters.regex(r"^cancel_backup_"))
async def handle_cancel_backup(client: Client, callback: CallbackQuery):
    target_user_id = int(callback.data.split("_")[2])
    if target_user_id != callback.from_user.id:
        await callback.answer("Not your backup!", show_alert=True)
        return

    if target_user_id in ACTIVE_BACKUPS:
        ACTIVE_BACKUPS[target_user_id]["cancelled"] = True
        await callback.answer("Cancelling...")
        await callback.message.edit_text("🚫 **Backup stopped by user.** Uploaded files remain saved in chat/channel.")
    else:
        await callback.answer("No active backup.")

@app.on_callback_query(filters.regex(r"^(check|reset)_history$"))
async def handle_history(client: Client, callback: CallbackQuery):
    action = callback.data
    history = load_history()
    if action == "check_history":
        await callback.answer()
        await callback.message.reply_text(f"📊 **Backup History:** {len(history)} files uploaded so far.")
    elif action == "reset_history":
        save_history({})
        await callback.answer("History cleared!", show_alert=True)
        await callback.message.reply_text("🔄 **History reset.** The next backup will re-upload all files.")

# === Interactive Folder Navigation Handlers ===
@app.on_message(filters.command(["browse", "files"]))
async def browse_command(client: Client, message: Message):
    text, markup = get_browser_view(message.from_user.id)
    await message.reply_text(text, reply_markup=markup)

@app.on_callback_query(filters.regex(r"^open_browser$"))
async def handle_open_browser(client: Client, callback: CallbackQuery):
    await callback.answer()
    text, markup = get_browser_view(callback.from_user.id)
    await callback.message.reply_text(text, reply_markup=markup)

@app.on_callback_query(filters.regex(r"^nav_f_(\d+)$"))
async def handle_nav_folder(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    idx = int(callback.data.split("_")[2])
    state = NAV_STATE.get(user_id)
    if not state or idx >= len(state["subfolders"]):
        await callback.answer("Folder session expired. Send /browse again.", show_alert=True)
        return

    next_path = os.path.join(state["path"], state["subfolders"][idx])
    text, markup = get_browser_view(user_id, target_path=next_path, page=0)
    await callback.answer()
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass

@app.on_callback_query(filters.regex(r"^nav_p_(\d+)$"))
async def handle_nav_page(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    page = int(callback.data.split("_")[2])
    state = NAV_STATE.get(user_id)
    if not state:
        await callback.answer("Session expired.")
        return
    text, markup = get_browser_view(user_id, target_path=state["path"], page=page)
    await callback.answer()
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass

@app.on_callback_query(filters.regex(r"^nav_up$"))
async def handle_nav_up(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    state = NAV_STATE.get(user_id)
    if not state:
        await callback.answer("Session expired.")
        return
    parent = os.path.dirname(state["path"])
    text, markup = get_browser_view(user_id, target_path=parent, page=0)
    await callback.answer()
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass

@app.on_callback_query(filters.regex(r"^nav_refresh$"))
async def handle_nav_refresh(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    state = NAV_STATE.get(user_id)
    target = state["path"] if state else None
    page = state["page"] if state else 0
    text, markup = get_browser_view(user_id, target_path=target, page=page)
    await callback.answer("Refreshed!")
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass

@app.on_callback_query(filters.regex(r"^nav_upload_curr$"))
async def handle_nav_upload_curr(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    state = NAV_STATE.get(user_id)
    if not state:
        await callback.answer("Session expired. Type /browse again.", show_alert=True)
        return
    folder = state["path"]
    await callback.answer(f"Starting backup of this folder...")
    await run_backup(client, user_id, folder, callback.message)

async def run_backup(client: Client, user_id: int, folder: str, context_message: Message):
    if not os.path.exists(folder):
        await context_message.reply_text(f"❌ Folder does not exist: `{folder}`")
        return

    if user_id in ACTIVE_BACKUPS:
        await context_message.reply_text("⚠️ A backup is already running! Type `/cancel` to stop it.")
        return

    st = get_user_settings(user_id)
    target_chat = st.get("target_chat") or user_id
    use_captions = st.get("use_captions", True)

    ACTIVE_BACKUPS[user_id] = {"cancelled": False}
    status = await context_message.reply_text(f"🔍 Scanning folder `{folder}`...")

    files = get_folder_files(folder)
    if not files:
        await status.edit_text(f"⚠️ No files found in `{folder}`.")
        ACTIVE_BACKUPS.pop(user_id, None)
        return

    history = load_history()
    # Filter out files already uploaded with same mtime
    to_upload = [f for f in files if history.get(f[0], {}).get("mtime") != f[2]]

    if not to_upload:
        await status.edit_text(f"✅ All {len(files)} files in `{folder}` are already backed up!")
        ACTIVE_BACKUPS.pop(user_id, None)
        return

    total_count = len(to_upload)
    uploaded_count = 0
    skipped_count = 0

    await status.edit_text(
        f"🚀 Found **{total_count}** new files to upload.\n"
        f"📢 **Destination:** `{st['target_name']}`\n"
        f"📝 **Captions:** `{'ON' if use_captions else 'OFF (Clean Mode)'}`\n\n"
        f"Starting batch upload now..."
    )

    try:
        for idx, (filepath, size, mtime) in enumerate(to_upload, start=1):
            if ACTIVE_BACKUPS.get(user_id, {}).get("cancelled"):
                break

            filename = os.path.basename(filepath)

            # Skip files larger than 2GB
            if size > 2097152000:
                skipped_count += 1
                continue

            # Caption logic: omit caption if use_captions is False
            caption_text = f"📁 `{filename}`\n📦 `{humanbytes(size)}`" if use_captions else None

            start_t = time.time()
            try:
                await client.send_document(
                    chat_id=target_chat,
                    document=filepath,
                    caption=caption_text,
                    progress=file_progress,
                    progress_args=(client, status, start_t, user_id, idx, total_count, filename)
                )
                uploaded_count += 1
                history[filepath] = {"size": size, "mtime": mtime, "uploaded_at": time.time()}
                save_history(history)
                # Polite pause to prevent Telegram flood limits
                await asyncio.sleep(1.5)
            except Exception as e:
                if ACTIVE_BACKUPS.get(user_id, {}).get("cancelled"):
                    break
                print(f"Failed to upload {filename}: {e}")
                await asyncio.sleep(2.0)

        if ACTIVE_BACKUPS.get(user_id, {}).get("cancelled"):
            await status.edit_text(f"🚫 **Backup Cancelled.**\nUploaded {uploaded_count}/{total_count} files before stopping.")
        else:
            await status.edit_text(
                f"🎉 **Batch Backup Complete!**\n\n"
                f"• **Uploaded:** {uploaded_count} files\n"
                f"• **Destination:** `{st['target_name']}`\n"
                f"• **Captions:** `{'ON' if use_captions else 'OFF'}`\n"
                f"• **Skipped (>2GB):** {skipped_count} files"
            )

    finally:
        ACTIVE_BACKUPS.pop(user_id, None)

if __name__ == "__main__":
    print("🚀 Starting Phone Folder Backup Bot (Channel & Caption support enabled)...")
    app.run()
