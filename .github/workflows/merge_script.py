import json
import os
import sys
import subprocess
import requests
import urllib3
import traceback
import re
import time
import concurrent.futures
import chardet

# ✅ Firebase Imports
import firebase_admin
from firebase_admin import credentials, firestore

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TELEGRAM_TOKEN       = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID              = os.environ.get("TELEGRAM_CHAT_ID")
GDRIVE_CLIENT_ID     = os.environ.get("GDRIVE_CLIENT_ID")
GDRIVE_CLIENT_SECRET = os.environ.get("GDRIVE_CLIENT_SECRET")
GDRIVE_REFRESH_TOKEN = os.environ.get("GDRIVE_REFRESH_TOKEN")
GDRIVE_FOLDER_ID     = os.environ.get("GDRIVE_FOLDER_ID")
UPLOAD_TARGET        = os.environ.get("UPLOAD_TARGET", "gdrive").lower()
VIDARA_API_KEY       = os.environ.get("VIDARA_API_KEY", "")
FIREBASE_SA_JSON     = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")

TEMP_DIR = "/tmp/drama_videos"
os.makedirs(TEMP_DIR, exist_ok=True)

# 🌐 أساس رابط المزود (يُضبط من data['scraped_from'] في main). افتراضي: نتشورت للتوافق العكسي.
BASE_URL = "https://netshort.dramafren.org"

# ========== أدوات فك الترميز ==========
def decode_subtitle_content(content_bytes):
    encodings = ['utf-8', 'windows-1256', 'iso-8859-6', 'cp1256', 'utf-8-sig']
    for enc in encodings:
        try: return content_bytes.decode(enc)
        except UnicodeDecodeError: continue
    try:
        result = chardet.detect(content_bytes)
        if result and result['encoding']: return content_bytes.decode(result['encoding'])
    except: pass
    return content_bytes.decode('utf-8', errors='ignore')

def read_subtitle_file(srt_path):
    try:
        with open(srt_path, 'rb') as f: raw = f.read()
        return decode_subtitle_content(raw)
    except Exception as e:
        print(f"⚠️ Could not read subtitle file: {e}", flush=True)
        return ""

# ========== Telegram ==========
def send_telegram(text):
    if TELEGRAM_TOKEN and CHAT_ID:
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=30)
        except Exception as e: print(f"Telegram send failed: {e}", flush=True)

def fail(msg):
    print(f"\n❌ FATAL ERROR: {msg}\n")
    send_telegram(f"❌ {msg}")
    sys.exit(1)

def safe_delete(filepath):
    for _ in range(5):
        try:
            if os.path.exists(filepath): os.remove(filepath)
            return True
        except: time.sleep(1)
    return False

# ========== معالجة الترجمة ==========
def normalize_subtitles(text):
    if not text: return ""
    text = text.replace('\ufeff', '').replace('\r\n', '\n').replace('\r', '\n')
    lines = text.split('\n')
    srt_blocks = []
    current_block_lines = []
    start_ts = end_ts = ""
    in_block = False
    ts_pattern = re.compile(r'(\d{1,2}:)?(\d{1,2}:\d{1,2})[.,](\d{1,3})\s*-->\s*(\d{1,2}:)?(\d{1,2}:\d{1,2})[.,](\d{1,3})')

    def format_time(h, ms, milli):
        h = h.strip(':').zfill(2) if h else "00"
        m, s = ms.split(':')
        return f"{h}:{m.zfill(2)}:{s.zfill(2)},{milli.ljust(3, '0')[:3]}"

    for line in lines:
        line = line.strip()
        if not line:
            if in_block and current_block_lines: srt_blocks.append((start_ts, end_ts, current_block_lines))
            in_block = False
            current_block_lines = []
            continue
        upper = line.upper()
        if upper.startswith(('WEBVTT', 'REGION', 'STYLE', 'X-TIMESTAMP-MAP')): continue
        if line in ('::cue {', '}'): continue
        m = ts_pattern.search(line)
        if m:
            if in_block and current_block_lines: srt_blocks.append((start_ts, end_ts, current_block_lines))
            start_ts = format_time(m.group(1), m.group(2), m.group(3))
            end_ts = format_time(m.group(4), m.group(5), m.group(6))
            in_block = True
            current_block_lines = []
            continue
        if in_block:
            clean = re.sub(r'<[^>]+>', '', line)
            clean = re.sub(r'\{.*?\}', '', clean)
            if clean.strip(): current_block_lines.append(clean.strip())
    if in_block and current_block_lines: srt_blocks.append((start_ts, end_ts, current_block_lines))

    output = []
    for i, (start, end, text_lines) in enumerate(srt_blocks, 1):
        if text_lines: output.extend([str(i), f"{start} --> {end}"] + text_lines + [""])
    return "\n".join(output).strip()

