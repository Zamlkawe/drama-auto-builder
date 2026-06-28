import json
import os
import sys
import subprocess
import requests
import urllib3
import traceback

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TELEGRAM_TOKEN       = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID              = os.environ.get("TELEGRAM_CHAT_ID")
GDRIVE_CLIENT_ID     = os.environ.get("GDRIVE_CLIENT_ID")
GDRIVE_CLIENT_SECRET = os.environ.get("GDRIVE_CLIENT_SECRET")
GDRIVE_REFRESH_TOKEN = os.environ.get("GDRIVE_REFRESH_TOKEN")
GDRIVE_FOLDER_ID     = os.environ.get("GDRIVE_FOLDER_ID")

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
            print(f"Telegram send failed: {e}", flush=True)


def fail(msg):
    print(f"\n❌ FATAL ERROR: {msg}\n", flush=True)
    send_telegram(f"❌ {msg}")
    sys.exit(1)


# ── التحقق من المدخلات ─────────────────────────────────────────────

if len(sys.argv) < 2:
    fail("Usage: python merge_script.py <json_path>")

json_path = sys.argv[1]
print(f"📂 JSON path: {json_path}", flush=True)

if not os.path.exists(json_path):
    fail(f"ملف JSON غير موجود: {json_path}")

if not all([GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN]):
    fail("❌ متغيرات OAuth غير موجودة في Secrets")

if not GDRIVE_FOLDER_ID:
    fail("متغير GDRIVE_FOLDER_ID غير موجود في Secrets")

print(f"✅ GDRIVE_FOLDER_ID = {GDRIVE_FOLDER_ID}", flush=True)

# ── قراءة الـ JSON ─────────────────────────────────────────────────

with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

episodes   = data.get("episodes", [])
movie_name = "".join(
    x for x in data.get("series_title", "movie")
    if x.isalnum() or x in " _-"
).strip() or "movie"

final_output = f"/tmp/{movie_name}_Full_Movie.mp4"
list_file    = "/tmp/mylist.txt"

print(f"🎬 Series: {data.get('series_title')}", flush=True)
print(f"📦 Episodes: {len(episodes)}", flush=True)

send_telegram(
    f"🚀 *GitHub Actions* بدأ العمل!\n"
    f"🎬 المسلسل: *{data.get('series_title', 'Unknown')}*\n"
    f"📦 الحلقات: {len(episodes)}"
)

# ── تحميل الحلقات ──────────────────────────────────────────────────

list_content     = ""
downloaded_count = 0

for ep in episodes:
    url    = ep.get("video_url", "")
    ep_num = ep.get("episode", "?")

    if not url or "http" not in str(url):
        print(f"⏭ Skipping episode {ep_num}: invalid url", flush=True)
        continue

    try:
        ep_num_int = int(ep_num)
    except Exception:
        print(f"⏭ Skipping episode {ep_num}: invalid number", flush=True)
        continue

    video_path = os.path.join(TEMP_DIR, f"ep_{ep_num_int:04d}.mp4")
    print(f"⬇️ Downloading episode {ep_num}...", flush=True)

    try:
        r = requests.get(url, stream=True, verify=False, timeout=120)
        r.raise_for_status()

        with open(video_path, "wb") as out:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    out.write(chunk)

        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        print(f"✅ Episode {ep_num} downloaded ({size_mb:.1f} MB)", flush=True)
        list_content     += f"file '{video_path}'\n"
        downloaded_count += 1

    except Exception as e:
        print(f"⚠️ Failed episode {ep_num}: {e}", flush=True)

if downloaded_count == 0:
    fail("فشل تحميل كل الحلقات. لا يوجد شيء لدمجه.")

with open(list_file, "w", encoding="utf-8") as f:
    f.write(list_content)

print(f"\n✅ Downloaded {downloaded_count} episodes", flush=True)
send_telegram(f"⏳ اكتمل التحميل ({downloaded_count} حلقة)، جاري الدمج بـ FFmpeg...")

# ── دمج الفيديوهات ─────────────────────────────────────────────────

print("\n🔀 Starting FFmpeg merge...", flush=True)

result = subprocess.run(
    [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        "-fflags", "+genpts",
        "-movflags", "+faststart",
        final_output,
        "-y",
        "-loglevel", "warning"
    ],
    capture_output=True,
    text=True
)

