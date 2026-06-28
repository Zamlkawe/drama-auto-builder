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
                timeout=600,
                verify=False
            )

        result = resp.json()
        print(f"   Response: {result}", flush=True)

        # vidara.so returns: {"filecode": "https://vidara.to/e/...", "video_id": ..., "title": ...}
        if result and result.get("filecode"):
            filecode = result["filecode"]
            # filecode might be a full URL like "https://vidara.to/e/xxx" or just a code
            if filecode.startswith("http"):
                video_url = filecode
                # Extract actual filecode from URL if possible
                filecode_clean = filecode.split("/")[-1]
            else:
                video_url = f"https://vidara.so/{filecode}"
                filecode_clean = filecode

            print(f"✅ Video uploaded!", flush=True)
            print(f"   URL: {video_url}", flush=True)
            print(f"   Filecode: {filecode_clean}", flush=True)

            # Upload subtitle if provided
            if srt_path and os.path.exists(srt_path):
                upload_subtitle(filecode_clean, srt_path)

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


def upload_subtitle(filecode, srt_path):
    """Upload SRT subtitle to existing video"""
    # vidara.so upload/sub needs sub_url (direct URL), not a file path
    # We need to upload the SRT somewhere first, or use the upload API differently
    # For now, we skip subtitle upload to vidara since it requires a public URL
    print(f"\n📝 Note: Subtitle upload to vidara.so requires a public URL.", flush=True)
    print(f"   Subtitle file: {srt_path}", flush=True)
    print(f"   Skipping vidara subtitle upload (video uploaded successfully)", flush=True)
    return False


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