def get_video_duration_ms(video_path):
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        val = result.stdout.strip()
        if val and val != "N/A": return int(float(val) * 1000)
    except Exception as e: print(f"⚠️ Could not get duration: {e}", flush=True)
    return 0

def merge_subtitles(temp_dir, subtitle_map, total_eps, movie_name):
    merged_path = f"/tmp/{movie_name}_Full_Movie.srt"
    cum_offset_ms = 0
    global_index = 1
    all_entries = []

    def ts_to_ms(ts):
        p = ts.replace(',', '.').split(':')
        if len(p) == 2: return int((int(p[0]) * 60 + float(p[1])) * 1000)
        elif len(p) >= 3: return int((int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])) * 1000)
        return 0

    def ms_to_srt(ms):
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, mi = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{mi:03d}"

    episode_durations = []
    for ep in range(1, total_eps + 1):
        mp4_path = os.path.join(temp_dir, f"ep_{ep:04d}.mp4")
        episode_durations.append(get_video_duration_ms(mp4_path) if os.path.exists(mp4_path) else 0)

    for ep in range(1, total_eps + 1):
        srt_path = os.path.join(temp_dir, f"ep_{ep:04d}.srt")
        if not os.path.exists(srt_path):
            cum_offset_ms += episode_durations[ep-1]
            continue
        content = read_subtitle_file(srt_path)
        if not content:
            cum_offset_ms += episode_durations[ep-1]
            continue
        content = normalize_subtitles(content)
        if not content:
            cum_offset_ms += episode_durations[ep-1]
            continue

        offset = cum_offset_ms
        blocks = re.split(r'\n\s*\n', content.strip())
        for block in blocks:
            lines = block.split('\n')
            if len(lines) < 3: continue
            timestamp_line = next((i for i, line in enumerate(lines) if '-->' in line), None)
            if timestamp_line is None: continue
            time_str = lines[timestamp_line].strip()
            match = re.search(r'(\d{1,2}:\d{1,2}(?::\d{1,2})?[,.]\d+)\s*-->\s*(\d{1,2}:\d{1,2}(?::\d{1,2})?[,.]\d+)', time_str)
            if not match: continue
            s_ms = ts_to_ms(match.group(1)) + offset
            e_ms = ts_to_ms(match.group(2)) + offset
            text_lines = [l for l in lines[timestamp_line+1:] if l.strip()]
            if not text_lines: continue
            clean_text = '\n'.join(text_lines).strip()
            if clean_text:
                all_entries.append('\n'.join([str(global_index), f"{ms_to_srt(s_ms)} --> {ms_to_srt(e_ms)}", clean_text]))
                global_index += 1
        cum_offset_ms += episode_durations[ep-1]

    if all_entries:
        with open(merged_path, "w", encoding="utf-8") as f: f.write('\n\n'.join(all_entries))
        return merged_path
    return None

