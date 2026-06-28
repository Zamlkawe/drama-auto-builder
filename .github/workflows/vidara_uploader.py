import json
import os
import sys
import time
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

VIDARA_API_KEY = os.environ.get("VIDARA_API_KEY", "")
VIDARA_API_BASE = "https://api.vidara.so/v1"


def get_upload_server():
    """Get the current upload server URL"""
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
    """Upload a file to catbox.moe and return the direct download URL"""
    try:
        with open(file_path, "rb") as f:
            files = {"fileToUpload": (os.path.basename(file_path), f)}
            data = {"reqtype": "fileupload"}
            # استخدام catbox لضمان الحصول على رابط مباشر 100% للـ SRT
            resp = requests.post(
                "https://catbox.moe/user/api.php",
                data=data,
                files=files,
                timeout=120
            )

        if resp.status_code == 200 and resp.text.startswith("http"):
            url = resp.text.strip()
            print(f"   ✅ Temp URL: {url}", flush=True)
            return url
        else:
            print(f"   ❌ Temp upload failed. Status: {resp.status_code}, Response: {resp.text}", flush=True)
    except Exception as e:
        print(f"   ❌ Temp upload exception: {e}", flush=True)
    return None


def upload_subtitle_to_vidara(filecode, srt_path):
    """Upload SRT subtitle to vidara.so via upload/sub endpoint"""
    if not os.path.exists(srt_path):
        print(f"   ⚠️ Subtitle file not found: {srt_path}", flush=True)
        return False

    print(f"\n📝 Uploading subtitle to vidara.so...", flush=True)
    print(f"   File: {srt_path}", flush=True)

    # Step 1: Upload SRT to get a direct public URL
    print(f"   Step 1: Uploading to temporary direct-link host...", flush=True)
    sub_url = upload_to_temp_host(srt_path)

    if not sub_url:
        print(f"   ❌ Failed to get public URL for subtitle", flush=True)
        return False

    # Step 2: Send URL to vidara.so upload/sub
    print(f"   Step 2: Sending URL to vidara.so API...", flush=True)
    try:
        resp = requests.get(
            f"{VIDARA_API_BASE}/upload/sub",
            params={
                "api_key": VIDARA_API_KEY,
                "filecode": filecode,
                "sub_lang": "Arabic", # تم التعديل لتظهر الترجمة كعربية
                "sub_url": sub_url
            },
            timeout=60
        )

        data = resp.json()
        print(f"   Response: {data}", flush=True)

        if data.get("status") == 200:
            print(f"   ✅ Subtitle uploaded successfully to Vidara!", flush=True)
            return True
        else:
            print(f"   ⚠️ Subtitle upload returned error: {data}", flush=True)
            return False

    except Exception as e:
        print(f"   ❌ Subtitle upload failed: {e}", flush=True)
        return False


def upload_video_to_vidara(video_path, title="", srt_path=None):
    """Upload video to vidara.so via multipart upload"""
    if not VIDARA_API_KEY:
        print("❌ VIDARA_API_KEY not set", flush=True)
        return None

    if not os.path.exists(video_path):
        print(f"❌ Video file not found: {video_path}", flush=True)
        return None

    print(f"\n📤 Uploading to vidara.so...", flush=True)
    print(f"   Video: {video_path}", flush=True)

    # Get upload server
    upload_server = get_upload_server()
    if not upload_server:
        print("❌ No upload server available", flush=True)
        return None

    print(f"   Upload server: {upload_server}", flush=True)

    # Upload video
    try:
        print(f"⬆️ Uploading video file...", flush=True)

        with open(video_path, "rb") as f:
            files = {"file": (os.path.basename(video_path), f, "video/mp4")}
            data = {"api_key": VIDARA_API_KEY}

            resp = requests.post(
                upload_server,
                data=data,
                files=files,
                timeout=1200, # زيادة وقت الـ Timeout للملفات الكبيرة
                verify=False
            )

        result = resp.json()
        print(f"   Response: {result}", flush=True)

        if result and result.get("filecode"):
            filecode = result["filecode"]
            if filecode.startswith("http"):
                video_url = filecode
                filecode_clean = filecode.split("/")[-1]
            else:
                video_url = result.get("url", f"https://vidara.so/v/{filecode}")
                filecode_clean = filecode

            print(f"✅ Video uploaded!", flush=True)
            print(f"   URL: {video_url}", flush=True)
            print(f"   Filecode: {filecode_clean}", flush=True)

            # Upload subtitle if provided
            if srt_path and os.path.exists(srt_path):
                # تأخير 3 ثواني لضمان تسجيل الفيديو في قاعدة بيانات Vidara قبل رفع الترجمة
                time.sleep(3) 
                upload_subtitle_to_vidara(filecode_clean, srt_path)

            return {
                "url": video_url,
                "filecode": filecode_clean,
                "title": result.get("title", title)
            }
        else:
            print(f"❌ Upload failed: {result}", flush=True)
            return None

    except Exception as e:
        print(f"❌ Upload error: {e}", flush=True)
        return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python vidara_uploader.py <video_path> [title] [srt_path]")
        sys.exit(1)

    video_path = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else ""
    srt_path = sys.argv[3] if len(sys.argv) > 3 else None

    result = upload_video_to_vidara(video_path, title, srt_path)

    if result:
        print(f"\nSUCCESS: {result['url']}")
        sys.exit(0)
    else:
        print("\nFAILED")
        sys.exit(1)
