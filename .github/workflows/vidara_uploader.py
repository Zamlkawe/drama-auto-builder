import json
import os
import sys
import time
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

VIDARA_API_KEY = os.environ.get("VIDARA_API_KEY", "")
VIDARA_UPLOAD_SERVER = "https://s1.vidara.so/api/upload"
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

    return VIDARA_UPLOAD_SERVER


def upload_video_to_vidara(video_path, title="", srt_path=None):
    """
    Upload video to vidara.so via API

    Args:
        video_path: Path to video file
        title: Video title (optional)
        srt_path: Path to SRT subtitle file (optional)

    Returns:
        dict: {url, filecode, title} or None
    """
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
                timeout=300,
                verify=False
            )

        result = resp.json()
        print(f"   Response: {result}", flush=True)

        if "url" not in result or "filecode" not in result:
            print(f"❌ Upload failed: {result}", flush=True)
            return None

        filecode = result["filecode"]
        video_url = result["url"]

        print(f"✅ Video uploaded!", flush=True)
        print(f"   URL: {video_url}", flush=True)
        print(f"   Filecode: {filecode}", flush=True)

        # Upload subtitle if provided
        if srt_path and os.path.exists(srt_path):
            print(f"\n📝 Uploading subtitle...", flush=True)
            upload_subtitle(filecode, srt_path)

        return {
            "url": video_url,
            "filecode": filecode,
            "title": result.get("title", title)
        }

    except Exception as e:
        print(f"❌ Upload error: {e}", flush=True)
        return None


def upload_subtitle(filecode, srt_path):
    """Upload SRT subtitle to existing video"""
    try:
        # Upload subtitle file to a temporary host first
        # vidara needs a URL, not a file path
        # We'll use the file directly if the API supports it

        # Actually, vidara API needs sub_url (direct URL)
        # We need to upload the SRT somewhere first, or use the upload API differently

        # Alternative: upload SRT as a file using multipart
        with open(srt_path, "rb") as f:
            files = {"file": (os.path.basename(srt_path), f, "application/x-subrip")}
            data = {
                "api_key": VIDARA_API_KEY,
                "filecode": filecode,
                "sub_lang": "English"
            }

            resp = requests.post(
                f"{VIDARA_API_BASE}/upload/sub",
                data=data,
                files=files,
                timeout=60,
                verify=False
            )

        result = resp.json()
        if result.get("status") == 200:
            print(f"✅ Subtitle uploaded!", flush=True)
        else:
            print(f"⚠️ Subtitle upload: {result}", flush=True)

    except Exception as e:
        print(f"⚠️ Subtitle upload failed: {e}", flush=True)


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
