# Folder Uploader Bot

An automated bulk folder uploader bot built with **Pyrogram (MTProto)**. It scans any folder on your phone (or laptop) and uploads all files one by one to Telegram (chat or dedicated channel) with **2 GB support per file**, incremental synchronization, and caption toggles.

---

## ✨ Features
- 🚀 **2 GB File Uploads**: Powered by Telegram MTProto to bypass the standard 50 MB bot limit.
- 🔄 **Incremental Sync (`backup_history.json`)**:
  - Remembers file sizes and modification timestamps.
  - Skips already-uploaded files on future runs—saving bandwidth and time!
- 📢 **Custom Channel Support**:
  - Upload directly to any Telegram Channel (just add the bot as an Administrator).
- 📝 **Clean Channel Mode (Caption Toggle)**:
  - Option to upload without captions so your channel remains clean.
  - Toggle captions on or off anytime via `/captions on` or `/captions off`.
- 📊 **Live Progress Bar**:
  - Shows file index (`[14/50] IMG_20261019.jpg [████░░░░░░] 48%`), transfer speed, and ETA.
  - Progress updates stay in your private chat so channels are never spammed.
- ❌ **Instant Cancel**:
  - Use `/cancel` or tap `❌ Cancel Backup` to halt batch uploads cleanly anytime.
- 🛡️ **Flood-Wait Protection**:
  - Built-in polite throttling between file uploads to prevent Telegram rate limits.

---

## 🔑 Prerequisites (Get Your API Keys)
Before running the bot on Windows or Termux, you need 3 credentials:
1. **`BOT_TOKEN`**: Open Telegram $\rightarrow$ Message [`@BotFather`](https://t.me/BotFather) $\rightarrow$ `/newbot` $\rightarrow$ copy the HTTP token.
2. **`API_ID` & `API_HASH`**:
   - Go to [my.telegram.org](https://my.telegram.org) and log in with your phone number.
   - Click **API development tools**.
   - Create an application (name it anything, e.g. `backupbot`).
   - Copy `api_id` (numbers) and `api_hash` (string).
3. **Your Numerical Telegram User ID**: Message [`@userinfobot`](https://t.me/userinfobot) on Telegram to get your User ID.

---

## 💻 Running on Windows

### 1. Clone the Repository
```powershell
git clone https://github.com/aaryan-mi/folder-uploader.git
cd folder-uploader
```

### 2. Set Up Python Environment & Install Dependencies
```powershell
python -m venv venv
# Enable execution policy if needed:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 3. Configure Credentials
Open `config.py` in your text editor and enter your values:
```python
API_ID = 12345678
API_HASH = "your_api_hash_here"
BOT_TOKEN = "your_bot_token"
ALLOWED_USERS = [123456789]
```

### 4. Start the Bot
```powershell
python backup_bot.py
```

---

## 📱 Running on Android (Termux)

Termux lets you run the backup bot directly on your Android phone, uploading your Camera photos, WhatsApp media, or Downloads directly to Telegram in the background.

### 1. Update Packages & Install System Tools
Open Termux on Android and run:
```bash
pkg update && pkg upgrade -y
pkg install python git clang tmux libffi -y
```

### 2. Grant Storage Permission
```bash
termux-setup-storage
```
*(Tap "Allow" on the Android permission popup so the bot can access `/sdcard/DCIM` and `/sdcard/Download`).*

### 3. Clone the Repository
```bash
git clone https://github.com/aaryan-mi/folder-uploader.git
cd folder-uploader
```

### 4. Install Python Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Configure `config.py`
Edit `config.py` using `nano`:
```bash
nano config.py
```
*(Paste your `API_ID`, `API_HASH`, `BOT_TOKEN`, and `ALLOWED_USERS`. Press `Ctrl + O`, `Enter` to save, then `Ctrl + X` to exit).*

### 6. Keep Alive & Run 24/7 in Background
```bash
# 1. Prevent CPU sleep when screen turns off
termux-wake-lock

# 2. Start a persistent tmux terminal session
tmux new -s backup

# 3. Launch the bot
python backup_bot.py
```

- **To Detach & Leave Running:** Press `Ctrl + B`, then press `D`. You can now safely close the Termux app!
- **To Re-attach Later:** Run `tmux attach -t backup`.

---

## 📖 Bot Commands & Usage

### Setting Up a Channel (Optional):
1. Create a Telegram channel and add your bot as an **Administrator** with permission to post messages.
2. Send:
   ```text
   /set_channel @your_channel_username
   ```
   *(Captions are automatically turned OFF for channels).*
3. To switch back to private chat anytime, send `/clear_channel`.

### Captions:
- `/captions off` - Clean mode (no captions, only raw files).
- `/captions on` - Includes file name and size in caption.

### Interactive Phone File Browser:
- Send `/browse` (or tap **`📁 Browse Phone Folders`** in `/start`).
- Tap subfolders to navigate inside them.
- Tap **`⬆️ Up Level`** to go to parent folder.
- Tap **`🚀 Upload This Folder`** to automatically copy and upload all files in that folder!

### Scanning & Backing Up via Path:
- `/browse` - Open the interactive folder navigator.
- `/scan <folder_path>` - Scans the folder and displays total files and size.
  - Example on Termux: `/scan /sdcard/Download` or `/scan /sdcard/DCIM/Camera`
  - Example on Windows: `/scan C:\Users\AARYAN\Downloads`
- Tap **`🚀 Start Backup Now`** or run `/backup <folder_path>`.
- `/cancel` - Instantly aborts the active backup.
