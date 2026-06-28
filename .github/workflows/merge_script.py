import json
import os
import sys
import subprocess
import requests
import urllib3
import traceback
import re
import base64
import time

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
final_srt    = f"/tmp/{movie_name}_Full_Movie.srt"
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
subtitle_map     = {}  # ep_num -> srt_content

for ep in episodes:
    url    = ep.get("video_url", "")
    ep_num = ep.get("episode", "?")
    sub_url = ep.get("subtitle_url", "")  # ✅ جديد: رابط الترجمة

    if not url or "http" not in str(url):
        print(f"⏭ Skipping episode {ep_num}: invalid url", flush=True)
        continue

    try:
        ep_num_int = int(ep_num)
    except Exception:
        print(f"⏭ Skipping episode {ep_num}: invalid number", flush=True)
        continue

    video_path = os.path.join(TEMP_DIR, f"ep_{ep_num_int:04d}.mp4")
    srt_path   = os.path.join(TEMP_DIR, f"ep_{ep_num_int:04d}.srt")
    print(f"⬇️ Downloading episode {ep_num}...", flush=True)

    try:
        # ✅ تحميل الفيديو
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

        # ✅ تحميل الترجمة لو موجودة
        if sub_url and "http" in str(sub_url):
            try:
                print(f"  📝 Downloading subtitle for ep {ep_num}...", flush=True)
                sub_r = requests.get(sub_url, verify=False, timeout=30)
                if sub_r.status_code == 200:
                    srt_content = normalize_subtitles(sub_r.text)
                    if srt_content.strip():
                        with open(srt_path, "w", encoding="utf-8") as f:
                            f.write(srt_content)
                        subtitle_map[ep_num_int] = srt_content
                        print(f"  ✅ Subtitle ep {ep_num} downloaded", flush=True)
            except Exception as sub_e:
                print(f"  ⚠️ Subtitle download failed: {sub_e}", flush=True)

    except Exception as e:
        print(f"⚠️ Failed episode {ep_num}: {e}", flush=True)

if downloaded_count == 0:
    fail("فشل تحميل كل الحلقات. لا يوجد شيء لدمجه.")

with open(list_file, "w", encoding="utf-8") as f:
    f.write(list_content)

print(f"\n✅ Downloaded {downloaded_count} episodes", flush=True)
if subtitle_map:
    print(f"📝 Downloaded {len(subtitle_map)} subtitle files", flush=True)

send_telegram(f"⏳ اكتمل التحميل ({downloaded_count} حلقة)، جاري الدمج بـ FFmpeg...")

# ── دمج الترجمات ───────────────────────────────────────────────────

merged_srt = None
if subtitle_map:
    print("\n📝 Merging subtitles...", flush=True)
    merged_srt = merge_subtitles(TEMP_DIR, subtitle_map, downloaded_count)
    if merged_srt and os.path.exists(merged_srt):
        print(f"✅ Merged subtitle: {merged_srt}", flush=True)

# ── دمج الفيديوهات (مع إصلاح التقطيع) ──────────────────────────────

print("\n🔀 Starting FFmpeg merge...", flush=True)

# ✅ الطريقة المحسّنة: تحويل لـ TS أولاً ثم دمج
# ده بيمنع مشاكل الـ timestamps والتقطيع

# خطوة 1: تحويل كل فيديو لـ TS (MPEG-TS)
print("🔄 Converting to TS format...", flush=True)
ts_files = []
for ep in range(1, downloaded_count + 1):
    mp4_path = os.path.join(TEMP_DIR, f"ep_{ep:04d}.mp4")
    ts_path  = os.path.join(TEMP_DIR, f"ep_{ep:04d}.ts")

    if not os.path.exists(mp4_path):
        continue

    cmd = [
        "ffmpeg", "-y",
        "-i", mp4_path,
        "-c", "copy",
        "-bsf:v", "h264_mp4toannexb",
        "-f", "mpegts",
        ts_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and os.path.exists(ts_path):
        ts_files.append(ts_path)
        print(f"  ✅ Ep {ep} → TS", flush=True)
    else:
        print(f"  ⚠️ Ep {ep} TS conversion failed, using MP4 directly", flush=True)

# خطوة 2: دمج الـ TS files
if len(ts_files) >= 2:
    # إنشاء list file للـ TS
    ts_list_file = "/tmp/ts_list.txt"
    with open(ts_list_file, "w", encoding="utf-8") as f:
        for tsf in ts_files:
            f.write(f"file '{tsf}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-fflags", "+genpts",
        "-f", "concat",
        "-safe", "0",
        "-i", ts_list_file,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        "-movflags", "+faststart",
        final_output
    ]
else:
    # لو فيديو واحد بس، استخدم MP4 مباشرة
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        "-fflags", "+genpts",
        "-movflags", "+faststart",
        final_output
    ]

