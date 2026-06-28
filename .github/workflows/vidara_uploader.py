import os
import sys
import time
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

VIDARA_API_KEY = os.environ.get("VIDARA_API_KEY", "")
VIDARA_API_BASE = "https://api.vidara.so/v1"

def get_upload_server():
    try:
        resp = requests.get(
            f"{VIDARA_API_BASE}/upload/server",
            params={"api_key": VIDARA_API_KEY},
            timeout=30
        )
        data = resp.json()
        if data.get("status") == 200:
            return data["result"]["upload_server"]
    except Exception as e:
        print(f"⚠️ Could not get upload server: {e}", flush=True)
    return None

def upload_to_temp_host(file_path):
    """
    Upload SRT to a public host and return direct URL.
    Tries multiple reliable hosts in order.
    """
    simple_name = "subtitle.srt"  # ✅ اسم إنجليزي ثابت
    size_kb = os.path.getsize(file_path) / 1024
    print(f"   📂 SRT size: {size_kb:.1f} KB", flush=True)

    # ── Host 1: tmpfiles.org ────────────────────────────
    try:
        print("   ↗ Trying tmpfiles.org...", flush=True)
        with open(file_path, "rb") as f:
            resp = requests.post(
                "https://tmpfiles.org/api/v1/upload",
                files={"file": (simple_name, f, "text/plain; charset=utf-8")},
                timeout=60
            )
        data = resp.json()
        if data.get("status") == "success":
            # tmpfiles returns https://tmpfiles.org/123/file.srt
            # direct link is https://tmpfiles.org/dl/123/file.srt
            url = data["data"]["url"].replace("tmpfiles.org/", "tmpfiles.org/dl/", 1)
            print(f"   ✅ tmpfiles.org → {url}", flush=True)
            return url
        print(f"   ⚠️ tmpfiles.org failed: {data}", flush=True)
    except Exception as e:
        print(f"   ⚠️ tmpfiles.org error: {e}", flush=True)

    # ── Host 2: pixeldrain.com ──────────────────────────
    try:
        print("   ↗ Trying pixeldrain.com...", flush=True)
        with open(file_path, "rb") as f:
            resp = requests.post(
                "https://pixeldrain.com/api/file",
                files={"file": (simple_name, f, "text/plain; charset=utf-8")},
                timeout=60
            )
        data = resp.json()
        if data.get("id"):
            url = f"https://pixeldrain.com/u/{data['id']}"
            print(f"   ✅ pixeldrain.com → {url}", flush=True)
            return url
        print(f"   ⚠️ pixeldrain.com failed: {data}", flush=True)
    except Exception as e:
        print(f"   ⚠️ pixeldrain.com error: {e}", flush=True)

    # ── Host 3: litterbox.catbox.moe ────────────────────
    try:
        print("   ↗ Trying litterbox.catbox.moe...", flush=True)
        with open(file_path, "rb") as f:
            resp = requests.post(
                "https://litterbox.catbox.moe/resources/internals/api.php",
                data={"reqtype": "fileupload", "time": "72h"},
                files={"fileToUpload": (simple_name, f, "text/plain; charset=utf-8")},
                timeout=120
            )
        if resp.status_code == 200 and resp.text.strip().startswith("http"):
            url = resp.text.strip()
            print(f"   ✅ litterbox.catbox.moe → {url}", flush=True)
            return url
        print(f"   ⚠️ litterbox failed: {resp.status_code} – {resp.text[:100]}", flush=True)
    except Exception as e:
        print(f"   ⚠️ litterbox error: {e}", flush=True)

    # ── Host 4: envs.sh ─────────────────────────────────
    try:
        print("   ↗ Trying envs.sh...", flush=True)
        with open(file_path, "rb") as f:
            resp = requests.post(
                "https://envs.sh",
                files={"file": (simple_name, f, "text/plain; charset=utf-8")},
                timeout=60
            )
        if resp.status_code == 200 and resp.text.strip().startswith("http"):
            url = resp.text.strip()
            print(f"   ✅ envs.sh → {url}", flush=True)
            return url
        print(f"   ⚠️ envs.sh failed: {resp.status_code} – {resp.text[:100]}", flush=True)
    except Exception as e:
        print(f"   ⚠️ envs.sh error: {e}", flush=True)

    # ── Host 5: file.io ─────────────────────────────────
    try:
        print("   ↗ Trying file.io...", flush=True)
        with open(file_path, "rb") as f:
            resp = requests.post(
                "https://file.io/?expires=3d",
                files={"file": (simple_name, f, "text/plain; charset=utf-8")},
                timeout=60
            )
        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("success") and data.get("link"):
                    url = data["link"]
                    print(f"   ✅ file.io → {url}", flush=True)
                    return url
            except:
                print(f"   ⚠️ file.io invalid JSON: {resp.text[:100]}", flush=True)
        else:
            print(f"   ⚠️ file.io failed: {resp.status_code} – {resp.text[:100]}", flush=True)
    except Exception as e:
        print(f"   ⚠️ file.io error: {e}", flush=True)

    print("   ❌ All temp hosts failed!", flush=True)
    return None

