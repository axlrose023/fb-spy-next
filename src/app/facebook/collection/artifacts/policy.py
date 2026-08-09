from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ArtifactPolicy:
    screenshots: bool
    landing_resolution: bool
    video_recording: bool
    permalink_resolution: bool
    interest_safe: bool
    overrides: tuple[str, ...]

    @classmethod
    def from_options(
        cls,
        *,
        screenshots: bool,
        landing_resolution: bool,
        video_recording: bool,
        permalink_resolution: bool,
        interest_safe: bool,
    ) -> ArtifactPolicy:
        overrides: list[str] = []
        if interest_safe:
            if landing_resolution:
                overrides.append("landing_resolution")
            if video_recording:
                overrides.append("video_recording")
            if permalink_resolution:
                overrides.append("permalink_resolution")
            landing_resolution = False
            video_recording = False
            permalink_resolution = False
        return cls(
            screenshots=screenshots,
            landing_resolution=landing_resolution,
            video_recording=video_recording,
            permalink_resolution=permalink_resolution,
            interest_safe=interest_safe,
            overrides=tuple(overrides),
        )
