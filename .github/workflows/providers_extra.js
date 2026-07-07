// ============================================================
//  providers_extra.js — المجموعة ب (مشغّلات SPA / بنية مختلفة)
// ------------------------------------------------------------
//  المزودون دول مش بيستخدموا مشغّل PHP (index.php?page=watch) زي
//  المجموعة أ، لكن مشغّلات JavaScript (SPA) بتحمّل الفيديو من API.
//
//  عشان يشتغلوا "زي نتشورت" من البوت: كل مزود بيمر على واجهة موحّدة
//     scrapeExtraSeries(providerKey, id, { connect, onProgress })
//  وبترجّع نفس شكل jsonData بتاع المجموعة أ:
//     { series_title, description, poster_url, category, total_episodes,
//       drama_id, provider, provider_name, scraped_at, scraped_from, episodes:[{episode,video_url,subtitle_url}] }
//
//  الاستراتيجية العامة (Generic): بنفتح صفحة المسلسل بمتصفح حقيقي،
//  ونعترض طلبات الشبكة (network responses) عشان نمسك روابط .m3u8/.mp4/.vtt/.srt.
//  وكل مزود ليه "hooks" اختيارية تقدر تعدّلها بسهولة تحت في EXTRA_PROVIDERS.
// ============================================================

const EXTRA_PROVIDERS = {
  kalostv: {
    name: 'KalosTV',
    host: 'kalostv.dramafren.org',
    idRegex: /^[A-Za-z0-9_\-]+$/,
    // TODO: عدّل لو محتاج. مثال watch URL المتوقع لو موجود:
    watchUrl: (host, id, ep) => `https://${host}/index.php?page=watch&id=${id}&ep=${ep}`,
    detailUrl: (host, id) => `https://${host}/index.php?page=detail&id=${id}`,
  },
  shotshort: {
    name: 'ShotShort',
    host: 'shotshort.dramafren.org',
    idRegex: /^[A-Za-z0-9_\-]+$/,
    watchUrl: (host, id, ep) => `https://${host}/index.php?page=watch&id=${id}&ep=${ep}`,
    detailUrl: (host, id) => `https://${host}/index.php?page=detail&id=${id}`,
  },
  microdrama: {
    name: 'MicroDrama',
    host: 'microdrama.dramafren.org',
    idRegex: /^[A-Za-z0-9_\-]+$/,
    watchUrl: (host, id, ep) => `https://${host}/index.php?page=watch&id=${id}&ep=${ep}`,
    detailUrl: (host, id) => `https://${host}/index.php?page=detail&id=${id}`,
  },
  shortwave: {
    name: 'ShortWave',
    host: 'shortwave.dramafren.org',
    idRegex: /^[A-Za-z0-9_\-]+$/,
    watchUrl: (host, id, ep) => `https://${host}/index.php?page=watch&id=${id}&ep=${ep}`,
    detailUrl: (host, id) => `https://${host}/index.php?page=detail&id=${id}`,
  },
  moboreels: {
    name: 'MoboReels',
    host: 'moboreels.dramafren.org',
    idRegex: /^[A-Za-z0-9_\-]+$/,
    watchUrl: (host, id, ep) => `https://${host}/index.php?page=watch&id=${id}&ep=${ep}`,
    detailUrl: (host, id) => `https://${host}/index.php?page=detail&id=${id}`,
  },
  tvseries: {
    name: 'TvSeries (DramaSeries)',
    host: 'tvseries.dramafren.org',
    idRegex: /^[A-Za-z0-9_\-]+$/,
    // مسلسلات كاملة (aoneroom) — بنية مختلفة، عدّل الروابط حسب الصفحة الفعلية.
    watchUrl: (host, id, ep) => `https://${host}/watch?id=${id}&ep=${ep}`,
    detailUrl: (host, id) => `https://${host}/detail?id=${id}`,
  },
  reelfren: {
    name: 'ReelFren',
    host: 'reelfren.dramafren.org',
    idRegex: /^[A-Za-z0-9_\-]+$/,
    // مُجمِّع متعدد المزودين. الرابط بشكل: /drama/{provider}/{id}-{slug}
    // بنمرّر sub-provider جوه الـ id على شكل "provider/id" (يتفكّ في detailUrl).
    detailUrl: (host, id) => {
      const [sub, realId] = id.includes('/') ? id.split('/') : ['melolo', id];
      return `https://${host}/drama/${sub}/${realId}?lang=en`;
    },
    watchUrl: (host, id, ep) => {
      const [sub, realId] = id.includes('/') ? id.split('/') : ['melolo', id];
      return `https://${host}/watch/${sub}/${realId}/${ep}?lang=en`;
    },
  },
};

function resolveExtraProviderKey(hostname) {
  const h = (hostname || '').toLowerCase();
  if (h.endsWith('.dramafren.org')) {
    const sub = h.replace('.dramafren.org', '').split('.').pop();
    if (EXTRA_PROVIDERS[sub]) return sub;
  }
  return null;
}

// استخراج الـ id من رابط المجموعة ب
function extractExtraId(u) {
  // reelfren: /drama/{provider}/{id}-{slug}
  const parts = u.pathname.split('/').filter(Boolean);
  if (parts[0] === 'drama' && parts.length >= 3) {
    const sub = parts[1];
    const realId = parts[2].includes('-') ? parts[2].split('-')[0] : parts[2];
    return `${sub}/${realId}`;
  }
  const q = u.searchParams.get('id');
  if (q) return q.trim();
  const seg = parts.pop() || '';
  return seg.includes('-') ? seg.split('-')[0] : seg;
}

