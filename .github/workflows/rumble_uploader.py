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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TELEGRAM_TOKEN       = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID              = os.environ.get("TELEGRAM_CHAT_ID")
GDRIVE_CLIENT_ID     = os.environ.get("GDRIVE_CLIENT_ID")
GDRIVE_CLIENT_SECRET = os.environ.get("GDRIVE_CLIENT_SECRET")
GDRIVE_REFRESH_TOKEN = os.environ.get("GDRIVE_REFRESH_TOKEN")
GDRIVE_FOLDER_ID     = os.environ.get("GDRIVE_FOLDER_ID")
UPLOAD_TARGET        = os.environ.get("UPLOAD_TARGET", "gdrive").lower()

TEMP_DIR = "/tmp/drama_videos"
os.makedirs(TEMP_DIR, exist_ok=True)


# ── Telegram Helper ────────────────────────────────────────────────

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


def safe_delete(filepath):
    for _ in range(5):
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                return True
        except:
            time.sleep(1)
    return False


# ── Subtitle Helpers ─────────────────────────────────────────────

def normalize_subtitles(text):
    if not text:
        return ""
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
            if in_block and current_block_lines:
                srt_blocks.append((start_ts, end_ts, current_block_lines))
                in_block = False
                current_block_lines = []
            continue

        upper = line.upper()
        if upper.startswith(('WEBVTT', 'REGION', 'STYLE', 'X-TIMESTAMP-MAP')):
            continue
        if line in ('::cue {', '}'):
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
            clean = re.sub(r'<[^>]+>', '', line)
            clean = re.sub(r'\[font.*?\]', '', clean, flags=re.IGNORECASE)
            if clean.strip():
                current_block_lines.append(clean.strip())

    if in_block and current_block_lines:
        srt_blocks.append((start_ts, end_ts, current_block_lines))

    output = []
    for i, (start, end, text_lines) in enumerate(srt_blocks, 1):
        if text_lines:
            output.extend([str(i), f"{start} --> {end}"] + text_lines + [""])

    return "\n".join(output).strip()


def merge_subtitles(temp_dir, subtitle_map, total_eps, movie_name):
    merged_path = f"/tmp/{movie_name}_Full_Movie.srt"
    cum_offset_ms = 0
    global_index = 1
    all_entries = []

    def ts_to_ms(ts):
        p = ts.replace(',', '.').split(':')
        if len(p) == 2:
            return int((int(p[0]) * 60 + float(p[1])) * 1000)
        elif len(p) >= 3:
            return int((int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])) * 1000)
        return 0

    def ms_to_srt(ms):
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, mi = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{mi:03d}"

    for ep in range(1, total_eps + 1):
        srt_path = os.path.join(temp_dir, f"ep_{ep:04d}.srt")

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

        if not os.path.exists(srt_path):
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
                    end_text_idx = content.rfind('\n', start_text_idx, matches[i + 1].start())
                    if end_text_idx <= start_text_idx:
                        end_text_idx = matches[i + 1].start()
                else:
                    end_text_idx = len(content)

                raw_text = content[start_text_idx:end_text_idx].strip()
                text_lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
                if text_lines and text_lines[-1].isdigit():
                    text_lines = text_lines[:-1]

                clean_text = '\n'.join(text_lines).strip()
                if clean_text:
                    all_entries.append('\n'.join([
                        str(global_index),
                        f"{ms_to_srt(s_ms)} --> {ms_to_srt(e_ms)}",
                        clean_text
                    ]))
                    global_index += 1
        except Exception as e:
            print(f"⚠️ Error parsing subtitle Ep{ep:02d}: {e}", flush=True)

        cum_offset_ms += dur_ms

    if all_entries:
        with open(merged_path, "w", encoding="utf-8") as f:
            f.write('\n\n'.join(all_entries))
        return merged_path

    return None


# ── Download Helpers ─────────────────────────────────────────────

