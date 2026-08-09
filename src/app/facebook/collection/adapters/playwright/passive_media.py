from __future__ import annotations

from typing import Any

PASSIVE_MEDIA_GUARD_INSTALL_JS = r"""
() => {
  if (window.__fbSpyPassiveMediaGuard) {
    window.__fbSpyPassiveMediaGuard.pauseAll();
    return true;
  }
  const state = {
    blockedPlayCalls: 0,
    pauseEvents: 0,
    observedVideos: 0,
    pauseAll() {
      for (const video of document.querySelectorAll("video")) {
        state.observedVideos += 1;
        try {
          video.autoplay = false;
          video.muted = true;
          if (!video.paused) state.pauseEvents += 1;
          video.pause();
        } catch (_) {}
      }
    },
  };
  const nativePlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (...args) {
    state.blockedPlayCalls += 1;
    try {
      this.autoplay = false;
      this.muted = true;
      this.pause();
    } catch (_) {}
    return Promise.resolve();
  };
  state.nativePlay = nativePlay;
  const stopPlayback = event => {
    const video = event.target;
    if (!(video instanceof HTMLMediaElement)) return;
    try {
      video.autoplay = false;
      video.muted = true;
      if (!video.paused) state.pauseEvents += 1;
      video.pause();
    } catch (_) {}
  };
  document.addEventListener("play", stopPlayback, true);
  const startObserver = () => {
    if (!document.documentElement || state.observer) return;
    const observer = new MutationObserver(() => state.pauseAll());
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
    });
    state.observer = observer;
    state.pauseAll();
  };
  window.__fbSpyPassiveMediaGuard = state;
  if (document.documentElement) startObserver();
  else document.addEventListener("DOMContentLoaded", startObserver, {once: true});
  return true;
}
"""


def install_passive_media_guard(page: Any) -> bool:
    """Pause current and newly inserted videos for one passive feed document."""
    try:
        return bool(page.evaluate(PASSIVE_MEDIA_GUARD_INSTALL_JS))
    except Exception:
        return False


def prepare_passive_media_guard(page: Any) -> dict[str, int | bool]:
    """Install play and media-request blockers before passive feed navigation."""
    stats: dict[str, int | bool] = {
        "init_script_installed": False,
        "media_route_installed": False,
        "blocked_media_requests": 0,
    }
    try:
        page.add_init_script(f"({PASSIVE_MEDIA_GUARD_INSTALL_JS})()")
        stats["init_script_installed"] = True
    except Exception:
        pass

    def block_media(route: Any) -> None:
        try:
            if route.request.resource_type == "media":
                stats["blocked_media_requests"] += 1
                route.abort()
                return
            route.continue_()
        except Exception:
            try:
                route.abort()
            except Exception:
                pass

    try:
        page.route("**/*", block_media)
        stats["media_route_installed"] = True
    except Exception:
        pass
    return stats


def pause_all_videos(page: Any) -> None:
    try:
        page.evaluate(
            """
            () => {
              const guard = window.__fbSpyPassiveMediaGuard;
              if (guard && typeof guard.pauseAll === "function") {
                guard.pauseAll();
                return;
              }
              for (const video of document.querySelectorAll("video")) {
                try {
                  video.autoplay = false;
                  video.muted = true;
                  video.pause();
                } catch (_) {}
              }
            }
            """
        )
    except Exception:
        pass


def passive_media_guard_stats(page: Any) -> dict[str, int | bool]:
    try:
        payload = page.evaluate(
            """
            () => {
              const guard = window.__fbSpyPassiveMediaGuard;
              return guard ? {
                installed: true,
                blocked_play_calls: Number(guard.blockedPlayCalls || 0),
                pause_events: Number(guard.pauseEvents || 0),
                observed_videos: Number(guard.observedVideos || 0),
              } : {
                installed: false,
                blocked_play_calls: 0,
                pause_events: 0,
                observed_videos: 0,
              };
            }
            """
        )
        if isinstance(payload, dict):
            return {
                "installed": bool(payload.get("installed")),
                "blocked_play_calls": int(payload.get("blocked_play_calls") or 0),
                "pause_events": int(payload.get("pause_events") or 0),
                "observed_videos": int(payload.get("observed_videos") or 0),
            }
    except Exception:
        pass
    return {
        "installed": False,
        "blocked_play_calls": 0,
        "pause_events": 0,
        "observed_videos": 0,
    }
