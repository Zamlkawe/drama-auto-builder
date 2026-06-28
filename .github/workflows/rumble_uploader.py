import json
import os
import sys
import time
import traceback

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains

# ── Configuration ──────────────────────────────────────────────────

COOKIES_PATH = os.environ.get("RUMBLE_COOKIES_PATH", "/tmp/cookies.json")
RUMBLE_EMAIL = os.environ.get("RUMBLE_EMAIL", "")
RUMBLE_PASSWORD = os.environ.get("RUMBLE_PASSWORD", "")

# ── Chrome Setup for GitHub Actions ────────────────────────────────

def setup_driver():
    """Setup Chrome driver for headless environment (GitHub Actions)"""
    chrome_options = Options()

    # Essential headless options
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
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--disable-features=IsolateOrigins,site-per-process")

    # User agent to avoid detection
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )

    # Disable automation flags
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    # Create driver
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return driver
    except Exception as e:
        print(f"❌ Failed to create Chrome driver: {e}")
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            return driver
        except Exception as e2:
            print(f"❌ webdriver-manager also failed: {e2}")
            raise

# ── Cloudflare Bypass ─────────────────────────────────────────────

def bypass_cloudflare(driver, url, max_retries=3):
    """Navigate to URL and bypass Cloudflare if present"""
    for attempt in range(max_retries):
        try:
            print(f"🌐 Navigating to {url} (attempt {attempt + 1})...")
            driver.get(url)
            time.sleep(5)

            # Check for Cloudflare challenge
            page_source = driver.page_source.lower()
            page_title = driver.title.lower()

            is_cloudflare = (
                'checking your browser' in page_source or
                'just a moment' in page_title or
                'verify you are human' in page_source or
                'cf-turnstile' in page_source or
                'challenge-platform' in page_source
            )

            if is_cloudflare:
                print("⚠️ Cloudflare detected, waiting for challenge...")

                # Wait for challenge to complete (up to 30 seconds)
                for wait in range(30):
                    time.sleep(1)
                    current_url = driver.current_url
                    page_source = driver.page_source.lower()

                    # Check if challenge passed
                    if 'checking your browser' not in page_source and 'just a moment' not in driver.title.lower():
                        print("✅ Cloudflare challenge passed!")
                        time.sleep(3)
                        return True

                    # Try to click turnstile checkbox if present
                    try:
                        turnstile = driver.find_element(By.CSS_SELECTOR, 'input[type="checkbox"], .cf-turnstile')
                        if turnstile.is_displayed():
                            turnstile.click()
                            print("🖱️ Clicked turnstile checkbox")
                            time.sleep(5)
                    except:
                        pass

                print("⚠️ Cloudflare challenge timeout, retrying...")
                if attempt < max_retries - 1:
                    time.sleep(10)
                    continue
                else:
                    print("❌ Could not bypass Cloudflare")
                    return False
            else:
                print("✅ No Cloudflare challenge")
                time.sleep(2)
                return True

        except Exception as e:
            print(f"❌ Navigation error: {e}")
            if attempt < max_retries - 1:
                time.sleep(10)
            else:
                return False

    return False

# ── Cookie Management ──────────────────────────────────────────────

def load_cookies(driver, cookies_path):
    """Load cookies from JSON file"""
    if not os.path.exists(cookies_path):
        print(f"⚠️ Cookies file not found: {cookies_path}")
        return False

    try:
        with open(cookies_path, 'r', encoding='utf-8') as f:
            cookies = json.load(f)

        driver.get("https://rumble.com")
        time.sleep(3)

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
                print(f"⚠️ Failed to add cookie {cookie.get('name', 'unknown')}: {e}")

        driver.refresh()
        time.sleep(3)
        print("✅ Cookies loaded")
        return True

    except Exception as e:
        print(f"❌ Error loading cookies: {e}")
        return False

# ── Login Check ────────────────────────────────────────────────────

def is_logged_in(driver):
    """Check if user is logged in to Rumble"""
    try:
        driver.get("https://rumble.com")
        time.sleep(3)

        logged_in_indicators = [
            'a[href="/upload"]',
            '.upload-button',
            '[data-testid="upload"]',
            '.user-avatar',
            '.avatar',
            '[data-testid="user-menu"]',
            '.header-user-menu',
            'a[href="/account"]',
        ]

        for selector in logged_in_indicators:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements and any(e.is_displayed() for e in elements):
                    print(f"✅ Logged in detected via: {selector}")
                    return True
            except:
                continue

        page_source = driver.page_source.lower()
        if 'logout' in page_source or 'my account' in page_source or 'dashboard' in page_source:
            print("✅ Logged in detected via page source")
            return True

        print("⚠️ Not logged in")
        return False

    except Exception as e:
        print(f"⚠️ Error checking login status: {e}")
        return False

# ── Manual Login ───────────────────────────────────────────────────

