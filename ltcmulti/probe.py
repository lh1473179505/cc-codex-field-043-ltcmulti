"""Inventory a set of camera LTC tracks."""

from __future__ import annotations

import json
from pathlib import Path

from . import ltc, wavio
from .timecode import to_framecount


def probe_manifest(path: str) -> dict:
    doc = json.loads(Path(path).read_text())
    base = Path(path).resolve().parent
    cameras = []
    for cam in doc["cameras"]:
        wav_path = str((base / cam["path"]).resolve())
        wav = wavio.read_wav(wav_path)
        mono = wav.samples[0] if wav.channels >= 1 else []
        fps = int(cam["nominal_fps"])
        frames = ltc.decode_bmc(mono, wav.sample_rate, fps)
        tcs = [f.timecode for f in frames]
        cameras.append(
            {
                "id": cam["id"],
                "path": wav_path,
                "sample_rate": wav.sample_rate,
                "frames_audio": wav.frames,
                "duration_ms": wav.frames / wav.sample_rate * 1000.0,
                "ltc_frames": len(frames),
                "first": str(tcs[0]) if tcs else None,
                "last": str(tcs[-1]) if tcs else None,
                "first_sample": frames[0].sample_start if frames else None,
                "last_sample": frames[-1].sample_end if frames else None,
                "drop_frame": tcs[0].drop_frame if tcs else None,
            }
        )
    return {"manifest": path, "master": doc.get("master"), "cameras": cameras}


def format_probe(info: dict) -> str:
    return json.dumps(info, ensure_ascii=False, indent=2)