def download_with_ytdlp(url, output_path, ep_num):
    """تحميل باستخدام yt-dlp للـ HLS/m3u8"""
    try:
        cmd = [
            "yt-dlp",
            "-o", output_path,
            "--no-part", "--no-mtime",
            "--quiet", "--no-warnings",
            "--no-check-certificate",
            "--retries", "10",
            "--fragment-retries", "10",
            "--retry-sleep", "1..3",
            url
        ]
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

    if not url or "http" not in str(url):
        print(f"⏭ Skipping episode {ep_num}: invalid url", flush=True)
        return None

    try:
        ep_num_int = int(ep_num)
    except:
        print(f"⏭ Skipping episode {ep_num}: invalid number", flush=True)
        return None

    video_path = os.path.join(temp_dir, f"ep_{ep_num_int:04d}.mp4")
    srt_path = os.path.join(temp_dir, f"ep_{ep_num_int:04d}.srt")

    # ✅ إعادة المحاولة حتى 5 مرات
    for attempt in range(5):
        try:
            print(f"⬇️ Downloading episode {ep_num} (attempt {attempt + 1})...", flush=True)

            # ✅ محاولة yt-dlp أولاً (للـ HLS/m3u8)
            if ".m3u8" in url or ".mp4" not in url.split("?")[0]:
                ydl_success = download_with_ytdlp(url, video_path, ep_num)
                if ydl_success:
                    break

            # ✅ fallback لـ requests
            r = requests.get(url, stream=True, verify=False, timeout=120)
            r.raise_for_status()

            with open(video_path, "wb") as out:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        out.write(chunk)
            break

        except Exception as e:
            print(f"⚠️ Attempt {attempt + 1} failed for ep {ep_num}: {e}", flush=True)
            safe_delete(video_path)
            if attempt < 4:
                time.sleep(2 ** attempt)  # exponential backoff
            else:
                print(f"❌ All attempts failed for ep {ep_num}", flush=True)
                return None

    if not os.path.exists(video_path) or os.path.getsize(video_path) < 10000:
        return None

    size_mb = os.path.getsize(video_path) / (1024 * 1024)
    print(f"✅ Episode {ep_num} downloaded ({size_mb:.1f} MB)", flush=True)

    # ✅ تحميل الترجمة
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

    return {"ep": ep_num_int, "path": video_path}


# ── Rumble Upload Helper ───────────────────────────────────────────