result = subprocess.run(cmd, capture_output=True, text=True)

if result.stdout:
    print(f"FFmpeg stdout:\n{result.stdout}", flush=True)
if result.stderr:
    print(f"FFmpeg stderr:\n{result.stderr}", flush=True)

if result.returncode != 0:
    fail(f"فشل الدمج:\n{result.stderr[:500]}")

if not os.path.exists(final_output):
    fail("ملف الدمج لم يُنشأ")

# ✅ تنظيف الـ TS files
for tsf in ts_files:
    try:
        os.remove(tsf)
    except:
        pass

output_size = os.path.getsize(final_output) / (1024 * 1024)
print(f"✅ Merged file: {final_output} ({output_size:.1f} MB)", flush=True)

# ── رفع على Google Drive ───────────────────────────────────────────

print("\n☁️ Starting Google Drive upload...", flush=True)

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

try:
    creds = Credentials(
        None,
        refresh_token=GDRIVE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GDRIVE_CLIENT_ID,
        client_secret=GDRIVE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/drive"]
    )

    print("🔄 Refreshing access token...", flush=True)
    creds.refresh(Request())
    print(f"✅ Token refreshed!", flush=True)

    service = build("drive", "v3", credentials=creds)

    # ✅ رفع الفيديو
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

    print("📤 Uploading video...", flush=True)
    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink, name"
    ).execute()

    video_id = uploaded.get("id")
    print(f"✅ Video uploaded: {uploaded.get('name')}", flush=True)

    # ✅ رفع الترجمة لو موجودة
    srt_link = None
    if merged_srt and os.path.exists(merged_srt):
        srt_metadata = {
            "name": f"{movie_name}_Full_Movie.srt",
            "parents": [GDRIVE_FOLDER_ID]
        }
        srt_media = MediaFileUpload(
            merged_srt,
            mimetype="application/x-subrip",
            resumable=True
        )

        print("📤 Uploading subtitle...", flush=True)
        srt_uploaded = service.files().create(
            body=srt_metadata,
            media_body=srt_media,
            fields="id, webViewLink, name"
        ).execute()

        srt_link = f"https://drive.google.com/file/d/{srt_uploaded.get('id')}/view"
        print(f"✅ Subtitle uploaded: {srt_uploaded.get('name')}", flush=True)

    # ✅ صلاحية Public
    service.permissions().create(
        fileId=video_id,
        body={"type": "anyone", "role": "reader"}
    ).execute()

    drive_link = uploaded.get("webViewLink") or f"https://drive.google.com/file/d/{video_id}/view"

    msg = (
        f"🎉 *اكتمل الدمج والرفع بنجاح!*\n\n"
        f"🎬 *{data.get('series_title', 'Unknown')}*\n"
        f"📦 الحلقات المحمّلة: {downloaded_count}\n"
        f"📁 الحجم: {output_size:.0f} MB"
    )

    if srt_link:
        msg += f"\n📝 الترجمة: [SRT ملف]({srt_link})"

    msg += f"\n\n🔗 [رابط المشاهدة]({drive_link})"

    print(f"🔗 Drive link: {drive_link}", flush=True)
    send_telegram(msg)

except Exception as e:
    traceback.print_exc()
    fail(f"فشل الرفع على Google Drive:\n{str(e)[:1000]}")


# ── دوال مساعدة ─────────────────────────────────────────────────────

def normalize_subtitles(text):
    """تنظيف وتحويل ترجمات VTT/SRT إلى SRT موحدة"""
    if not text:
        return ""

    text = text.replace('\ufeff', '').replace('\r\n', '\n').replace('\r', '\n')
    lines = text.split('\n')

    srt_blocks = []
    current_block_lines = []
    start_ts = ""
    end_ts = ""
    in_block = False

    ts_pattern = re.compile(
        r'(\d{1,2}:)?(\d{1,2}:\d{1,2})[.,](\d{1,3})\s*-->\s*(\d{1,2}:)?(\d{1,2}:\d{1,2})[.,](\d{1,3})'
    )

    def format_time(h, ms, milli):
        h = h.strip(':').zfill(2) if h else "00"
        m, s = ms.split(':')
        m = m.zfill(2)
        s = s.zfill(2)
        milli = milli.ljust(3, '0')[:3]
        return f"{h}:{m}:{s},{milli}"

    for line in lines:
        line = line.strip()

        if not line:
            if in_block and current_block_lines:
                srt_blocks.append((start_ts, end_ts, current_block_lines))
                in_block = False
                current_block_lines = []
            continue

        upper_line = line.upper()
        if upper_line.startswith('WEBVTT') or upper_line.startswith('REGION') or \
           upper_line.startswith('STYLE') or upper_line.startswith('X-TIMESTAMP-MAP'):
            continue
        if line == '::cue {' or line == '}':
            continue
        if not in_block and (line.startswith('color:') or line.startswith('font-')):
            continue

        m = ts_pattern.search(line)
        if m:
            if in_block and current_block_lines:
                srt_blocks.append((start_ts, end_ts, current_block_lines))

            start_ts = format_time(m.group(1), m.group(2), m.group(3))
            end_ts = format_time(m.group(4), m.group(5), m.group(6))
            in_block = True
            current_block_lines = []
            continue

        if in_block:
            clean_line = re.sub(r'<[^>]+>', '', line)
            clean_line = re.sub(r'\[font.*?\]', '', clean_line, flags=re.IGNORECASE)
            clean_line = clean_line.strip()

            if clean_line:
                current_block_lines.append(clean_line)

    if in_block and current_block_lines:
        srt_blocks.append((start_ts, end_ts, current_block_lines))

    output = []
    for i, (start, end, text_lines) in enumerate(srt_blocks, 1):
        if text_lines:
            output.append(str(i))
            output.append(f"{start} --> {end}")
            output.extend(text_lines)
            output.append("")

    return "\n".join(output).strip()


