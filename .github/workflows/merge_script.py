import json
import os
import re
import subprocess
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GDRIVE_CREDENTIALS = os.environ.get("GDRIVE_CREDENTIALS", "").strip()
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "").strip()

TEMP_DIR = "/tmp/drama_videos"
LIST_FILE = "/tmp/mylist.txt"

os.makedirs(TEMP_DIR, exist_ok=True)

def send_telegram_message(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram variables missing, skipping notification.")
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            },
            timeout=30
        )
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

def sanitize_filename(name):
    cleaned = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF _-]+', '', name).strip()
    return cleaned or "Series"

def load_payload():
    with open("data.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, str):
        data = json.loads(data)

    return data

def download_episode(url, output_path):
    r = requests.get(url, stream=True, verify=False, timeout=180)
    r.raise_for_status()

    with open(output_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)

def merge_videos(list_file, final_output):
    cmd = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        final_output,
        "-y",
        "-loglevel", "error"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "FFmpeg merge failed")

def upload_to_drive(file_path, file_name):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds_data = json.loads(GDRIVE_CREDENTIALS)
    creds = service_account.Credentials.from_service_account_info(
        creds_data,
        scopes=["https://www.googleapis.com/auth/drive"]
    )

    service = build("drive", "v3", credentials=creds)

    metadata = {"name": file_name}
    if GDRIVE_FOLDER_ID:
        metadata["parents"] = [GDRIVE_FOLDER_ID]

    media = MediaFileUpload(file_path, mimetype="video/mp4", resumable=True)

    created = service.files().create(
        body=metadata,
        media_body=media,
        fields="id, webViewLink, webContentLink"
    ).execute()

    service.permissions().create(
        fileId=created["id"],
        body={"type": "anyone", "role": "reader"}
    ).execute()

    refreshed = service.files().get(
        fileId=created["id"],
        fields="id, webViewLink, webContentLink"
    ).execute()

    return refreshed.get("webViewLink") or refreshed.get("webContentLink")

def main():
    data = load_payload()

    series_title = data.get("series_title", "مسلسل_بدون_اسم")
    episodes = data.get("episodes", [])

    if not episodes:
        raise ValueError("No episodes found in JSON payload")

    movie_name = sanitize_filename(series_title)
    final_output = f"/tmp/{movie_name}_Full_Movie.mp4"

    send_telegram_message(
        f"🚀 *بدأ الدمج على GitHub Actions*\n🎬 *{series_title}*\n📦 عدد الحلقات: {len(episodes)}"
    )

    list_content = ""
    downloaded_count = 0

    for ep in episodes:
        url = ep.get("video_url", "")
        ep_num = ep.get("episode", "?")

        if not url or "http" not in str(url):
            print(f"Skipping episode {ep_num}: invalid URL")
            continue

        output_path = os.path.join(TEMP_DIR, f"ep_{ep_num}.mp4")

        try:
            print(f"Downloading episode {ep_num}...")
            download_episode(url, output_path)
            list_content += f"file '{output_path}'\n"
            downloaded_count += 1
        except Exception as e:
            print(f"Failed downloading episode {ep_num}: {e}")

    if downloaded_count == 0:
        raise RuntimeError("No episodes were downloaded successfully")

    with open(LIST_FILE, "w", encoding="utf-8") as f:
        f.write(list_content)

    send_telegram_message("⏳ اكتمل تحميل الحلقات، جاري الدمج الآن...")

    merge_videos(LIST_FILE, final_output)

    send_telegram_message("☁️ اكتمل الدمج، جاري رفع الفيلم إلى Google Drive...")

    drive_link = upload_to_drive(final_output, f"{movie_name}_Full_Movie.mp4")

    if not drive_link:
        raise RuntimeError("Upload completed but no Drive link was returned")

    send_telegram_message(
        f"🎉 *اكتمل الدمج والرفع بنجاح!*\n\n"
        f"🎬 *{series_title}*\n"
        f"📦 الحلقات المدمجة: {downloaded_count}\n\n"
        f"🔗 [رابط الفيلم على Google Drive]({drive_link})"
    )

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        error_message = str(e).replace("_", "\\_").replace("-", "\\-")
        print(f"Fatal error: {e}")
        send_telegram_message(f"❌ حدث خطأ أثناء الدمج أو الرفع:\n`{error_message}`")
        raise