def login_with_credentials(driver, email, password):
    """Login with email and password, bypassing Cloudflare"""
    try:
        print(f"🔐 Attempting login with credentials...")

        # Go to login page with Cloudflare bypass
        if not bypass_cloudflare(driver, "https://rumble.com/login", max_retries=3):
            print("❌ Could not reach login page")
            return False

        time.sleep(3)

        # Find and fill email
        try:
            email_field = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 
                    'input[type="email"], input[name="email"], #email, input[placeholder*="mail" i]'))
            )
            email_field.clear()
            email_field.send_keys(email)
            print("✅ Email filled")
        except Exception as e:
            print(f"❌ Could not find email field: {e}")
            # Try to find any input field
            inputs = driver.find_elements(By.CSS_SELECTOR, 'input')
            print(f"Found {len(inputs)} input fields")
            for i, inp in enumerate(inputs):
                print(f"  Input {i}: type={inp.get_attribute('type')}, name={inp.get_attribute('name')}")
            return False

        # Find and fill password
        try:
            password_field = driver.find_element(By.CSS_SELECTOR, 
                'input[type="password"], input[name="password"], #password, input[placeholder*="pass" i]')
            password_field.clear()
            password_field.send_keys(password)
            print("✅ Password filled")
        except Exception as e:
            print(f"❌ Could not find password field: {e}")
            return False

        # Click submit
        try:
            submit_btn = driver.find_element(By.CSS_SELECTOR, 
                'button[type="submit"], .login-submit, input[type="submit"], .btn-login')
            submit_btn.click()
            print("✅ Submit clicked")
        except Exception as e:
            print(f"❌ Could not find submit button: {e}")
            # Try pressing Enter
            password_field.send_keys("
")
            print("✅ Pressed Enter to submit")

        time.sleep(8)

        # Check for Cloudflare challenge after login
        page_source = driver.page_source.lower()
        if 'checking your browser' in page_source or 'just a moment' in driver.title.lower():
            print("⚠️ Cloudflare challenge after login, waiting...")
            time.sleep(15)

        # Check if login successful
        if is_logged_in(driver):
            print("✅ Logged in successfully!")
            return True

        # Check for error messages
        error_selectors = [
            '.error-message',
            '.alert-error',
            '[data-testid="error"]',
            '.form-error'
        ]
        for selector in error_selectors:
            try:
                error_el = driver.find_element(By.CSS_SELECTOR, selector)
                if error_el.is_displayed():
                    print(f"❌ Login error: {error_el.text}")
            except:
                pass

        return False

    except Exception as e:
        print(f"❌ Login with credentials failed: {e}")
        traceback.print_exc()
        return False

# ── Rumble Upload ──────────────────────────────────────────────────

def upload_to_rumble(driver, video_path, title, description="", tags="", srt_path=None, thumbnail_path=None):
    """Upload video to Rumble"""
    try:
        print(f"\n📤 Starting Rumble upload...")
        print(f"   Video: {video_path}")
        print(f"   Title: {title}")

        # Go to upload page with Cloudflare bypass
        if not bypass_cloudflare(driver, "https://rumble.com/upload", max_retries=3):
            print("❌ Could not reach upload page")
            return None

        time.sleep(5)

        # Verify we're on upload page
        if "upload" not in driver.current_url:
            print(f"❌ Not on upload page. Current URL: {driver.current_url}")
            return None

        # ── Upload Video File ──────────────────────────────────────
        print("📁 Uploading video file...")

        file_selectors = [
            'input[type="file"][accept*="video"]',
            'input[type="file"]',
            '.file-input',
            '[data-testid="file-input"]',
            'input[name="video"]',
        ]

        file_input = None
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
            file_input = driver.execute_script("""
                return document.querySelector('input[type="file"]') || 
                       document.querySelector('[type="file"]');
            """)

        if file_input:
            abs_path = os.path.abspath(video_path)
            file_input.send_keys(abs_path)
            print(f"✅ Video file sent: {abs_path}")
        else:
            print("❌ Cannot find file input element")
            return None

        # Wait for upload to start
        print("⏳ Waiting for upload to start...")
        time.sleep(15)

        # Wait for form to appear
        max_wait = 300
        waited = 0
        while waited < max_wait:
            try:
                title_field = driver.find_element(By.CSS_SELECTOR, 
                    'input[name="title"], #title, .title-input, textarea[name="title"]')
                if title_field.is_displayed():
                    print("✅ Upload form ready")
                    break
            except:
                pass

            # Check for errors
            try:
                error_elements = driver.find_elements(By.CSS_SELECTOR, '.error, .alert-error, .upload-error')
                if error_elements:
                    error_text = error_elements[0].text
                    print(f"❌ Upload error: {error_text}")
                    return None
            except:
                pass

            time.sleep(5)
            waited += 5
            if waited % 30 == 0:
                print(f"   Still uploading... ({waited}s)")

        # ── Fill Title ───────────────────────────────────────────
        print("📝 Filling title...")
        try:
            title_field = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 
                    'input[name="title"], #title, .title-input, textarea[name="title"]'))
            )
            title_field.clear()
            title_field.send_keys(title)
        except Exception as e:
            print(f"⚠️ Title field issue: {e}")

        # ── Fill Description ───────────────────────────────────
        if description:
            print("📝 Filling description...")
            try:
                desc_field = driver.find_element(By.CSS_SELECTOR,
                    'textarea[name="description"], #description, .description-input, textarea[placeholder*="description" i]')
                desc_field.clear()
                desc_field.send_keys(description)
            except Exception as e:
                print(f"⚠️ Description field issue: {e}")

        # ── Upload SRT if provided ────────────────────────────────
        if srt_path and os.path.exists(srt_path):
            print("📝 Uploading SRT subtitle...")
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
                    print("✅ SRT uploaded")
                    time.sleep(2)
                else:
                    try:
                        caption_btns = driver.find_elements(By.XPATH,
                            "//button[contains(text(), 'caption') or contains(text(), 'subtitle') or contains(text(), 'CC')]")
                        if caption_btns:
                            caption_btns[0].click()
                            time.sleep(2)
                            sub_input = driver.find_element(By.CSS_SELECTOR, 'input[type="file"]')
                            sub_input.send_keys(os.path.abspath(srt_path))
                            print("✅ SRT uploaded via caption button")
                    except:
                        print("⚠️ No subtitle upload found")
            except Exception as e:
                print(f"⚠️ SRT upload issue: {e}")

        # ── Submit / Publish ─────────────────────────────────────
        print("🚀 Publishing video...")

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
            print("✅ Publish button clicked")
        else:
            driver.execute_script("""
                var btns = document.querySelectorAll('button[type="submit"], .publish-btn, .btn-primary');
                for(var i=0; i<btns.length; i++) {
                    if(btns[i].offsetParent !== null) { btns[i].click(); break; }
                }
            """)

        # Wait for processing
        print("⏳ Waiting for processing...")
        time.sleep(20)

        # ── Get Video URL ────────────────────────────────────────
        current_url = driver.current_url
        print(f"📍 Current URL: {current_url}")

        if "/v/" in current_url or "/c/" in current_url:
            print(f"✅ Video URL found: {current_url}")
            return current_url

        try:
            video_links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/v/"], a[href*="/c/"]')
            for link in video_links:
                href = link.get_attribute('href')
                if href and ("/v/" in href or "/c/" in href):
                    print(f"✅ Video URL found: {href}")
                    return href
        except:
            pass

        return current_url

    except Exception as e:
        print(f"❌ Upload failed: {e}")
        traceback.print_exc()
        return None

