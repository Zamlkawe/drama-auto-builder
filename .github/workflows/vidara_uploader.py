import json
import os
import sys
import time
import requests
import urllib3
import subprocess
import traceback

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


def upload_via_multipart(video_path, title=""):
    """محاولة الرفع المباشر على vidara.so (multipart)"""
    upload_server = get_upload_server()
    if not upload_server:
        print("❌ No upload server available", flush=True)
        return None
    
    print(f"📤 Upload server: {upload_server}", flush=True)
    
    try:
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
        
        if "url" in result and "filecode" in result:
            return result
        else:
            print(f"❌ Multipart upload failed: {result}", flush=True)
            return None
            
    except Exception as e:
        print(f"❌ Multipart upload error: {e}", flush=True)
        return None


def upload_to_gofile(video_path):
    """رفع الفيديو على GoFile.io وإرجاع الـ download URL"""
    print(f"\n☁️ Uploading to GoFile.io (temp host)...", flush=True)
    
    try:
        # 1. Upload file
        with open(video_path, "rb") as f:
            files = {"file": (os.path.basename(video_path), f, "video/mp4")}
            resp = requests.post(
                "https://store1.gofile.io/uploadFile",
                files=files,
                timeout=600
            )
        
        if resp.status_code != 200:
            print(f"❌ GoFile upload failed: HTTP {resp.status_code}", flush=True)
            return None
        
        data = resp.json()
        if data.get("status") != "ok":
            print(f"❌ GoFile upload failed: {data}", flush=True)
            return None
        
        content_id = data["data"]["parentFolderCode"]
        download_url = f"https://gofile.io/d/{content_id}"
        
        print(f"✅ GoFile upload: {download_url}", flush=True)
        return download_url
        
    except Exception as e:
        print(f"❌ GoFile error: {e}", flush=True)
        traceback.print_exc()
        return None


def upload_via_url(video_url, title=""):
    """رفع على vidara.so باستخدام upload_url endpoint"""
    print(f"\n📤 Sending URL to vidara.so: {video_url[:80]}...", flush=True)
    
    try:
        resp = requests.get(
            f"{VIDARA_API_BASE}/upload/url",
            params={
                "api_key": VIDARA_API_KEY,
                "url": video_url
            },
            timeout=120
        )
        
        data = resp.json()
        print(f"   Response: {data}", flush=True)
        
        if data.get("status") == 200:
            return {
                "url": f"https://vidara.so/{data['data']['filecode']}",
                "filecode": data["data"]["filecode"],
                "title": data["data"].get("title", title)
            }
        else:
            print(f"❌ upload_url failed: {data}", flush=True)
            return None
            
    except Exception as e:
        print(f"❌ upload_url error: {e}", flush=True)
        return None


def upload_subtitle_to_vidara(filecode, srt_path):
    """رفع الترجمة على vidara.so"""
    print(f"\n📝 Uploading subtitle to vidara.so...", flush=True)
    
    # vidara.so upload/sub بيحتاج sub_url (direct URL) مش file path
    # فلازم نرفع الـ SRT على GoFile الأول
    srt_url = upload_to_gofile(srt_path)
    
    if not srt_url:
        print("❌ Failed to upload subtitle to temp host", flush=True)
        return False
    
    try:
        resp = requests.get(
            f"{VIDARA_API_BASE}/upload/sub",
            params={
                "api_key": VIDARA_API_KEY,
                "filecode": filecode,
                "sub_lang": "English",
                "sub_url": srt_url
            },
            timeout=60
        )
        
        data = resp.json()
        if data.get("status") == 200:
            print(f"✅ Subtitle uploaded!", flush=True)
            return True
        else:
            print(f"⚠️ Subtitle upload: {data}", flush=True)
            return False
            
    except Exception as e:
        print(f"⚠️ Subtitle upload failed: {e}", flush=True)
        return False


def upload_video_to_vidara(video_path, title="", srt_path=None):
    """
    الرفع على vidara.so بأي طريقة متاحة:
    1. multipart upload (المباشرة)
    2. upload_url (عبر GoFile.io)
    """
    if not VIDARA_API_KEY:
        print("❌ VIDARA_API_KEY not set", flush=True)
        return None

    if not os.path.exists(video_path):
        print(f"❌ Video file not found: {video_path}", flush=True)
        return None

    print(f"\n📤 Uploading to vidara.so...", flush=True)
    print(f"   Video: {video_path}", flush=True)

    # المحاولة 1: Multipart upload (المباشرة)
    result = upload_via_multipart(video_path, title)
    
    # المحاولة 2: upload_url (عبر GoFile.io)
    if not result:
        print("\n⚠️ Multipart upload failed. Trying upload_url strategy...", flush=True)
        
        temp_url = upload_to_gofile(video_path)
        if temp_url:
            result = upload_via_url(temp_url, title)
        else:
            print("❌ Failed to upload to GoFile.io", flush=True)
            return None

    if not result:
        print("❌ All vidara upload methods failed", flush=True)
        return None

    # رفع الترجمة لو موجودة
    if srt_path and os.path.exists(srt_path) and result.get("filecode"):
        upload_subtitle_to_vidara(result["filecode"], srt_path)

    return result


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
