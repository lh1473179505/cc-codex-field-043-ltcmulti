"""Multi-camera LTC alignment. Not implemented in the initial snapshot."""

from __future__ import annotations


class NotImplementedAlign(NotImplementedError):
    pass


def align(manifest_path: str, policy_path: str, report_path: str, map_path: str) -> int:
    raise NotImplementedAlign(
        "ltcmulti.align.align is not implemented yet; LTC decode / probe already work"
    )