function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

const MEDIA_RE = /https?:\/\/[^ "'\s>]+\.(?:m3u8|mp4|ts)(?:[^ "'\s>]*)?/i;
const SUB_RE   = /https?:\/\/[^ "'\s>]+\.(?:vtt|srt)(?:[^ "'\s>]*)?/i;

// ------------------------------------------------------------
//  السحب العام لمزودي المجموعة ب عبر اعتراض الشبكة
//  connect  : دالة puppeteer-real-browser (تتمرّر من bot.js)
//  onProgress(text) : لتحديث رسالة تليجرام (اختياري)
// ------------------------------------------------------------
async function scrapeExtraSeries(providerKey, id, { connect, onProgress = () => {}, maxEpisodesGuess = 200 } = {}) {
  const cfg = EXTRA_PROVIDERS[providerKey];
  if (!cfg) throw new Error(`Unknown extra provider: ${providerKey}`);

  let browser = null;
  const mediaByEp = {};   // ep -> video_url
  const subByEp = {};     // ep -> subtitle_url

  try {
    const resp = await connect({
      headless: false, turnstile: true, disableXvfb: true,
      args: ['--start-maximized', '--disable-blink-features=AutomationControlled', '--mute-audio', '--no-sandbox']
    });
    browser = resp.browser;
    const page = resp.page;

    // اعتراض كل الطلبات لالتقاط روابط الميديا والترجمة
    let currentEp = 1;
    page.on('response', (res) => {
      try {
        const url = res.url();
        if (MEDIA_RE.test(url) && !mediaByEp[currentEp]) mediaByEp[currentEp] = url;
        if (SUB_RE.test(url) && !subByEp[currentEp]) subByEp[currentEp] = url;
      } catch {}
    });

    // 1) صفحة التفاصيل — لاستخراج العنوان وعدد الحلقات
    await page.goto(cfg.detailUrl(cfg.host, id), { waitUntil: 'domcontentloaded', timeout: 45000 });
    await delay(4000); // مهلة للـ SPA يحمّل

    const meta = await page.evaluate(() => {
      const title = document.querySelector('meta[property="og:title"]')?.content || document.title || 'مسلسل';
      const description = document.querySelector('meta[property="og:description"]')?.content || '';
      const posterUrl = document.querySelector('meta[property="og:image"]')?.content || document.querySelector('img')?.src || '';
      // محاولة تقدير عدد الحلقات من نصوص زي "60 Eps" أو "Ep 60"
      const bodyTxt = document.body ? document.body.innerText : '';
      let totalEps = 0;
      const m1 = bodyTxt.match(/(\d+)\s*(?:Eps|Episodes|حلقة)/i);
      if (m1) totalEps = parseInt(m1[1], 10);
      const eps = [...bodyTxt.matchAll(/Ep\s*(\d+)/gi)].map(m => parseInt(m[1], 10));
      if (eps.length) totalEps = Math.max(totalEps, ...eps);
      return { title, description, posterUrl, totalEps };
    });

    const totalEps = meta.totalEps > 0 ? meta.totalEps : maxEpisodesGuess;
    onProgress(`🏷️ ${cfg.name}\n🎬 ${meta.title}\n📺 عدد الحلقات (تقديري): ${totalEps}\n⏳ جاري سحب الحلقات...`);

    // 2) المرور على الحلقات — نفتح صفحة كل حلقة ونلتقط رابط الميديا من الشبكة
    const episodes = [];
    for (let ep = 1; ep <= totalEps; ep++) {
      currentEp = ep;
      try {
        await page.goto(cfg.watchUrl(cfg.host, id, ep), { waitUntil: 'domcontentloaded', timeout: 30000 });
        // ننتظر شوية لحد ما مشغّل الفيديو يطلب الـ m3u8/mp4
        for (let w = 0; w < 8 && !mediaByEp[ep]; w++) await delay(1000);
      } catch {}

      if (mediaByEp[ep]) {
        episodes.push({ episode: ep, video_url: mediaByEp[ep], subtitle_url: subByEp[ep] || '' });
      } else {
        // لو حلقتين متتاليتين مفيش فيهم ميديا، يبقى غالباً خلصنا الحلقات
        if (ep > 1 && !mediaByEp[ep] && !mediaByEp[ep - 1] && meta.totalEps === 0) break;
      }

      if (ep % 5 === 0) onProgress(`🏷️ ${cfg.name}\n🔄 تم سحب ${episodes.length}/${totalEps} حلقة...`);
    }

    if (episodes.length === 0) {
      throw new Error(`لم أتمكن من التقاط أي روابط فيديو من ${cfg.name}. غالباً محتاج تعديل hooks المزود في providers_extra.js`);
    }

    return {
      series_title: (meta.title || 'مسلسل').replace(/\s*\|\s*.*$/, '').trim(),
      description: meta.description,
      poster_url: meta.posterUrl,
      category: 'أخرى',
      total_episodes: episodes.length,
      drama_id: id,
      provider: providerKey,
      provider_name: cfg.name,
      scraped_at: new Date().toLocaleString(),
      scraped_from: `https://${cfg.host}`,
      episodes: episodes.sort((a, b) => a.episode - b.episode)
    };
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
}

module.exports = {
  EXTRA_PROVIDERS,
  resolveExtraProviderKey,
  extractExtraId,
  scrapeExtraSeries,
};