if result.stdout:
    print(f"FFmpeg stdout:\n{result.stdout}", flush=True)
if result.stderr:
    print(f"FFmpeg stderr:\n{result.stderr}", flush=True)

if result.returncode != 0:
    fail(f"فشل الدمج:\n{result.stderr[:500]}")

if not os.path.exists(final_output):
    fail("ملف الدمج لم يُنشأ")

output_size = os.path.getsize(final_output) / (1024 * 1024)
print(f"✅ Merged file: {final_output} ({output_size:.1f} MB)", flush=True)
send_telegram(f"✅ اكتمل الدمج ({output_size:.0f} MB)، جاري الرفع على Google Drive...")

# ── رفع على Google Drive (OAuth) ───────────────────────────────────

print("\n☁️ Starting Google Drive upload (OAuth)...", flush=True)

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

try:
    print(f"🔑 OAuth Client ID: {GDRIVE_CLIENT_ID[:30]}...", flush=True)
    print(f"📁 Target Folder ID: {GDRIVE_FOLDER_ID}", flush=True)
    print(f"📄 File exists: {os.path.exists(final_output)}", flush=True)
    print(f"📊 File size: {output_size:.1f} MB", flush=True)

    # ✅ إنشاء Credentials من Refresh Token
    creds = Credentials(
        None,
        refresh_token=GDRIVE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GDRIVE_CLIENT_ID,
        client_secret=GDRIVE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/drive"]
    )

    # ✅ Refresh token
    print("🔄 Refreshing access token...", flush=True)
    creds.refresh(Request())
    print(f"✅ Token refreshed! Expiry: {creds.expiry}", flush=True)

    service = build("drive", "v3", credentials=creds)

    # ✅ التحقق من الـ Folder
    print("🔍 Checking folder access...", flush=True)
    try:
        folder_info = service.files().get(
            fileId=GDRIVE_FOLDER_ID,
            fields="id, name, mimeType, capabilities"
        ).execute()

        print(f"✅ Folder found: {folder_info.get('name')}", flush=True)
        caps = folder_info.get('capabilities', {})
        print(f"   Can addChildren: {caps.get('canAddChildren', 'N/A')}", flush=True)

    except HttpError as e:
        error_msg = str(e)
        if hasattr(e, 'error_details') and e.error_details:
            error_msg = str(e.error_details)
        print(f"❌ Folder access FAILED: {error_msg}", flush=True)
        raise

    # ✅ إعداد الملف
    file_metadata = {
        "name": f"{movie_name}_Full_Movie.mp4",
        "parents": [GDRIVE_FOLDER_ID]
    }

    media = MediaFileUpload(
        final_output,
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024
    )

    print("📤 Uploading file...", flush=True)

    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink, name, size"
    ).execute()

    print(f"✅ Upload complete!", flush=True)
    print(f"   File ID: {uploaded.get('id')}", flush=True)
    print(f"   Name: {uploaded.get('name')}", flush=True)
    print(f"   Size: {uploaded.get('size')}", flush=True)

    # ✅ إضافة صلاحية Public
    try:
        service.permissions().create(
            fileId=uploaded["id"],
            body={"type": "anyone", "role": "reader"}
        ).execute()
        print("✅ Public permission set", flush=True)
    except Exception as perm_err:
        print(f"⚠️ Permission set failed (non-critical): {perm_err}", flush=True)

    drive_link = uploaded.get("webViewLink")
    if not drive_link:
        drive_link = f"https://drive.google.com/file/d/{uploaded.get('id')}/view"

    print(f"🔗 Drive link: {drive_link}", flush=True)

    send_telegram(
        f"🎉 *اكتمل الدمج والرفع بنجاح!*\n\n"
        f"🎬 *{data.get('series_title', 'Unknown')}*\n"
        f"📦 الحلقات المحمّلة: {downloaded_count}\n"
        f"📁 الحجم: {output_size:.0f} MB\n\n"
        f"🔗 [رابط المشاهدة على Google Drive]({drive_link})"
    )

except Exception as e:
    print(f"\n❌ Upload failed:", flush=True)
    traceback.print_exc()
    fail(f"فشل الرفع على Google Drive:\n{str(e)[:1000]}")