def upload_subtitle_to_vidara(filecode, srt_path, max_retries=3):
    """Upload SRT subtitle to vidara.so via /upload/sub endpoint with retry"""
    if not os.path.exists(srt_path):
        print(f"   ⚠️ SRT file not found: {srt_path}", flush=True)
        return False

    print(f"\n📝 Uploading subtitle to vidara.so...", flush=True)
    print(f"   Filecode: {filecode}", flush=True)

    # Step 1: Get a public direct URL for the SRT
    sub_url = upload_to_temp_host(srt_path)
    if not sub_url:
        print("   ❌ Cannot get public URL for subtitle — skipping", flush=True)
        return False

    # Step 2: Call vidara /upload/sub with retry
    for attempt in range(1, max_retries + 1):
        try:
            print(f"   → Calling vidara API (attempt {attempt}/{max_retries})...", flush=True)
            resp = requests.get(
                f"{VIDARA_API_BASE}/upload/sub",
                params={
                    "api_key": VIDARA_API_KEY,
                    "filecode": filecode,
                    "sub_lang": "Arabic",
                    "sub_url": sub_url,
                },
                timeout=60,
            )
            data = resp.json()
            print(f"   API response: {data}", flush=True)

            if data.get("status") == 200:
                print("   ✅ Subtitle attached to Vidara video!", flush=True)
                return True

            print(f"   ⚠️ Attempt {attempt} returned status: {data.get('status')} – {data}", flush=True)

        except Exception as e:
            print(f"   ❌ Attempt {attempt} exception: {e}", flush=True)

        if attempt < max_retries:
            wait = 5 * attempt  # 5s, 10s
            print(f"   ⏳ Retrying in {wait}s...", flush=True)
            time.sleep(wait)

    print("   ❌ All subtitle upload attempts failed", flush=True)
    return False

def upload_video_to_vidara(video_path, title="", srt_path=None):
    """Upload video to vidara.so via multipart upload, then attach subtitle"""
    if not VIDARA_API_KEY:
        print("❌ VIDARA_API_KEY not set", flush=True)
        return None

    if not os.path.exists(video_path):
        print(f"❌ Video file not found: {video_path}", flush=True)
        return None

    size_gb = os.path.getsize(video_path) / (1024 ** 3)
    print(f"\n📤 Uploading to vidara.so ({size_gb:.2f} GB)...", flush=True)

    upload_server = get_upload_server()
    if not upload_server:
        print("❌ No upload server available", flush=True)
        return None
    print(f"   Server: {upload_server}", flush=True)

    try:
        print("⬆️ Sending video file...", flush=True)
        with open(video_path, "rb") as f:
            files = {"file": ("video.mp4", f, "video/mp4")}  # ✅ اسم ثابت
            data = {"api_key": VIDARA_API_KEY}
            resp = requests.post(
                upload_server,
                data=data,
                files=files,
                timeout=3600,   # 1 hour for large files
                verify=False,
            )

        result = resp.json()
        print(f"   Upload response: {result}", flush=True)

        if not result or not result.get("filecode"):
            print(f"❌ Upload failed — no filecode in response: {result}", flush=True)
            return None

        raw_filecode = result["filecode"]
        if raw_filecode.startswith("http"):
            video_url = raw_filecode
            filecode_clean = raw_filecode.rstrip("/").split("/")[-1]
        else:
            video_url = result.get("url", f"https://vidara.so/v/{raw_filecode}")
            filecode_clean = raw_filecode

        print(f"✅ Video uploaded → filecode: {filecode_clean}", flush=True)
        print(f"   Watch URL: {video_url}", flush=True)

        # Attach subtitle if provided
        if srt_path and os.path.exists(srt_path):
            wait_sec = 15  # ✅ 15 ثانية بدل 3
            print(f"\n⏳ Waiting {wait_sec}s for Vidara to process the video...", flush=True)
            time.sleep(wait_sec)
            upload_subtitle_to_vidara(filecode_clean, srt_path)
        else:
            if srt_path:
                print(f"⚠️ SRT path given but file doesn't exist: {srt_path}", flush=True)
            else:
                print("ℹ️ No subtitle to upload", flush=True)

        return {
            "url": video_url,
            "filecode": filecode_clean,
            "title": result.get("title", title),
        }

    except Exception as e:
        print(f"❌ Upload error: {e}", flush=True)
        return None

# ── CLI entry point ────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python vidara_uploader.py <video_path> [title] [srt_path]")
        sys.exit(1)

    vp = sys.argv[1]
    ttl = sys.argv[2] if len(sys.argv) > 2 else ""
    sp = sys.argv[3] if len(sys.argv) > 3 else None

    res = upload_video_to_vidara(vp, ttl, sp)
    if res:
        print(f"\nSUCCESS: {res['url']}")
        sys.exit(0)
    else:
        print("\nFAILED")
        sys.exit(1)
