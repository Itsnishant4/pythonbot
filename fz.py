import os
import zipfile
import ssl
import certifi
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from telegram.ext import CallbackQueryHandler
import random
import asyncio
from aiohttp import web
from collections import defaultdict
import tempfile
from telegram.error import RetryAfter
from urllib.parse import urlparse



TOKEN = "your telegram bot token"
# SSL context for secure requests
ssl_context = ssl.create_default_context(cafile=certifi.where())

# Maximum file size allowed (50MB)
MAX_FILE_SIZE = 52428800  # 50MB

# User-specific states
user_states = defaultdict(lambda: {"downloading": False, "stop_requested": False, "temp_dir": None})


# Generate a unique temporary directory for each user
def get_user_temp_dir(user_id):
    if not user_states[user_id]["temp_dir"]:
        user_states[user_id]["temp_dir"] = tempfile.mkdtemp(prefix=f"temp_files_{user_id}_")
    return user_states[user_id]["temp_dir"]

# Command: /start
async def start(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("Stop Download", callback_data="stop_download")],
        [InlineKeyboardButton("Clear All Files", callback_data="clear_all")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Hello! Send me files or a URL, and I will compress them into a ZIP file for you. "
        "Use /zip to create the ZIP file and /clearall to stop and delete previous uploads.",
        reply_markup=reply_markup
    )

