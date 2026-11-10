#!/usr/bin/env python3
"""Multi-agent bug inbox (private/bugs/ — git-ignored, one file per report).

Any agent that finds a harness bug DURING PLAY files it here instead of
fixing-and-pushing (project rule: exactly one agent fixes any given
issue; play sessions never edit code mid-game). External
agents (other machines) file into their own clone's private/bugs/ and
deliver the files to the maintainer post-match.

    bugs.py file --reporter zoti --area sparring --title "..." [--body -]
    bugs.py list [--open]
    bugs.py claim <id> --by <agent>      # exclusive; refuses if claimed
    bugs.py close <id> --commit <sha>    # requires a prior claim
"""
import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INBOX = ROOT / "private" / "bugs"


class AlreadyClaimed(Exception):
    pass


class NotClaimed(Exception):
    pass


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def file_report(inbox: Path, reporter: str, area: str, title: str,
                body: str) -> str:
    inbox.mkdir(parents=True, exist_ok=True)
    base = f"{time.strftime('%Y%m%d')}-{_slug(title) or 'bug'}"
    bid, n = base, 1
    while (inbox / f"{bid}.md").exists():
        n += 1
        bid = f"{base}-{n}"
    (inbox / f"{bid}.md").write_text(
        f"id: {bid}\nstatus: open\nreporter: {reporter}\narea: {area}\n"
        f"claimed-by: \nfixed-commit: \n\n# {title}\n\n{body}\n")
    return bid


def _read(inbox: Path, bid: str) -> tuple[Path, str]:
    p = inbox / f"{bid}.md"
    if not p.exists():
        raise FileNotFoundError(f"no report {bid!r} in {inbox}")
    return p, p.read_text()


def _field(txt: str, key: str) -> str:
    m = re.search(rf"^{key}: (.*)$", txt, re.M)
    return (m.group(1) if m else "").strip()


def _set(txt: str, key: str, value: str) -> str:
    return re.sub(rf"^{key}: .*$", f"{key}: {value}", txt, count=1, flags=re.M)


def claim(inbox: Path, bid: str, by: str) -> None:
    p, txt = _read(inbox, bid)
    holder = _field(txt, "claimed-by")
    if holder and holder != by:
        raise AlreadyClaimed(f"{bid} already claimed by {holder!r}")
    p.write_text(_set(_set(txt, "claimed-by", by), "status", "claimed"))


def close(inbox: Path, bid: str, commit: str) -> None:
    p, txt = _read(inbox, bid)
    if not _field(txt, "claimed-by"):
        raise NotClaimed(f"{bid} must be claimed before closing")
    p.write_text(_set(_set(txt, "fixed-commit", commit), "status", "fixed"))


def list_reports(inbox: Path, only_open: bool = False) -> list[dict]:
    out = []
    for p in sorted(inbox.glob("*.md")):
        txt = p.read_text()
        e = {k: _field(txt, k) for k in
             ("id", "status", "reporter", "area", "claimed-by")}
        if only_open and e["status"] != "open":
            continue
        out.append(e)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inbox", type=Path, default=DEFAULT_INBOX)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("file")
    f.add_argument("--reporter", required=True)
    f.add_argument("--area", required=True)
    f.add_argument("--title", required=True)
    f.add_argument("--body", default="-",
                   help="text, or '-' to read stdin")
    ls = sub.add_parser("list")
    ls.add_argument("--open", action="store_true")
    c = sub.add_parser("claim")
    c.add_argument("id"); c.add_argument("--by", required=True)
    x = sub.add_parser("close")
    x.add_argument("id"); x.add_argument("--commit", required=True)
    a = ap.parse_args()
    try:
        if a.cmd == "file":
            body = sys.stdin.read() if a.body == "-" else a.body
            print(file_report(a.inbox, a.reporter, a.area, a.title, body))
        elif a.cmd == "list":
            for e in list_reports(a.inbox, only_open=a.open):
                print(f"{e['status']:<8} {e['id']}  [{e['area']}] "
                      f"by {e['reporter']}"
                      + (f"  → {e['claimed-by']}" if e['claimed-by'] else ""))
        elif a.cmd == "claim":
            claim(a.inbox, a.id, by=a.by); print(f"claimed by {a.by}")
        elif a.cmd == "close":
            close(a.inbox, a.id, commit=a.commit); print("fixed")
    except (AlreadyClaimed, NotClaimed, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
