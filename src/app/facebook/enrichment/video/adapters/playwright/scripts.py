VIDEO_PREP_JS = r"""
async (elementId) => {
  const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
  if (!root) return {ok:false, reason:"missing_root"};
  root.scrollIntoView({block:"center", inline:"nearest"});
  await new Promise(resolve => setTimeout(resolve, 300));
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width * r.height >= 25000 &&
      r.bottom > 0 && r.top < innerHeight &&
      s.display !== "none" && s.visibility !== "hidden" &&
      Number(s.opacity || 1) > 0.05;
  };
  const videos = [...root.querySelectorAll("video")]
    .filter(visible)
    .map(video => {
      const r = video.getBoundingClientRect();
      return {video, area:r.width*r.height, rect:r};
    })
    .sort((a,b) => b.area - a.area);
  if (!videos.length) return {ok:false, reason:"missing_visible_video"};
  const {video, rect} = videos[0];
  try { video.muted = true; } catch {}
  try { video.playsInline = true; } catch {}
  try {
    if (Number.isFinite(video.currentTime) && video.currentTime > 0.05) {
      video.pause();
      video.currentTime = 0;
      await Promise.race([
        new Promise(resolve => video.addEventListener("seeked", resolve, {once:true})),
        new Promise(resolve => setTimeout(resolve, 600)),
      ]);
    }
  } catch {}
  let played = false;
  let error = "";
  try {
    await video.play();
    played = true;
  } catch (exc) {
    error = String((exc && exc.message) || exc || "");
  }
  return {
    ok:true,
    played,
    error,
    paused:video.paused,
    ended:video.ended,
    currentTime:Number.isFinite(video.currentTime) ? video.currentTime : null,
    duration:Number.isFinite(video.duration) ? video.duration : null,
    x:Math.round(rect.left + rect.width / 2),
    y:Math.round(rect.top + rect.height / 2),
    width:Math.round(rect.width),
    height:Math.round(rect.height),
  };
}
"""
