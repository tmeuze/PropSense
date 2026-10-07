#!/usr/bin/env python3
"""Point the README import buttons and every blueprint `source_url` at your
GitHub repo and a version (a release tag such as v0.1.0, or main).

    python scripts/set_repo.py --owner YOUR_GITHUB_NAME --version v0.1.0

Safe to re-run; it rewrites whatever owner/version is currently there.
"""
import argparse
import re
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    ap.add_argument("--version", default="main")
    ap.add_argument("--repo", default="ha-unity")
    a = ap.parse_args()
    q = lambda s: quote(s, safe="")  # noqa: E731
    changed = 0
    readme = ROOT / "README.md"
    text = readme.read_text()
    new = re.sub(r"github\.com%2F[^%]+%2F[^%]+%2Fblob%2F[^%]+%2Fblueprints",
                 f"github.com%2F{q(a.owner)}%2F{q(a.repo)}%2Fblob%2F{q(a.version)}%2Fblueprints", text)
    if new != text:
        readme.write_text(new)
        changed += 1
    for f in sorted((ROOT / "blueprints").rglob("*.yaml")):
        t = f.read_text()
        n = re.sub(r"https://github\.com/[^/\s]+/[^/\s]+/blob/[^/\s]+/blueprints/",
                   f"https://github.com/{a.owner}/{a.repo}/blob/{a.version}/blueprints/", t)
        if n != t:
            f.write_text(n)
            changed += 1
    print(f"updated {changed} file(s) for {a.owner}/{a.repo} @ {a.version}")


if __name__ == "__main__":
    main()
