
() => {
  const GLYPHS = [0xF17E1, 0xF078B];
  const DOMAIN_RE = /^(https?:\/\/)?([a-z0-9-]+\.)+[a-z]{2,}(\/\S*)?$/i;
  const BAD = %BAD%;
  const PUA = c => (c>=0xE000&&c<=0xF8FF)||(c>=0xF0000);
  const strip = s => [...(s||"")]
    .filter(ch=>!PUA(ch.codePointAt(0)))
    .join("")
    .replace(/\u200e|\u200f|\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const linesOf = el => (el && el.innerText || "")
    .split("\n").map(strip).filter(Boolean);
  const hasGlyphText = t => {
    for (const ch of (t||"")) if (GLYPHS.includes(ch.codePointAt(0))) return true;
    return false;
  };
  const isDomain = s => DOMAIN_RE.test((s||"").trim());
  const domainOf = s => {
    const m = (s||"").trim().match(DOMAIN_RE);
    if (!m) return "";
    return s.replace(/^https?:\/\//i,"").split("/")[0].toLowerCase();
  };
  const badDomain = dom => BAD.some(b => dom === b || dom.endsWith("." + b) || dom.includes(b));
  const hasLetters = s => /[\p{L}]/u.test(s||"");
  const wordCount = s => strip(s).split(/\s+/).filter(Boolean).length;
  const numericLike = s => /^[\d\s.,+]+([KkMmBb])?$/.test(strip(s).replace(/\s+/g, ""));
  const likelyCtaText = s => {
    const tx = strip(s);
    const words = wordCount(tx);
    return tx.length >= 2 && tx.length <= 42 && words >= 1 && words <= 5 &&
      hasLetters(tx) && !/\d/.test(tx) && !numericLike(tx) && !isDomain(tx) &&
      !/[a-z0-9-]+\.[a-z]{2,}/i.test(tx);
  };
  const engagementTop = root => {
    let top = Infinity;
    for (const el of root.querySelectorAll('a,[role="button"],[role="link"],[data-action-id]')) {
      const r = el.getBoundingClientRect();
      const tx = strip(el.innerText);
      if (r.width >= 40 && r.height >= 20 && numericLike(tx)) top = Math.min(top, r.top);
    }
    return top;
  };
  const bestButton = (root, maxTop = Infinity, minTop = -Infinity) => {
    let best = null;
    for (const el of root.querySelectorAll('a,[role="button"],[role="link"],[data-action-id]')) {
      const r = el.getBoundingClientRect();
      const tx = strip(el.innerText);
      if (r.top < minTop) continue;
      if (r.top >= maxTop) continue;
      if (r.width < 50 || r.height < 20 || r.height > 90 || !likelyCtaText(tx)) continue;
      const score = r.top * 10 + r.width;
      if (!best || score > best.score) best = {el, text:tx, score};
    }
    return best;
  };
  const videoPoster = video => {
    let root = video.parentElement;
    for (let depth = 0; root && depth < 4; root = root.parentElement, depth++) {
      const imgs = [...root.querySelectorAll('img[src][data-image-id]')];
      if (!imgs.length) continue;
      imgs.sort((a, b) =>
        (b.naturalWidth * b.naturalHeight) - (a.naturalWidth * a.naturalHeight));
      return imgs[0].src || "";
    }
    return "";
  };
  const biggestImgInfo = s => {
    let src = "", area = 0, bottom = -Infinity;
    for (const im of s.querySelectorAll('img[src]')) {
      if (!im.src || im.src.startsWith('data:')) continue;
      const r = im.getBoundingClientRect();
      const a = r.width * r.height;
      if (a > area) { area = a; src = im.src; bottom = r.bottom; }
    }
    for (const v of s.querySelectorAll('video')) {
      const r = v.getBoundingClientRect();
      const a = r.width * r.height;
      if (a > area) {
        area = a;
        bottom = r.bottom;
        // The visible video has a hidden poster sibling. Keep that stable URL
        // instead of retaining whichever small profile image was seen first.
        src = videoPoster(v);
      }
    }
    return {src, area, bottom};
  };
  const hasVideo = s => !!s.querySelector('video');
  const hasVideoCreative = s => {
    if (hasVideo(s)) return true;
    for (const el of s.querySelectorAll('button,[role="button"],[aria-label],video')) {
      const cls = (typeof el.className === "string" ? el.className : "").toLowerCase();
      const label = (el.getAttribute("aria-label") || "").toLowerCase();
      if (cls.includes("inline-video-icon") || label.includes("video")) return true;
    }
    return false;
  };
  const decodedAttributeValue = raw => (raw || "")
    .replace(/\\u0025/gi, "%")
    .replace(/\\u0026/gi, "&")
    .replace(/\\u003d/gi, "=")
    .replace(/\\u002f/gi, "/")
    .replace(/\\\//g, "/")
    .replace(/&amp;/gi, "&");
  const urlsFromAttribute = raw => {
    const value = decodedAttributeValue(raw);
    const urls = [];
    if (/^(?:https?:\/\/|\/l\.php\?)/i.test(value.trim())) {
      urls.push(value.trim());
    }
    for (const match of value.matchAll(/https?:\/\/[^"'\\\s<>]+/gi)) {
      urls.push(match[0]);
    }
    return [...new Set(urls)];
  };
  const outboundHrefInfo = (raw, displayedDomain, sourceScore) => {
    let parsed;
    try { parsed = new URL(raw, location.href); } catch (_) { return null; }
    if (!/^https?:$/.test(parsed.protocol)) return null;
    const host = parsed.hostname.toLowerCase().replace(/^www\./, "");
    const path = parsed.pathname.toLowerCase();
    let targetHost = host;
    const facebookHost = host === "facebook.com" || host.endsWith(".facebook.com");
    if (facebookHost) {
      if (!path.endsWith("/l.php")) return null;
      const target = parsed.searchParams.get("u");
      if (!target) return null;
      try {
        const targetUrl = new URL(target);
        targetHost = targetUrl.hostname.toLowerCase().replace(/^www\./, "");
      } catch (_) {
        return null;
      }
    }
    if (badDomain(targetHost)) return null;
    if (/\.(?:png|jpe?g|gif|webp|svg|mp4|m3u8)(?:$|\?)/i.test(parsed.href)) {
      return null;
    }
    const expected = (displayedDomain || "").replace(/^www\./, "");
    const domainMatch = expected && (
      targetHost === expected ||
      targetHost.endsWith("." + expected) ||
      expected.endsWith("." + targetHost)
    );
    return {
      href: parsed.href,
      score: sourceScore + (domainMatch ? 1000 : 0),
    };
  };
  const passiveHrefOf = (cardEl, buttonEl, story, displayedDomain) => {
    const candidates = [];
    const inspect = (node, baseScore) => {
      if (!node || !node.attributes) return;
      const explicitNames = new Set([
        "href", "data-lynx-uri", "data-href", "data-url",
        "data-destination-url", "data-endpoint",
      ]);
      for (const attr of node.attributes) {
        const name = (attr.name || "").toLowerCase();
        const explicit = explicitNames.has(name);
        if (!explicit && !/(?:url|uri|href|store|tracking)/.test(name)) continue;
        for (const rawUrl of urlsFromAttribute(attr.value || "")) {
          const info = outboundHrefInfo(
            rawUrl,
            displayedDomain,
            baseScore + (explicit ? 200 : 0),
          );
          if (info) candidates.push(info);
        }
      }
    };
    let node = buttonEl;
    for (let depth = 0; node && node !== story && depth < 7;
         node = node.parentElement, depth++) {
      inspect(node, 700 - depth * 20);
    }
    for (const child of cardEl.querySelectorAll(
      'a[href],[data-lynx-uri],[data-href],[data-url],[data-destination-url]'
    )) {
      inspect(child, 500);
    }
    node = cardEl;
    for (let depth = 0; node && node !== story && depth < 5;
         node = node.parentElement, depth++) {
      inspect(node, 400 - depth * 20);
    }
    candidates.sort((a, b) => b.score - a.score);
    return candidates.length ? candidates[0].href : "";
  };
  const linkCard = s => {
    let best = null;
    for (const d of s.querySelectorAll('div')) {
      const r = d.getBoundingClientRect();
      if (r.width < 240 || r.height < 30) continue;
      if (hasGlyphText(d.innerText || "")) continue;
      const dl = linesOf(d);
      if (dl.length < 2 || !isDomain(dl[0])) continue;
      const dom = domainOf(dl[0]);
      if (!dom || badDomain(dom)) continue;
      const btn = bestButton(d, engagementTop(s));
      const cta = btn ? btn.text : "";
      const candidate = {
        el: d,
        domain: dom,
        headline: dl[1] || "",
        cta,
        btn: btn ? btn.el : null,
        area: r.width * r.height,
      };
      if (!best || (candidate.btn && !best.btn) || candidate.area < best.area) best = candidate;
    }
    if (!best) return null;
    let target = best.btn;
    if (!target) {
      for (let el = best.el, depth = 0; el && el !== s && depth < 5;
           el = el.parentElement, depth++) {
        if (el.matches('a,[role="button"],[role="link"],[data-action-id]')) {
          target = el;
          break;
        }
      }
    }
    const br = best.btn ? best.btn.getBoundingClientRect() : null;
    const href = passiveHrefOf(best.el, target, s, best.domain);
    return {
      domain: best.domain,
      headline: best.headline,
      cta: best.cta,
      href,
      btn: br ? {x:Math.round(br.left+br.width/2), y:Math.round(br.top+br.height/2)} : null,
      target,
    };
  };
  const storyRootFor = sp => {
    for (let el = sp.parentElement, depth = 0; el && depth < 14; el = el.parentElement, depth++) {
      if (el.tagName !== "DIV") continue;
      const text = el.innerText || "";
      const r = el.getBoundingClientRect();
      if (r.width < 300 || r.height < 150 || r.height > 2600 ||
          text.length < 70 || text.length > 3500) continue;
      const img = biggestImgInfo(el);
      if (!linkCard(el) && !hasVideo(el) && img.area < 45000) continue;
      return el;
    }
    return null;
  };
  const advertiserOf = sp => {
    const sr = sp.getBoundingClientRect();
    const sponsored = new Set(linesOf(sp));
    const cands = [];
    for (let root = sp.parentElement, depth = 0; root && depth < 8; root = root.parentElement, depth++) {
      for (const el of root.querySelectorAll('a,[role="link"],span,div,h1,h2,h3,h4')) {
        if (el === sp || el.contains(sp) || sp.contains(el)) continue;
        const raw = el.innerText || "";
        if (hasGlyphText(raw)) continue;
        const r = el.getBoundingClientRect();
        if (r.bottom > sr.top + 6) continue;
        const tx = strip(raw);
        if (sponsored.has(tx)) continue;
        if (tx.length >= 2 && tx.length < 80 && hasLetters(tx))
          cands.push({line:tx, top:r.top, len:tx.length});
      }
      if (cands.length) break;
    }
    cands.sort((a,b)=>b.top-a.top || b.len-a.len);
    return cands.length ? cands[0].line : "";
  };
  const adTextOf = (root, sp, adv, card) => {
    const lines = linesOf(root);
    const sponsored = new Set(linesOf(sp));
    const skip = new Set([adv, card && card.domain, card && card.headline, card && card.cta]
      .filter(Boolean));
    for (const s of sponsored) skip.add(s);
    const domainIdx = card ? lines.findIndex(l => domainOf(l) === card.domain) : -1;
    const windowLines = domainIdx > 0 ? lines.slice(0, domainIdx) : lines;
    let best = "";
    for (const line of windowLines) {
      if (skip.has(line) || isDomain(line) || numericLike(line) || !hasLetters(line)) continue;
      if (likelyCtaText(line) && line.length <= 42) continue;
      if (line.length > best.length) best = line;
    }
    return best;
  };
  const facebookIdentityOf = root => {
    let adId = "", ownerId = "", postId = "";
    const values = [];
    for (const el of [root, ...root.querySelectorAll("*")]) {
      for (const attr of el.attributes || []) {
        const value = attr.value || "";
        if (!value.startsWith("{") ||
            !/(adid|top_level_post_id|story_fbid|content_owner_id_new)/.test(value)) continue;
        values.push(value);
      }
    }
    for (const value of values) {
      let payload;
      try { payload = JSON.parse(value); } catch (_) { continue; }
      const pending = [payload];
      let inspected = 0;
      while (pending.length && inspected++ < 150) {
        const item = pending.pop();
        if (!item || typeof item !== "object") continue;
        if (!adId && item.adid) adId = String(item.adid);
        if (!ownerId && item.content_owner_id_new) ownerId = String(item.content_owner_id_new);
        if (!ownerId && item.actor_id) ownerId = String(item.actor_id);
        if (!postId && item.top_level_post_id) postId = String(item.top_level_post_id);
        if (!postId && item.story_fbid) {
          postId = String(Array.isArray(item.story_fbid) ? item.story_fbid[0] : item.story_fbid);
        }
        if (!postId && item.post_id) postId = String(item.post_id);
        for (const child of Object.values(item)) {
          if (child && typeof child === "object") pending.push(child);
        }
      }
      if (adId && ownerId && postId) break;
    }
    return {
      fb_ad_id: adId,
      facebook_page_url: ownerId ? `https://m.facebook.com/${ownerId}` : "",
      facebook_post_url: ownerId && postId
        ? `https://m.facebook.com/${ownerId}/posts/${postId}`
        : "",
    };
  };

  const seenRoots = new Set();
  const out = [];
  const spans = [...document.querySelectorAll('span')]
    .filter(sp => (sp.getAttribute('style') || '').includes('#8a8d91') && hasGlyphText(sp.innerText));
  for (const sp of spans) {
    const el = storyRootFor(sp);
    if (!el || seenRoots.has(el)) continue;
    seenRoots.add(el);
    const card = linkCard(el);
    const adv = advertiserOf(sp);
    const adText = adTextOf(el, sp, adv, card);
    const img = biggestImgInfo(el);
    const facebook = facebookIdentityOf(el);
    const has_video = hasVideoCreative(el);
    let ad_type = card ? "link" : (has_video ? "video" : "in_facebook");
    const elementId = el.dataset.fbspyId ||
      ("fbspy_" + Date.now().toString(36) + "_" + out.length);
    el.dataset.fbspyId = elementId;
    if (card && card.target) card.target.dataset.fbspyClickTarget = elementId;
    out.push({
      advertiser: adv,
      ad_type,
      has_video,
      domain: card ? card.domain : "",
      headline: card ? card.headline : "",
      ad_text: adText.slice(0,300),
      cta: card ? (card.cta || "") : ((bestButton(el, engagementTop(el), img.bottom - 8) || {}).text || ""),
      cta_href: card ? (card.href || "") : "",
      creative_img: img.src,
      creative_area: Math.round(img.area || 0),
      btn: card ? card.btn : null,
      element_id: elementId,
      fb_ad_id: facebook.fb_ad_id,
      facebook_page_url: facebook.facebook_page_url,
      facebook_post_url: facebook.facebook_post_url,
    });
  }
  return out;
}