# ========== التحميل ==========
def download_with_ytdlp(url, output_path, ep_num):
    try:
        cmd = ["yt-dlp", "-o", output_path, "--no-part", "--no-mtime", "--quiet", "--no-warnings", "--no-check-certificate", "--retries", "10", "--fragment-retries", "10", "--retry-sleep", "1..3", url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
            print(f"✅ Episode {ep_num} downloaded via yt-dlp", flush=True)
            return True
    except Exception as e:
        print(f"⚠️ yt-dlp failed for ep {ep_num}: {e}", flush=True)
        safe_delete(output_path)
    return False

def download_episode(ep_data, temp_dir, subtitle_map):
    url = ep_data.get("video_url", "")
    ep_num = ep_data.get("episode", "?")
    sub_url = ep_data.get("subtitle_url", "")
    if not url or "http" not in str(url): return None
    try: ep_num_int = int(ep_num)
    except: return None

    video_path = os.path.join(temp_dir, f"ep_{ep_num_int:04d}.mp4")
    srt_path = os.path.join(temp_dir, f"ep_{ep_num_int:04d}.srt")

    if sub_url:
        sub_url = str(sub_url).strip()
        if sub_url.startswith("//"): sub_url = "https:" + sub_url
        elif sub_url.startswith("/"): sub_url = BASE_URL + sub_url
        elif not sub_url.startswith("http"): sub_url = BASE_URL + "/" + sub_url

    for attempt in range(5):
        try:
            print(f"⬇️ Downloading episode {ep_num} (attempt {attempt + 1})...", flush=True)
            if ".m3u8" in url or ".mp4" not in url.split("?")[0]:
                if download_with_ytdlp(url, video_path, ep_num): break
            r = requests.get(url, stream=True, verify=False, timeout=120)
            r.raise_for_status()
            with open(video_path, "wb") as out:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk: out.write(chunk)
            break
        except Exception as e:
            print(f"⚠️ Attempt {attempt + 1} failed for ep {ep_num}: {e}", flush=True)
            safe_delete(video_path)
            if attempt < 4: time.sleep(2 ** attempt)
            else: return None

    if not os.path.exists(video_path) or os.path.getsize(video_path) < 10000: return None

    if sub_url:
        try:
            sub_r = requests.get(sub_url, verify=False, timeout=30)
            if sub_r.status_code == 200:
                decoded_text = decode_subtitle_content(sub_r.content)
                normalized = normalize_subtitles(decoded_text)
                if normalized.strip():
                    with open(srt_path, "w", encoding="utf-8") as f: f.write(normalized)
                    subtitle_map[ep_num_int] = normalized
        except Exception as sub_e:
            print(f"⚠️ Subtitle download failed: {sub_e}", flush=True)

    return {"ep": ep_num_int, "path": video_path}

# ========== الرفع ==========
def upload_to_vidara(video_path, title, srt_path=None):
    try:
        import vidara_uploader
        return vidara_uploader.upload_video_to_vidara(video_path, title, srt_path)
    except Exception as e:
        print(f" Vidara upload error: {e}", flush=True)
        traceback.print_exc()
        return None

def upload_to_gdrive(final_output, merged_srt, movie_name, data, downloaded_count, output_size):
    print("\n☁️ Starting Google Drive upload...", flush=True)
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    try:
        creds = Credentials(None, refresh_token=GDRIVE_REFRESH_TOKEN, token_uri="https://oauth2.googleapis.com/token", client_id=GDRIVE_CLIENT_ID, client_secret=GDRIVE_CLIENT_SECRET, scopes=["https://www.googleapis.com/auth/drive"])
        creds.refresh(Request())
        service = build("drive", "v3", credentials=creds)

        file_metadata = {"name": f"{movie_name}_Full_Movie.mp4", "parents": [GDRIVE_FOLDER_ID]}
        media = MediaFileUpload(final_output, mimetype="video/mp4", resumable=True, chunksize=10 * 1024 * 1024)
        uploaded = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink, name").execute()
        video_id = uploaded.get("id")

        srt_link = None
        if merged_srt and os.path.exists(merged_srt):
            srt_metadata = {"name": f"{movie_name}_Full_Movie.srt", "parents": [GDRIVE_FOLDER_ID]}
            srt_media = MediaFileUpload(merged_srt, mimetype="application/x-subrip", resumable=True)
            srt_uploaded = service.files().create(body=srt_metadata, media_body=srt_media, fields="id, webViewLink").execute()
            srt_link = f"https://drive.google.com/file/d/{srt_uploaded.get('id')}/view"

        service.permissions().create(fileId=video_id, body={"type": "anyone", "role": "reader"}).execute()
        drive_link = uploaded.get("webViewLink") or f"https://drive.google.com/file/d/{video_id}/view"

        msg = f"🎉 *اكتمل الدمج والرفع بنجاح!* \n\n🎬 *{data.get('series_title', 'Unknown')}* \n الحلقات: {downloaded_count} \n الحجم: {output_size:.0f} MB "
        if srt_link: msg += f"\n📝 [ملف الترجمة]({srt_link}) "
        msg += f"\n\n🔗 [رابط المشاهدة]({drive_link}) "
        send_telegram(msg)
        return drive_link, srt_link
    except Exception as e:
        traceback.print_exc()
        fail(f"فشل الرفع على Google Drive:\n{str(e)[:1000]}")
        return None, None

# ========== ✅ Firebase Firestore ==========
def init_firebase():
    if not FIREBASE_SA_JSON:
        print("⚠️ FIREBASE_SERVICE_ACCOUNT_JSON not set. Skipping Firebase.", flush=True)
        return None
    try:
        if not firebase_admin._apps:
            cred_dict = json.loads(FIREBASE_SA_JSON)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        print(f"❌ Firebase init failed: {e}", flush=True)
        return None

def upload_to_firebase(db, data, video_link, srt_link):
    if not db or not video_link: return
    try:
        raw_id = str(data.get('drama_id', 'unknown'))
        provider = str(data.get('provider', '') or '').strip()
        # 🔑 معرّف فريد لكل مزود عشان ماييجيش تعارض بين مزودين ليهم نفس الرقم
        doc_id = f"{provider}_{raw_id}" if provider else raw_id
        doc_ref = db.collection('series').document(doc_id)
        
        doc_data = {
            'title': data.get('series_title', 'Unknown'),
            'description': data.get('description', ''),
            'poster_url': data.get('poster_url', ''),
            'category': data.get('category', ''),
            'rating': data.get('rating', ''),
            'year': data.get('year', ''),
            'provider': provider or 'netshort',
            'provider_name': data.get('provider_name', ''),
            'drama_id': raw_id,
            'video_link': video_link,
            'subtitle_link': srt_link or '',
            'total_episodes': data.get('total_episodes', 0),
            'upload_target': UPLOAD_TARGET,
            'updated_at': firestore.SERVER_TIMESTAMP
        }
        
        doc_ref.set(doc_data, merge=True)
        print(f"✅ Uploaded to Firebase (ID: {doc_id})", flush=True)
        print(f"   📝 Title: {doc_data['title']}", flush=True)
        print(f"   🖼️ Poster: {doc_data['poster_url'][:80] if doc_data['poster_url'] else 'N/A'}...", flush=True)
        print(f"   📂 Category: {doc_data['category']}", flush=True)
    except Exception as e:
        print(f"⚠️ Firebase upload failed: {e}", flush=True)

# ========== MAIN ==========
if __name__ == "__main__":
    if len(sys.argv) < 2: fail("Usage: python merge_script.py <json_path>")
    json_path = sys.argv[1]
    if not os.path.exists(json_path): fail(f"ملف JSON غير موجود: {json_path}")

    if UPLOAD_TARGET == "gdrive":
        if not all([GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN]): fail("❌ متغيرات OAuth غير موجودة")
        if not GDRIVE_FOLDER_ID: fail("متغير GDRIVE_FOLDER_ID غير موجود")

    with open(json_path, "r", encoding="utf-8") as f: data = json.load(f)
    _sf = str(data.get("scraped_from", "") or "").strip().rstrip("/")
    if _sf.startswith("http"): BASE_URL = _sf
    print(f"🌐 BASE_URL = {BASE_URL} | provider = {data.get('provider', 'netshort')}", flush=True)
    episodes = data.get("episodes", [])
    movie_name = "".join(x for x in data.get("series_title", "movie") if x.isalnum() or x in " _-").strip() or "movie"

    final_output = f"/tmp/{movie_name}_Full_Movie.mp4"
    list_file = "/tmp/mylist.txt"

    target_name = "vidara.so " if UPLOAD_TARGET == "vidara" else "Google Drive ☁️"
    send_telegram(f"🚀 *GitHub Actions* بدأ العمل!\n🎬 المسلسل: *{data.get('series_title', 'Unknown')}*\n📦 الحلقات: {len(episodes)}\n الوجهة: *{target_name}*")

    subtitle_map = {}
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(download_episode, ep, TEMP_DIR, subtitle_map): ep for ep in episodes}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result: results.append(result)

    results.sort(key=lambda x: x["ep"])
    downloaded_count = len(results)
    if downloaded_count == 0: fail("فشل تحميل كل الحلقات.")

    with open(list_file, "w", encoding="utf-8") as f:
        for r in results: f.write(f"file '{r['path']}'\n")

    send_telegram(f"⏳ اكتمل التحميل ({downloaded_count} حلقة)، جاري الدمج بـ FFmpeg...")

    merged_srt = None
    if subtitle_map:
        merged_srt = merge_subtitles(TEMP_DIR, subtitle_map, downloaded_count, movie_name)

    # FFmpeg Merge Logic
    ts_files = []
    for r in results:
        ep = r["ep"]
        mp4_path = r["path"]
        ts_path = os.path.join(TEMP_DIR, f"ep_{ep:04d}.ts")
        cmd = ["ffmpeg", "-y", "-i", mp4_path, "-c", "copy", "-bsf:v", "h264_mp4toannexb", "-f", "mpegts", "-fflags", "+genpts", ts_path]
        if subprocess.run(cmd, capture_output=True).returncode == 0 and os.path.exists(ts_path):
            ts_files.append(ts_path)

    if len(ts_files) >= 2:
        ts_list_file = "/tmp/ts_list.txt"
        with open(ts_list_file, "w", encoding="utf-8") as f:
            for tsf in ts_files: f.write(f"file '{tsf}'\n")
        cmd = ["ffmpeg", "-y", "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", ts_list_file, "-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", "-copytb", "1", final_output]
    else:
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", "-fflags", "+genpts", "-movflags", "+faststart", "-copytb", "1", final_output]

    if subprocess.run(cmd, capture_output=True).returncode != 0: fail("فشل الدمج بـ FFmpeg")
    if not os.path.exists(final_output): fail("ملف الدمج لم يُنشأ")

    for tsf in ts_files: safe_delete(tsf)
    output_size = os.path.getsize(final_output) / (1024 * 1024)

    final_video_link = ""
    final_srt_link = ""

    if UPLOAD_TARGET == "vidara":
        vidara_result = upload_to_vidara(final_output, data.get('series_title', 'Video'), merged_srt)
        if vidara_result:
            final_video_link = vidara_result.get('url', '')
            msg = f"🎉 *رفع على vidara.so بنجاح!* \n\n🎬 *{data.get('series_title', 'Unknown')}* \n📦 الحلقات: {downloaded_count} \n📁 الحجم: {output_size:.0f} MB \n\n🔗 [رابط المشاهدة]({final_video_link}) "
            send_telegram(msg)
        else:
            fail("فشل الرفع على vidara.so.")
    else:
        drive_link, srt_link = upload_to_gdrive(final_output, merged_srt, movie_name, data, downloaded_count, output_size)
        final_video_link = drive_link
        final_srt_link = srt_link

    # ✅ رفع البيانات إلى Firebase
    print("\n☁️ Uploading metadata to Firebase...", flush=True)
    db = init_firebase()
    if db:
        upload_to_firebase(db, data, final_video_link, final_srt_link)

    # Cleanup
    for r in results: safe_delete(r["path"])
    safe_delete(final_output)
    safe_delete(merged_srt)
    safe_delete(list_file)
    safe_delete("/tmp/ts_list.txt")
    print("\n✅ Done!", flush=True)
