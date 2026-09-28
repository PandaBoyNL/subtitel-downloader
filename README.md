# 🍿 Subtitel downloader (Unraid WebUI) 🎬

A powerful, lightweight WebUI to automatically search, download, and synchronize subtitles for your movies and TV shows directly on your Unraid server. Built with Python, Flask, and `ffsubsync`, this Docker container bypasses the hassle of manual subtitle syncing by analyzing audio tracks natively.

## ✨ Features
*   **Native Server Browser:** Browse your Unraid `/media` share directly within the app. Select individual files or entire folders with ease!
*   **Background Engine & Live Logs:** Start batch processing and safely close your browser. The app runs independently in the background while providing a real-time live logbook upon reopening.
*   **Smart Multi-Key Load Balancer:** Supports multiple OpenSubtitles API keys. It seamlessly rotates between your keys and monitors limits to maximize your free daily download quotas.
*   **Automatic Rate-Limiting & Pauses:** Hits an API download or search limit? The system automatically pauses for 15 minutes, resumes safely on its own, and sends live status alerts to Discord.
*   **Smart Pre-Checking:** Automatically detects if a video file already has an external subtitle file (`.srt`) or an embedded audio/subtitle language track (like Dutch or English), skipping it to save valuable API requests.
*   **Perfect Auto-Sync:** Utilizes `ffsubsync` under the hood to automatically align the downloaded `.srt` file perfectly with the spoken audio in your video.
*   **Detailed Discord Notifications:** Get a beautifully formatted summary sent to your Discord server the moment a batch finishes, categorized into successful, skipped, and failed files.
*   **Multi-Language & UI Localization:** Fetch subtitles in any language supported by OpenSubtitles. The UI automatically translates itself based on your system language!

## 📡 OpenSubtitles API & Feedback
By default, this application connects to the official OpenSubtitles.com REST API. **You will need a free OpenSubtitles account and API Key(s) to use this container.**

**Found a bug or have an idea?** If you know of a better way to filter results, or if you run into any matching issues, please contact me! You can reach out by creating an Issue on this GitHub repository, or use the contact 💬 button in the webgui. I am always looking to improve the app!

## 📦 Unraid Installation
1. Go to the **Apps** tab (Community Applications) in Unraid.
2. Search for **Subtitel downloader**.
3. Click **Install**.
4. **Important:** Fill in your OpenSubtitles Username, Password, and API Key(s) (you can comma-separate multiple keys) in the template settings. By default, this app uses port `5000`. If port `5000` is already in use on your server, please change the 'WebUI Port' (Host Port) during installation to another free port (e.g., `5005`).

## ☕ Support & Buy Me a Coffee 
This project is developed with passion in my free time. If you enjoy using Subtitel downloader and want to help keep the app running, updated, and bug-free, please consider buying me a coffee!

👉 **Buy me a coffee via PayPal (PandaBoyNL)** [https://www.paypal.com/paypalme/PandaBoyNL](https://www.paypal.com/paypalme/PandaBoyNL)

Thank you for your support! ❤️

## 🛠️ Manual Docker Installation
If you prefer to run it via CLI:

```bash
docker run -d \
  --name subtitel-downloader \
  -p 5000:5000 \
  -v /mnt/user/Media:/media \
  -e OS_USERNAME="your_opensubtitles_username" \
  -e OS_PASSWORD="your_opensubtitles_password" \
  -e OS_API_KEYS="your_api_key_1,your_api_key_2,your_api_key_3" \
  -e DISCORD_WEBHOOK="optional_discord_webhook_url" \
  pandaboynl/subtitel-downloader:latest