# ── Main Function ──────────────────────────────────────────────────

def upload_video_to_rumble(video_path, title, description="", tags="", srt_path=None, thumbnail_path=None):
    """Main function to upload video to Rumble"""
    driver = None

    try:
        print("=" * 60)
        print("🚀 Rumble Uploader")
        print("=" * 60)

        if not os.path.exists(video_path):
            print(f"❌ Video file not found: {video_path}")
            return None

        video_size = os.path.getsize(video_path) / (1024 * 1024)
        print(f"📁 Video: {video_path} ({video_size:.1f} MB)")

        # Setup driver
        print("\n🔧 Setting up Chrome...")
        driver = setup_driver()

        # Try cookies login first
        logged_in = False
        if os.path.exists(COOKIES_PATH):
            print("\n🍪 Trying cookies login...")
            load_cookies(driver, COOKIES_PATH)
            logged_in = is_logged_in(driver)

        # Fallback to credentials
        if not logged_in and RUMBLE_EMAIL and RUMBLE_PASSWORD:
            print("\n🔐 Trying credentials login...")
            logged_in = login_with_credentials(driver, RUMBLE_EMAIL, RUMBLE_PASSWORD)

        if not logged_in:
            print("❌ Could not login to Rumble")
            return None

        # Upload video
        result = upload_to_rumble(driver, video_path, title, description, tags, srt_path, thumbnail_path)

        if result:
            print(f"\n✅ SUCCESS! Video URL: {result}")
        else:
            print("\n❌ Upload failed")

        return result

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        traceback.print_exc()
        return None
    finally:
        if driver:
            print("\n🧹 Closing browser...")
            try:
                driver.quit()
            except:
                pass

# ── CLI Entry Point ────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python rumble_uploader.py <video_path> <title> [description] [tags] [srt_path]")
        sys.exit(1)

    video_path = sys.argv[1]
    title = sys.argv[2]
    description = sys.argv[3] if len(sys.argv) > 3 else ""
    tags = sys.argv[4] if len(sys.argv) > 4 else ""
    srt_path = sys.argv[5] if len(sys.argv) > 5 else None

    result = upload_video_to_rumble(video_path, title, description, tags, srt_path)

    if result:
        print(f"\nSUCCESS_URL: {result}")
        sys.exit(0)
    else:
        print("\nFAILED")
        sys.exit(1)