def merge_subtitles(temp_dir, subtitle_map, total_eps):
    """دمج ملفات SRT المتعددة في ملف واحد مع ضبط التوقيت"""
    merged_path = f"/tmp/{movie_name}_Full_Movie.srt"
    cum_offset_ms = 0
    global_index = 1
    all_entries = []

    def ts_to_ms(ts):
        p = ts.replace(',', '.').split(':')
        if len(p) == 2:
            return int((int(p[0]) * 60 + float(p[1])) * 1000)
        elif len(p) >= 3:
            return int((int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])) * 1000))
        return 0

    def ms_to_srt(ms):
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, mi = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{mi:03d}"

    for ep in range(1, total_eps + 1):
        srt_path = os.path.join(temp_dir, f"ep_{ep:04d}.srt")

        if not os.path.exists(srt_path):
            # محاولة الحصول على مدة الفيديو للـ offset
            mp4_path = os.path.join(temp_dir, f"ep_{ep:04d}.mp4")
            dur_ms = 0
            if os.path.exists(mp4_path):
                try:
                    r = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1", mp4_path],
                        capture_output=True, text=True, timeout=30
                    )
                    val = r.stdout.strip()
                    if val and val != "N/A":
                        dur_ms = int(float(val) * 1000)
                except:
                    pass
            cum_offset_ms += dur_ms
            continue

        try:
            with open(srt_path, "r", encoding="utf-8") as f:
                content = f.read()

            content = content.replace('\r\n', '\n')
            matches = list(re.finditer(
                r'(\d{1,2}:\d{1,2}(?::\d{1,2})?[,.]\d+)\s*-->\s*(\d{1,2}:\d{1,2}(?::\d{1,2})?[,.]\d+)',
                content
            ))

            for i, match in enumerate(matches):
                s_ms = ts_to_ms(match.group(1)) + cum_offset_ms
                e_ms = ts_to_ms(match.group(2)) + cum_offset_ms

                start_text_idx = match.end()
                if i + 1 < len(matches):
                    next_match_start = matches[i + 1].start()
                    end_text_idx = content.rfind('\n', start_text_idx, next_match_start)
                    if end_text_idx == -1 or end_text_idx <= start_text_idx:
                        end_text_idx = next_match_start
                else:
                    end_text_idx = len(content)

                raw_text = content[start_text_idx:end_text_idx].strip()
                text_lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
                if text_lines and text_lines[-1].isdigit():
                    text_lines = text_lines[:-1]

                clean_text = '\n'.join(text_lines).strip()
                if not clean_text:
                    continue

                entry_lines = [
                    str(global_index),
                    f"{ms_to_srt(s_ms)} --> {ms_to_srt(e_ms)}",
                    clean_text
                ]
                all_entries.append('\n'.join(entry_lines))
                global_index += 1
        except Exception as e:
            print(f"⚠️ Error parsing subtitle Ep{ep:02d}: {e}", flush=True)

        # الحصول على مدة الفيديو للـ offset
        mp4_path = os.path.join(temp_dir, f"ep_{ep:04d}.mp4")
        dur_ms = 0
        if os.path.exists(mp4_path):
            try:
                r = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", mp4_path],
                    capture_output=True, text=True, timeout=30
                )
                val = r.stdout.strip()
                if val and val != "N/A":
                    dur_ms = int(float(val) * 1000)
            except:
                pass
        cum_offset_ms += dur_ms

    if all_entries:
        with open(merged_path, "w", encoding="utf-8") as f:
            f.write('\n\n'.join(all_entries))
        return merged_path

    return None
