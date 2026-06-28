import json
import os
import sys
import time
import subprocess
import traceback

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

COOKIES_PATH = os.environ.get("RUMBLE_COOKIES", "cookies.json")
RUMBLE_EMAIL = os.environ.get("RUMBLE_EMAIL", "")
RUMBLE_PASSWORD = os.environ.get("RUMBLE_PASSWORD", "")

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def load_cookies(driver, cookies_path):
    with open(cookies_path, 'r') as f:
        cookies = json.load(f)
    
    driver.get("https://rumble.com")
    time.sleep(2)
    
    for cookie in cookies:
        try:
            driver.add_cookie({
                'name': cookie['name'],
                'value': cookie['value'],
                'domain': cookie.get('domain', '.rumble.com'),
                'path': cookie.get('path', '/'),
                'secure': cookie.get('secure', True),
                'httpOnly': cookie.get('httpOnly', False)
            })
        except Exception as e:
            print(f"⚠️ Failed to add cookie {cookie['name']}: {e}")
    
    driver.refresh()
    time.sleep(3)

def check_login(driver):
    try:
        driver.get("https://rumble.com")
        time.sleep(3)
        
        # Check if logged in by looking for user menu or upload button
        upload_btn = driver.find_elements(By.CSS_SELECTOR, 'a[href="/upload"], .upload-button, [data-testid="upload"]')
        user_menu = driver.find_elements(By.CSS_SELECTOR, '.user-menu, .avatar, [data-testid="user-menu"]')
        
        if upload_btn or user_menu:
            print("✅ Logged in successfully via cookies")
            return True
        
        # Check for login button (not logged in)
        login_btn = driver.find_elements(By.CSS_SELECTOR, 'a[href="/login"], .login-button')
        if login_btn:
            print("⚠️ Not logged in. Cookies may be expired.")
            return False
            
        return False
    except Exception as e:
        print(f"⚠️ Error checking login: {e}")
        return False

def login_with_credentials(driver, email, password):
    try:
        driver.get("https://rumble.com/login")
        time.sleep(3)
        
        email_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="email"], input[name="email"], #email'))
        )
        email_field.send_keys(email)
        
        password_field = driver.find_element(By.CSS_SELECTOR, 'input[type="password"], input[name="password"], #password')
        password_field.send_keys(password)
        
        submit_btn = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], .login-submit, input[type="submit"]')
        submit_btn.click()
        
        time.sleep(5)
        
        # Check if login successful
        if check_login(driver):
            print("✅ Logged in with credentials")
            return True
        return False
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return False

def upload_to_rumble(driver, video_path, title, description="", srt_path=None):
    try:
        # Go to upload page
        driver.get("https://rumble.com/upload")
        time.sleep(5)
        
        # Check if we're on upload page
        if "upload" not in driver.current_url:
            print("❌ Not on upload page. May need to login.")
            return None
        
        # Upload video file
        print(f"📤 Uploading video: {video_path}")
        file_input = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"], .file-input, [data-testid="file-input"]'))
        )
        file_input.send_keys(os.path.abspath(video_path))
        
        # Wait for upload to start
        time.sleep(5)
        
        # Fill title
        title_field = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="title"], #title, .title-input, textarea[name="title"]'))
        )
        title_field.clear()
        title_field.send_keys(title)
        
        # Fill description if field exists
        try:
            desc_field = driver.find_element(By.CSS_SELECTOR, 'textarea[name="description"], #description, .description-input')
            desc_field.clear()
            desc_field.send_keys(description)
        except:
            pass
        
        # Upload SRT if provided
        if srt_path and os.path.exists(srt_path):
            print(f"📤 Uploading subtitle: {srt_path}")
            try:
                # Look for subtitle/caption upload
                sub_input = driver.find_element(By.CSS_SELECTOR, 'input[type="file"][accept=".srt,.vtt"], .subtitle-input, [data-testid="subtitle-upload"]')
                sub_input.send_keys(os.path.abspath(srt_path))
                time.sleep(3)
            except Exception as e:
                print(f"⚠️ Could not upload subtitle: {e}")
        
        # Submit/Publish
        submit_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[type="submit"], .publish-btn, .submit-btn, [data-testid="publish"]'))
        )
        submit_btn.click()
        
        # Wait for processing
        print("⏳ Waiting for upload to complete...")
        time.sleep(10)
        
        # Get video URL
        current_url = driver.current_url
        if "/v/" in current_url or "/c/" in current_url:
            print(f"✅ Upload successful! URL: {current_url}")
            return current_url
        
        # Try to find video link on page
        links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/v/"], a[href*="/c/"]')
        for link in links:
            href = link.get_attribute('href')
            if href:
                print(f"✅ Video URL: {href}")
                return href
        
        return current_url
        
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        traceback.print_exc()
        return None

def upload_video_to_rumble(video_path, title, description="", srt_path=None):
    driver = None
    try:
        driver = setup_driver()
        
        # Try cookies first
        if os.path.exists(COOKIES_PATH):
            load_cookies(driver, COOKIES_PATH)
            if check_login(driver):
                return upload_to_rumble(driver, video_path, title, description, srt_path)
        
        # Fallback to credentials
        if RUMBLE_EMAIL and RUMBLE_PASSWORD:
            if login_with_credentials(driver, RUMBLE_EMAIL, RUMBLE_PASSWORD):
                return upload_to_rumble(driver, video_path, title, description, srt_path)
        
        print("❌ Could not login to Rumble")
        return None
        
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()
        return None
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python rumble_uploader.py <video_path> <title> [description] [srt_path]")
        sys.exit(1)
    
    video_path = sys.argv[1]
    title = sys.argv[2]
    description = sys.argv[3] if len(sys.argv) > 3 else ""
    srt_path = sys.argv[4] if len(sys.argv) > 4 else None
    
    result = upload_video_to_rumble(video_path, title, description, srt_path)
    if result:
        print(f"SUCCESS: {result}")
        sys.exit(0)
    else:
        print("FAILED")
        sys.exit(1)
