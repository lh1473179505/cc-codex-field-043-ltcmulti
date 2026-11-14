"""Multi-camera LTC alignment: decode each track, estimate offset and drift."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from . import ltc, wavio
from .timecode import to_framecount


class NotImplementedAlign(NotImplementedError):
    pass


DEFAULT_MIN_READABLE_RATIO = 0.5
MIN_SEGMENT_FRAMES = 4
MAX_GAP_FRAMES = 3
GAP_TOLERANCE_FRAMES = 0.75


@dataclass
class Track:
    cam_id: str
    nominal_fps: int
    sample_rate: int
    audio_frames: int
    ltc_frames: list[ltc.LtcFrame]

    @property
    def samples_per_frame(self) -> float:
        return self.sample_rate / self.nominal_fps

    @property
    def readable_ratio(self) -> float:
        expected = self.audio_frames / self.samples_per_frame
        if expected <= 0:
            return 0.0
        return len(self.ltc_frames) / expected

    @property
    def drop_frame(self) -> bool | None:
        if not self.ltc_frames:
            return None
        return self.ltc_frames[0].timecode.drop_frame


def _linfit(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    """Least-squares y = a + b*x. Returns (a, b) or None if degenerate."""
    n = len(xs)
    if n == 0:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


def _segments(frames: list[ltc.LtcFrame], samples_per_frame: float) -> list[list[ltc.LtcFrame]]:
    """Split decoded frames at timecode jumps / position gaps; drop tiny runs."""
    if not frames:
        return []
    segs: list[list[ltc.LtcFrame]] = []
    cur = [frames[0]]
    for f in frames[1:]:
        prev = cur[-1]
        dn = to_framecount(f.timecode) - to_framecount(prev.timecode)
        ds = f.sample_start - prev.sample_start
        contiguous = (
            1 <= dn <= MAX_GAP_FRAMES
            and abs(ds - dn * samples_per_frame) <= GAP_TOLERANCE_FRAMES * samples_per_frame * dn
        )
        if contiguous:
            cur.append(f)
        else:
            segs.append(cur)
            cur = [f]
    segs.append(cur)
    return [s for s in segs if len(s) >= MIN_SEGMENT_FRAMES]


def _segment_entry(
    seg: list[ltc.LtcFrame],
    reference: tuple[float, float],
    samples_per_frame: float,
) -> dict | None:
    """Fit one segment against the master reference fit (a, b): sample = a + b*tc."""
    xs = [to_framecount(f.timecode) for f in seg]
    ys = [f.sample_start for f in seg]
    fit = _linfit(xs, ys)
    if fit is None:
        return None
    a_s, b_s = fit
    a_m, b_m = reference
    n0 = xs[0]
    offset_samples = (a_s + b_s * n0) - (a_m + b_m * n0)
    offset_frames = offset_samples / samples_per_frame
    drift_ppm = (b_s - b_m) / b_m * 1e6 if b_m else 0.0
    user_bits: list[str] = []
    for f in seg:
        hexed = f.user_bits.hex()
        if hexed not in user_bits:
            user_bits.append(hexed)
    return {
        "start_tc": str(seg[0].timecode),
        "end_tc": str(seg[-1].timecode),
        "start_sample": seg[0].sample_start,
        "end_sample": seg[-1].sample_end,
        "offset_frames": round(offset_frames, 3),
        "offset_samples": int(round(offset_samples)),
        "drift_ppm": round(drift_ppm, 2),
        "user_bits": user_bits,
    }


def _read_json(path: str) -> dict | None:
    try:
        return json.loads(Path(path).read_text())
    except Exception as e:
        sys.stderr.write(f"align: cannot read {path}: {e}\n")
        return None


def align(manifest_path: str, policy_path: str, report_path: str, map_path: str) -> int:
    doc = _read_json(manifest_path)
    if doc is None:
        return 2
    policy = _read_json(policy_path)
    if policy is None:
        return 2
    min_ratio = float(policy.get("min_readable_ratio", DEFAULT_MIN_READABLE_RATIO))

    base = Path(manifest_path).resolve().parent
    tracks: list[Track] = []
    for cam in doc.get("cameras", []):
        wav_path = str((base / cam["path"]).resolve())
        try:
            wav = wavio.read_wav(wav_path)
        except Exception as e:
            sys.stderr.write(f"align: cannot read {wav_path}: {e}\n")
            return 2
        mono = wav.samples[0] if wav.channels >= 1 else []
        fps = int(cam["nominal_fps"])
        frames = ltc.decode_bmc(mono, wav.sample_rate, fps)
        tracks.append(Track(cam["id"], fps, wav.sample_rate, wav.frames, frames))

    master_id = doc.get("master")
    master = next((t for t in tracks if t.cam_id == master_id), None)

    reference: tuple[float, float] | None = None
    if master is not None and master.ltc_frames:
        reference = _linfit(
            [to_framecount(f.timecode) for f in master.ltc_frames],
            [f.sample_start for f in master.ltc_frames],
        )

    camera_reports: list[dict] = []
    map_cameras: list[dict] = []
    global_reasons: set[str] = set()

    for track in tracks:
        is_master = track is master
        reasons: list[str] = []
        segments = _segments(track.ltc_frames, track.samples_per_frame)

        if (
            not is_master
            and track.drop_frame is not None
            and master is not None
            and master.drop_frame is not None
            and track.drop_frame != master.drop_frame
        ):
            reasons.append("dropframe_mismatch")
            segments = []  # never mix drop/non-drop counting

        if track.readable_ratio < min_ratio:
            reasons.append("insufficient_lock")

        seg_entries: list[dict] = []
        if reference is not None:
            for seg in segments:
                entry = _segment_entry(seg, reference, track.samples_per_frame)
                if entry is not None:
                    seg_entries.append(entry)
        elif not is_master:
            reasons.append("no_master_reference")

        if not seg_entries and not reasons:
            reasons.append("insufficient_lock")

        decision = "ok" if not reasons and seg_entries else "reject"
        global_reasons.update(reasons)

        primary = max(seg_entries, key=lambda e: e["end_sample"] - e["start_sample"], default=None)
        camera_reports.append(
            {
                "id": track.cam_id,
                "decision": decision,
                "reason_codes": reasons,
                "readable_ratio": round(track.readable_ratio, 4),
                "segment_count": len(seg_entries),
                "offset_frames": primary["offset_frames"] if primary else None,
                "offset_samples": primary["offset_samples"] if primary else None,
                "drift_ppm": primary["drift_ppm"] if primary else None,
            }
        )
        map_cameras.append(
            {
                "id": track.cam_id,
                "readable_ratio": round(track.readable_ratio, 4),
                "drop_frame": track.drop_frame,
                "segments": seg_entries,
            }
        )

    overall = "ok" if all(c["decision"] == "ok" for c in camera_reports) else "reject"

    map_doc = {"manifest": manifest_path, "master": master_id, "cameras": map_cameras}
    report_doc = {
        "manifest": manifest_path,
        "decision": overall,
        "reason_codes": sorted(global_reasons),
        "master": master_id,
        "cameras": camera_reports,
        "map": map_path,
    }
    Path(map_path).write_text(json.dumps(map_doc, ensure_ascii=False, indent=2) + "\n")
    Path(report_path).write_text(json.dumps(report_doc, ensure_ascii=False, indent=2) + "\n")
    return 0 if overall == "ok" else 1