def upload_to_rumble(video_path, title, description, srt_path=None):
    """
    Upload video to Rumble using Selenium with cookies.
    Returns video URL or None.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
    except ImportError:
        print("❌ selenium not installed", flush=True)
        return None

    driver = None
    rumble_url = None

    try:
        print("\n📺 Starting Rumble upload...", flush=True)
        print(f"   Video: {video_path}", flush=True)
        print(f"   Title: {title}", flush=True)

        # Setup Chrome options
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-plugins")
        chrome_options.add_argument("--no-first-run")
        chrome_options.add_argument("--no-default-browser-check")
        chrome_options.add_argument("--password-store=basic")
        chrome_options.add_argument("--use-mock-keychain")
        chrome_options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        # Create driver
        try:
            driver = webdriver.Chrome(options=chrome_options)
        except Exception:
            from selenium.webdriver.chrome.service import Service
            service = Service('/usr/bin/chromedriver')
            driver = webdriver.Chrome(service=service, options=chrome_options)

        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # Load cookies
        cookies_path = "/tmp/cookies.json"
        if os.path.exists(cookies_path):
            print("🍪 Loading cookies...", flush=True)
            with open(cookies_path, 'r', encoding='utf-8') as f:
                cookies = json.load(f)

            driver.get("https://rumble.com")
            time.sleep(2)

            for cookie in cookies:
                try:
                    cookie_dict = {
                        'name': cookie['name'],
                        'value': cookie['value'],
                        'domain': cookie.get('domain', '.rumble.com'),
                        'path': cookie.get('path', '/'),
                        'secure': cookie.get('secure', True),
                    }
                    if 'httpOnly' in cookie:
                        cookie_dict['httpOnly'] = cookie['httpOnly']
                    driver.add_cookie(cookie_dict)
                except Exception as e:
                    print(f"⚠️ Cookie {cookie.get('name')}: {e}", flush=True)

            driver.refresh()
            time.sleep(3)

        # Check login
        print("🔍 Checking login status...", flush=True)
        driver.get("https://rumble.com")
        time.sleep(3)

        logged_in = False
        login_indicators = [
            'a[href="/upload"]',
            '.upload-button',
            '[data-testid="upload"]',
            '.user-avatar',
            '.avatar',
            '[data-testid="user-menu"]',
            '.header-user-menu',
        ]

        for selector in login_indicators:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements and any(e.is_displayed() for e in elements):
                    logged_in = True
                    print(f"✅ Logged in (found: {selector})", flush=True)
                    break
            except:
                continue

        if not logged_in:
            page_source = driver.page_source.lower()
            if 'logout' in page_source or 'my account' in page_source or 'dashboard' in page_source:
                logged_in = True
                print("✅ Logged in (page source)", flush=True)

        if not logged_in:
            print("❌ Not logged in. Cookies may be expired.", flush=True)
            return None

        # Go to upload page
        print("📤 Navigating to upload page...", flush=True)
        driver.get("https://rumble.com/upload")
        time.sleep(5)

        # Upload video file
        print("📁 Uploading video file...", flush=True)
        abs_video_path = os.path.abspath(video_path)

        # Try multiple selectors for file input
        file_input = None
        file_selectors = [
            'input[type="file"]',
            '.file-input',
            '[data-testid="file-input"]',
            'input[name="video"]',
            'input[name="file"]',
        ]

        for selector in file_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    if el.is_displayed() or el.get_attribute('type') == 'file':
                        file_input = el
                        break
                if file_input:
                    break
            except:
                continue

        if not file_input:
            # Try JavaScript
            file_input = driver.execute_script("""
                return document.querySelector('input[type="file"]');
            """)

        if file_input:
            file_input.send_keys(abs_video_path)
            print(f"✅ Video file sent", flush=True)
        else:
            print("❌ Cannot find file input", flush=True)
            return None

        # Wait for upload
        print("⏳ Waiting for upload to process...", flush=True)
        time.sleep(15)

        # Wait for title field to appear
        max_wait = 300
        waited = 0
        while waited < max_wait:
            try:
                title_field = driver.find_element(By.CSS_SELECTOR,
                    'input[name="title"], #title, .title-input, textarea[name="title"]')
                if title_field.is_displayed():
                    print("✅ Upload form ready", flush=True)
                    break
            except:
                pass

            # Check for errors
            try:
                error_elements = driver.find_elements(By.CSS_SELECTOR, '.error, .alert-error, .upload-error')
                if error_elements:
                    error_text = error_elements[0].text
                    print(f"❌ Upload error: {error_text}", flush=True)
                    return None
            except:
                pass

            time.sleep(5)
            waited += 5
            if waited % 30 == 0:
                print(f"   Still uploading... ({waited}s)", flush=True)

        # Fill title
        print("📝 Filling title...", flush=True)
        try:
            title_field = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    'input[name="title"], #title, .title-input, textarea[name="title"]'))
            )
            title_field.clear()
            title_field.send_keys(title)
        except Exception as e:
            print(f"⚠️ Title field issue: {e}", flush=True)

        # Fill description
        if description:
            print("📝 Filling description...", flush=True)
            try:
                desc_field = driver.find_element(By.CSS_SELECTOR,
                    'textarea[name="description"], #description, .description-input, textarea[placeholder*="description" i]')
                desc_field.clear()
                desc_field.send_keys(description)
            except Exception as e:
                print(f"⚠️ Description field issue: {e}", flush=True)

        # Upload SRT if provided
        if srt_path and os.path.exists(srt_path):
            print("📝 Uploading SRT subtitle...", flush=True)
            try:
                sub_selectors = [
                    'input[type="file"][accept*=".srt"]',
                    'input[type="file"][accept*=".vtt"]',
                    '.subtitle-input',
                    '[data-testid="subtitle-upload"]',
                    'input[name="subtitle"]',
                ]

                sub_input = None
                for selector in sub_selectors:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        sub_input = elements[0]
                        break

                if sub_input:
                    sub_input.send_keys(os.path.abspath(srt_path))
                    print("✅ SRT uploaded", flush=True)
                    time.sleep(2)
                else:
                    # Try clicking "Add captions" button
                    try:
                        caption_btns = driver.find_elements(By.XPATH,
                            "//button[contains(text(), 'caption') or contains(text(), 'subtitle') or contains(text(), 'CC')]")
                        if caption_btns:
                            caption_btns[0].click()
                            time.sleep(2)
                            sub_input = driver.find_element(By.CSS_SELECTOR, 'input[type="file"]')
                            sub_input.send_keys(os.path.abspath(srt_path))
                            print("✅ SRT uploaded via caption button", flush=True)
                    except:
                        print("⚠️ No subtitle upload found", flush=True)
            except Exception as e:
                print(f"⚠️ SRT upload issue: {e}", flush=True)

        # Submit/Publish
        print("🚀 Publishing...", flush=True)
        submit_selectors = [
            'button[type="submit"]',
            '.publish-btn',
            '.submit-btn',
            '[data-testid="publish"]',
            '.btn-primary[type="submit"]',
        ]

        submit_btn = None
        for selector in submit_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    if el.is_displayed() and el.is_enabled():
                        submit_btn = el
                        break
                if submit_btn:
                    break
            except:
                continue

        if submit_btn:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
            time.sleep(1)
            submit_btn.click()
            print("✅ Publish clicked", flush=True)
        else:
            # Try JavaScript
            driver.execute_script("""
                var btns = document.querySelectorAll('button[type="submit"], .publish-btn, .btn-primary');
                for(var i=0; i<btns.length; i++) {
                    if(btns[i].offsetParent !== null) { btns[i].click(); break; }
                }
            """)

        # Wait for processing
        print("⏳ Waiting for processing...", flush=True)
        time.sleep(20)

        # Get video URL
        current_url = driver.current_url
        print(f"📍 Current URL: {current_url}", flush=True)

        if "/v/" in current_url or "/c/" in current_url:
            rumble_url = current_url
            print(f"✅ Video URL: {rumble_url}", flush=True)
        else:
            # Try to find video link
            try:
                video_links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/v/"], a[href*="/c/"]')
                for link in video_links:
                    href = link.get_attribute('href')
                    if href:
                        rumble_url = href
                        print(f"✅ Video URL: {rumble_url}", flush=True)
                        break
            except:
                pass

            if not rumble_url:
                rumble_url = current_url

        return rumble_url

    except Exception as e:
        print(f"❌ Rumble upload error: {e}", flush=True)
        traceback.print_exc()
        return None
    finally:
        if driver:
            print("🧹 Closing browser...", flush=True)
            try:
                driver.quit()
            except:
                pass


# ── Google Drive Upload ────────────────────────────────────────────

def upload_to_gdrive(final_output, merged_srt, movie_name, data, downloaded_count, output_size):
    """Upload to Google Drive"""
    print("\n☁️ Starting Google Drive upload...", flush=True)

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    try:
        creds = Credentials(
            None,
            refresh_token=GDRIVE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GDRIVE_CLIENT_ID,
            client_secret=GDRIVE_CLIENT_SECRET,
            scopes=["https://www.googleapis.com/auth/drive"]
        )

        creds.refresh(Request())
        service = build("drive", "v3", credentials=creds)

        # رفع الفيديو
        file_metadata = {
            "name": f"{movie_name}_Full_Movie.mp4",
            "parents": [GDRIVE_FOLDER_ID]
        }

        media = MediaFileUpload(final_output, mimetype="video/mp4", resumable=True, chunksize=10 * 1024 * 1024)
        uploaded = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink, name").execute()
        video_id = uploaded.get("id")

        # رفع الترجمة
        srt_link = None
        if merged_srt and os.path.exists(merged_srt):
            srt_metadata = {"name": f"{movie_name}_Full_Movie.srt", "parents": [GDRIVE_FOLDER_ID]}
            srt_media = MediaFileUpload(merged_srt, mimetype="application/x-subrip", resumable=True)
            srt_uploaded = service.files().create(body=srt_metadata, media_body=srt_media, fields="id, webViewLink").execute()
            srt_link = f"https://drive.google.com/file/d/{srt_uploaded.get('id')}/view"

        # صلاحية Public
        service.permissions().create(fileId=video_id, body={"type": "anyone", "role": "reader"}).execute()

        drive_link = uploaded.get("webViewLink") or f"https://drive.google.com/file/d/{video_id}/view"

        msg = f"🎉 *اكتمل الدمج والرفع بنجاح!*\n\n🎬 *{data.get('series_title', 'Unknown')}*\n📦 الحلقات: {downloaded_count}\n📁 الحجم: {output_size:.0f} MB"
        if srt_link:
            msg += f"\n📝 [ملف الترجمة]({srt_link})"
        msg += f"\n\n🔗 [رابط المشاهدة]({drive_link})"

        send_telegram(msg)
        print(f"🔗 Drive link: {drive_link}", flush=True)
        return drive_link

    except Exception as e:
        traceback.print_exc()
        fail(f"فشل الرفع على Google Drive:\n{str(e)[:1000]}")
        return None


# ── MAIN ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    # ── التحقق من المدخلات ──────────────────────────────────────

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
    print(f"✅ UPLOAD_TARGET = {UPLOAD_TARGET}", flush=True)

    # ── قراءة الـ JSON ──────────────────────────────────────────

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
        f"📦 الحلقات: {len(episodes)}\n"
        f"📤 الوجهة: *{'Rumble' if UPLOAD_TARGET == 'rumble' else 'Google Drive'}*"
    )

    # ── تحميل الحلقات (متوازي) ──────────────────────────────────

    subtitle_map = {}

    print("\n🚀 Starting parallel downloads (max 10 workers)...", flush=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(download_episode, ep, TEMP_DIR, subtitle_map): ep for ep in episodes}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    results.sort(key=lambda x: x["ep"])
    downloaded_count = len(results)

    if downloaded_count == 0:
        fail("فشل تحميل كل الحلقات. لا يوجد شيء لدمجه.")

    # إنشاء list file
    with open(list_file, "w", encoding="utf-8") as f:
        for r in results:
            f.write(f"file '{r['path']}'\n")

    print(f"\n✅ Downloaded {downloaded_count}/{len(episodes)} episodes", flush=True)
    if subtitle_map:
        print(f"📝 Downloaded {len(subtitle_map)} subtitle files", flush=True)

    send_telegram(f"⏳ اكتمل التحميل ({downloaded_count} حلقة)، جاري الدمج بـ FFmpeg...")

    # ── دمج الترجمات ────────────────────────────────────────────

    merged_srt = None
    if subtitle_map:
        print("\n📝 Merging subtitles...", flush=True)
        merged_srt = merge_subtitles(TEMP_DIR, subtitle_map, downloaded_count, movie_name)
        if merged_srt and os.path.exists(merged_srt):
            print(f"✅ Merged subtitle: {merged_srt}", flush=True)

    # ── دمج الفيديوهات (TS method) ──────────────────────────────

    print("\n🔀 Starting FFmpeg merge...", flush=True)

    # تحويل لـ TS
    ts_files = []
    for r in results:
        ep = r["ep"]
        mp4_path = r["path"]
        ts_path = os.path.join(TEMP_DIR, f"ep_{ep:04d}.ts")

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

    # دمج الـ TS
    if len(ts_files) >= 2:
        ts_list_file = "/tmp/ts_list.txt"
        with open(ts_list_file, "w", encoding="utf-8") as f:
            for tsf in ts_files:
                f.write(f"file '{tsf}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-fflags", "+genpts",
            "-f", "concat", "-safe", "0",
            "-i", ts_list_file,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart",
            final_output
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
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

    # تنظيف TS files
    for tsf in ts_files:
        safe_delete(tsf)

    output_size = os.path.getsize(final_output) / (1024 * 1024)
    print(f"✅ Merged file: {final_output} ({output_size:.1f} MB)", flush=True)

    # ── الرفع ────────────────────────────────────────────────────

    if UPLOAD_TARGET == "rumble":
        # رفع على Rumble
        rumble_title = data.get('series_title', 'Video')
        rumble_desc = f"Full series: {rumble_title}\nEpisodes: {downloaded_count}"

        rumble_url = upload_to_rumble(final_output, rumble_title, rumble_desc, merged_srt)

        if rumble_url:
            msg = f"🎉 *رفع على Rumble بنجاح!*\n\n🎬 *{data.get('series_title', 'Unknown')}*\n📦 الحلقات: {downloaded_count}\n📁 الحجم: {output_size:.0f} MB"
            if merged_srt and os.path.exists(merged_srt):
                msg += "\n📝 ملف الترجمة مرفق"
            msg += f"\n\n🔗 [رابط Rumble]({rumble_url})"
            send_telegram(msg)
            print(f"🔗 Rumble link: {rumble_url}", flush=True)
        else:
            # Fallback to Google Drive if Rumble fails
            print("⚠️ Rumble upload failed, falling back to Google Drive...", flush=True)
            send_telegram("⚠️ فشل الرفع على Rumble، جاري الرفع على Google Drive...")
            upload_to_gdrive(final_output, merged_srt, movie_name, data, downloaded_count, output_size)
    else:
        # رفع على Google Drive
        upload_to_gdrive(final_output, merged_srt, movie_name, data, downloaded_count, output_size)

    # ── تنظيف ────────────────────────────────────────────────────
    print("\n🧹 Cleaning up...", flush=True)
    for r in results:
        safe_delete(r["path"])
    safe_delete(final_output)
    safe_delete(merged_srt)
    safe_delete(list_file)
    safe_delete("/tmp/ts_list.txt")

    print("\n✅ Done!", flush=True)
