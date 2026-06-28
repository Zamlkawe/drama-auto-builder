import json
import os
import requests
import urllib3
from google.colab import drive

# إيقاف تحذيرات الأمان المزعجة في الشاشة
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. ربط جوجل درايف لحفظ الفيلم النهائي بداخله
drive.mount('/content/drive')

# ==========================================
# ⚠️ ضع اسم ملف الـ JSON الذي استخرجه البوت هنا
JSON_FILE = '' 
# ==========================================

OUTPUT_FOLDER = '/content/drive/MyDrive/DramaMovies'
TEMP_DIR = '/content/temp_videos'

os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

# 2. قراءة ملف البيانات
if not os.path.exists(JSON_FILE):
    print(f"❌ لم يتم العثور على الملف: {JSON_FILE}. الرجاء رفعه أولاً.")
else:
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    episodes = data['episodes']
    movie_name = "".join(x for x in data['series_title'] if x.isalnum() or x in " _-")
    final_output = os.path.join(OUTPUT_FOLDER, f"{movie_name}_Full_Movie.mp4")
    list_file_path = os.path.join(TEMP_DIR, 'mylist.txt')

    print(f"🎬 جاري تجهيز فيلم: {data['series_title']}")
    print(f"📦 عدد الحلقات: {len(episodes)}")
    print("-" * 40)

    # 3. تحميل الحلقات بسرعة السيرفر
    list_content = ""
    for ep in episodes:
        url = ep['video_url']
        ep_num = ep['episode']
        
        if not url or "http" not in url:
            print(f"⚠️ تخطي حلقة {ep_num} (لا يوجد رابط)")
            continue
        
        video_path = os.path.join(TEMP_DIR, f"ep_{ep_num}.mp4")
        print(f"📥 تحميل الحلقة {ep_num}...")
        
        try:
            # 🔥 السر هنا: verify=False عشان يتجاهل شهادة الأمان ويحمل بالعافية
            r = requests.get(url, stream=True, verify=False)
            r.raise_for_status() # التأكد إن مفيش خطأ 404 أو غيره
            
            with open(video_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if chunk: f.write(chunk)
                    
            list_content += f"file '{video_path}'\n"
        except Exception as e:
            print(f"❌ فشل تحميل الحلقة {ep_num}: {e}")

    # 4. حفظ ملف القائمة لأداة الدمج
    with open(list_file_path, 'w', encoding='utf-8') as f:
        f.write(list_content)

    print("-" * 40)
    print("⏳ جاري دمج الحلقات في فيلم واحد... (يستغرق ثواني معدودة)")

    # 5. الدمج الفوري باستخدام FFmpeg
    ffmpeg_cmd = f'ffmpeg -f concat -safe 0 -i "{list_file_path}" -c copy "{final_output}" -y -loglevel error'
    os.system(ffmpeg_cmd)

    print("🎉 اكتمل الدمج بنجاح!")
    print(f"🎥 الفيلم محفوظ الآن في جوجل درايف الخاص بك في مجلد (DramaMovies).")