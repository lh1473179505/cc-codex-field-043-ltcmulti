from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import align, probe


def cmd_probe(args: argparse.Namespace) -> int:
    info = probe.probe_manifest(args.manifest)
    text = probe.format_probe(info)
    if args.out:
        Path(args.out).write_text(text + "\n")
    else:
        sys.stdout.write(text + "\n")
    return 0


def cmd_align(args: argparse.Namespace) -> int:
    try:
        return align.align(args.manifest, args.policy, args.report, args.map)
    except align.NotImplementedAlign as e:
        sys.stderr.write(str(e) + "\n")
        return 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ltcmulti")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("probe", help="decode LTC from camera tracks")
    sp.add_argument("--manifest", required=True)
    sp.add_argument("--out", default=None)
    sp.set_defaults(func=cmd_probe)
    sa = sub.add_parser("align", help="align cameras to the master LTC clock")
    sa.add_argument("--manifest", required=True)
    sa.add_argument("--policy", required=True)
    sa.add_argument("--report", required=True)
    sa.add_argument("--map", required=True, help="output alignment map JSON")
    sa.set_defaults(func=cmd_align)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