# Command: clear all files
async def clear_all(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    user_temp_dir = get_user_temp_dir(user_id)

    if os.path.exists(user_temp_dir):
        for file_name in os.listdir(user_temp_dir):
            file_path = os.path.join(user_temp_dir, file_name)
            os.remove(file_path)
        os.rmdir(user_temp_dir)  # Remove the directory
        user_states[user_id]["temp_dir"] = None
        await query.edit_message_text("All files have been cleared.")
        
    else:
        await query.edit_message_text("No files found to delete!")

async def clear__all(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_temp_dir = get_user_temp_dir(user_id)
    if os.path.exists(user_temp_dir):
        for file_name in os.listdir(user_temp_dir):
            file_path = os.path.join(user_temp_dir, file_name)
            os.remove(file_path)
        os.rmdir(user_temp_dir)  # Remove the directory
        user_states[user_id]["temp_dir"] = None
        await update.message.reply_text("All files have been cleared.")
    else:
        await update.message.reply_text("No files found to delete!")
# CallbackQuery handler
async def handle_buttons(update: Update, context: CallbackContext):
    query = update.callback_query
    action = query.data
    user_id = query.from_user.id

    if action == "clear_all":
        await clear_all(update, context)
    elif action == "stop_download":
        user_states[user_id]["stop_requested"] = True
        await query.answer("Stopping the current download...")

    await query.answer()

# Handle file uploads
CHUNK_SIZE = 5 * 1024 * 1024  # 5MB per chunk

async def handle_file(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_state = user_states[user_id]

    if user_state["downloading"]:
        await update.message.reply_text("A download is already in progress. Please wait or stop it using /clearall.")
        return

    user_temp_dir = get_user_temp_dir(user_id)
    file = None
    file_path = ""
    random_file_name = f"{random.randint(1, 1000000)}"

    if update.message.document:
        file = update.message.document
        file_path = os.path.join(user_temp_dir, f"{random_file_name}_{file.file_name}")
    elif update.message.photo:
        file = update.message.photo[-1]
        file_path = os.path.join(user_temp_dir, f"{random_file_name}_photo.jpg")
    elif update.message.video:
        file = update.message.video
        file_path = os.path.join(user_temp_dir, f"{random_file_name}_video.mp4")
    elif update.message.audio:
        file = update.message.audio
        file_path = os.path.join(user_temp_dir, f"{random_file_name}_audio.mp3")
    else:
        await update.message.reply_text("Unsupported file type.")
        return

    if file.file_size > MAX_FILE_SIZE:
        await update.message.reply_text("The file is too large! Please send a file smaller than 50MB.")
        return

    user_state["downloading"] = True
    try:
        progress_msg = await update.message.reply_text("Downloading... 0%")
        await download_file(file, file_path, update, progress_msg, user_state)
    except Exception as e:
        await update.message.reply_text(f"Error while downloading the file: {e}")
    finally:
        user_state["downloading"] = False

async def download_from_url(update: Update, context: CallbackContext):
    if not context.args:
        await update.message.reply_text("Please provide a URL to download, e.g., /url <URL>.")
        return

    url = context.args[0]
    user_id = update.message.from_user.id
    user_dir = get_user_temp_dir(user_id)
    os.makedirs(user_dir, exist_ok=True)

    msg = await update.message.reply_text("Starting download...")

    try:
        print(f"Received URL: {url}")
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            async with session.get(url) as response:
                print(f"HTTP Status: {response.status}")

                if response.status != 200:
                    await msg.edit_text(f"Failed to download: HTTP {response.status}")
                    return

                # Check content length
                total_size = response.headers.get("Content-Length")
                if total_size:
                    total_size = int(total_size)
                    print(f"Content-Length: {total_size} bytes")
                    if total_size > MAX_FILE_SIZE_:
                        await msg.edit_text(f"File too large! Max allowed size is {MAX_FILE_SIZE_ // (1024 * 1024)} MB.")
                        return
                else:
                    print("Content-Length header is missing.")
                    total_size = None

                # Determine file name
                content_disposition = response.headers.get("Content-Disposition")
                if content_disposition and "filename=" in content_disposition:
                    file_name = content_disposition.split("filename=")[-1].strip('"')
                else:
                    file_name = os.path.basename(urlparse(url).path) or "downloaded_file"

                file_path = os.path.join(user_dir, f"{random.randint(1, 1000000)}_{file_name}")
                print(f"File will be saved as: {file_path}")

                # Start downloading
                downloaded = 0
                with open(file_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                        # Update progress
                        if total_size:
                            progress = (downloaded / total_size) * 100
                            progress_bar = generate_progress_bar(progress)
                            await msg.edit_text(f"Downloading... {progress_bar}")
                        else:
                            await msg.edit_text(f"Downloading... {downloaded} bytes")

        await msg.edit_text("Download complete! Use /zip to compress the file.")
        print(f"Download successful: {file_path}")
    except aiohttp.ClientError as e:
        await msg.edit_text(f"Network error: {e}")
        print(f"ClientError: {e}")
    except Exception as e:
        await msg.edit_text(f"Error: {e}")
        print(f"Exception: {e}")

# Create a ZIP file
async def zip_files(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_temp_dir = get_user_temp_dir(user_id)

    if not os.path.exists(user_temp_dir) or not os.listdir(user_temp_dir):
        await update.message.reply_text("No files to compress! Please send some files first.")
        return

    zip_file_path = os.path.join(user_temp_dir, f"files_{user_id}.zip")
    files_in_temp = os.listdir(user_temp_dir)
    total_files = len(files_in_temp)

    zip_msg = await update.message.reply_text("Creating ZIP file... This might take some time.")
    try:
        with zipfile.ZipFile(zip_file_path, "w") as zipf:
            for idx, file_name in enumerate(files_in_temp):
                file_path = os.path.join(user_temp_dir, file_name)
                zipf.write(file_path, arcname=file_name)

                progress = (idx + 1) / total_files * 100
                progress_bar = generate_progress_bar(progress)
                await zip_msg.edit_text(f"Creating ZIP file... {progress_bar}")

        await update.message.reply_document(document=open(zip_file_path, "rb"))
        await update.message.reply_text("Files have been successfully compressed and sent.")
    except Exception as e:
        await update.message.reply_text(f"Error while creating ZIP file: {e}")
    finally:
        os.remove(zip_file_path)
        await zip_msg.delete()

# Cool progress bar
def generate_progress_bar(percentage):
    completed = int(percentage // 5)
    remaining = 20 - completed
    progress_bar = "🟩" * completed + "⬛" * remaining
    return f"{progress_bar} {percentage:.2f}%"

# Command: /help
async def help(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "Here are the available commands:\n"
        "/start - Start the bot\n"
        "/zip - Create a ZIP file from your uploaded files\n"
        "/clearall - Clear all uploaded files\n"
        "/help - Display this help message"
    )


MAX_FILE_SIZE_ = 500 * 1024 * 1024  # 500 MB

async def download_from_url(update: Update, context: CallbackContext):
    if not context.args:
        await update.message.reply_text("Please provide a URL to download, e.g., /url <URL>.")
        return
    
    url = context.args[0]
    user_id = update.message.from_user.id
    user_dir = get_user_temp_dir(user_id)
    os.makedirs(user_dir, exist_ok=True)

    msg = await update.message.reply_text("Starting download...")

    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            async with session.get(url) as response:
                print(f"Response status: {response.status}")
                if response.status != 200:
                    await msg.edit_text(f"Failed to download: HTTP {response.status}")
                    return

                total_size = int(response.headers.get("Content-Length", 0))
                print(f"Content-Length: {total_size}")

                if total_size > MAX_FILE_SIZE_:
                    await msg.edit_text(f"File too large. Max size: {MAX_FILE_SIZE_ // (1024 * 1024)} MB.")
                    return

                content_disposition = response.headers.get("Content-Disposition")
                file_name = (
                    content_disposition.split("filename=")[-1].strip('"')
                    if content_disposition and "filename=" in content_disposition
                    else os.path.basename(urlparse(url).path)
                )

                file_path = os.path.join(user_dir, f"{random.randint(1, 1000000)}_{file_name}")
                print(f"Saving file to: {file_path}")

                downloaded = 0
                with open(file_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        progress = (downloaded / total_size) * 100 if total_size else 0
                        progress_bar = generate_progress_bar(progress)
                        await msg.edit_text(f"Downloading... {progress_bar}")

        await msg.edit_text("Download complete! Use /zip to compress the file.")
    except Exception as e:
        await msg.edit_text(f"Error: {e}")
        print(f"Exception: {e}")

# Main function
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clearall", clear__all))
    app.add_handler(CommandHandler("zip", zip_files))
    app.add_handler(CommandHandler("help", help))
    app.add_handler(CommandHandler("url", download_from_url))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.PHOTO, handle_file))
    app.add_handler(MessageHandler(filters.VIDEO, handle_file))
    app.add_handler(MessageHandler(filters.AUDIO, handle_file))
    app.add_handler(CallbackQueryHandler(handle_buttons))

    print("Bot is running. Press Ctrl+C to stop.")
    app.run_polling()

# Entry point
if __name__ == "__main__":
    main()
