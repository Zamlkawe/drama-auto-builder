import json
import os
import sys
import subprocess
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GDRIVE_CREDENTIALS = os.environ.get("GDRIVE_CREDENTIALS")

TEMP_DIR = "/tmp/drama_videos"
os.makedirs(TEMP_DIR, exist_ok=True)

def send_telegram(text):
    if TELEGRAM_TOKEN and CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"},
                timeout=30
            )
        except Exception as e:
            print(f"Telegram send failed: {e}")

if len(sys.argv) < 2:
    print("Usage: python merge_script.py <json_path>")
    sys.exit(1)

json_path = sys.argv[1]

if not os.path.exists(json_path):
    print(f"JSON file not found: {json_path}")
    sys.exit(1)

with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

episodes = data.get("episodes", [])
movie_name = "".join(
    x for x in data.get("series_title", "movie")
    if x.isalnum() or x in " _-"
).strip() or "movie"

final_output = f"/tmp/{movie_name}_Full_Movie.mp4"
list_file = "/tmp/mylist.txt"

send_telegram(
    f"🚀 *GitHub Actions* بدأ العمل!\n"
    f"🎬 المسلسل: *{data.get('series_title', 'Unknown')}*\n"
    f"📦 الحلقات: {len(episodes)}"
)

list_content = ""
downloaded_count = 0

for ep in episodes:
    url = ep.get("video_url", "")
    ep_num = ep.get("episode", "?")

    if not url or "http" not in str(url):
        print(f"Skipping episode {ep_num}: invalid url")
        continue

    try:
        ep_num_int = int(ep_num)
    except:
        print(f"Skipping episode {ep_num}: invalid episode number")
        continue

    video_path = os.path.join(TEMP_DIR, f"ep_{ep_num_int:04d}.mp4")
    print(f"Downloading episode {ep_num}...")

    try:
        r = requests.get(url, stream=True, verify=False, timeout=120)
        r.raise_for_status()

        with open(video_path, "wb") as out:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    out.write(chunk)

        list_content += f"file '{video_path}'\n"
        downloaded_count += 1

    except Exception as e:
        print(f"Failed episode {ep_num}: {e}")

if downloaded_count == 0:
    send_telegram("❌ فشل تحميل كل الحلقات. لا يوجد شيء لدمجه.")
    sys.exit(1)

with open(list_file, "w", encoding="utf-8") as f:
    f.write(list_content)

send_telegram("⏳ اكتمل التحميل، جاري الدمج بـ FFmpeg...")

result = subprocess.run(
    [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        final_output,
        "-y",
        "-loglevel", "error"
    ],
    capture_output=True,
    text=True
)

if result.returncode != 0:
    send_telegram(f"❌ فشل الدمج:\n{result.stderr[:500]}")
    sys.exit(1)

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

if not GDRIVE_CREDENTIALS:
    send_telegram("❌ متغير GDRIVE_CREDENTIALS غير موجود.")
    sys.exit(1)

creds_data = json.loads(GDRIVE_CREDENTIALS)
creds = service_account.Credentials.from_service_account_info(
    creds_data,
    scopes=["https://www.googleapis.com/auth/drive"]
)

service = build("drive", "v3", credentials=creds)

file_metadata = {
    "name": f"{movie_name}_Full_Movie.mp4",
    "parents": ["root"]
}

media = MediaFileUpload(final_output, mimetype="video/mp4", resumable=True)
uploaded = service.files().create(
    body=file_metadata,
    media_body=media,
    fields="id, webViewLink"
).execute()

service.permissions().create(
    fileId=uploaded["id"],
    body={"type": "anyone", "role": "reader"}
).execute()

drive_link = uploaded["webViewLink"]

send_telegram(
    f"🎉 *اكتمل الدمج والرفع بنجاح!*\n\n"
    f"🎬 *{data.get('series_title', 'Unknown')}*\n"
    f"📦 الحلقات المحمّلة: {downloaded_count}\n\n"
    f"🔗 [رابط المشاهدة على Google Drive]({drive_link})"
)
