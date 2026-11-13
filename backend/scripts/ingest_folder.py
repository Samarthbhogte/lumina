"""Upload every PDF in a folder to a running Lumina API, e.g. the bundled samples:

    python -m backend.scripts.ingest_folder samples --email you@example.com
    python -m backend.scripts.ingest_folder ~/policies --email you@example.com --workspace <id>

Signs in as the given account (password from LUMINA_PASSWORD or a prompt) and uploads into
your personal workspace unless --workspace names another one you can edit.

It goes through the API (rather than opening the index directly) so it is safe to run
while the server is up. Files already in the library are reported as duplicates.
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--api", default="http://localhost:8000", help="Lumina API base URL")
    parser.add_argument("--email", required=True, help="your Lumina account email")
    parser.add_argument("--workspace", help="workspace id (default: your personal workspace)")
    args = parser.parse_args()

    pdfs = sorted(args.folder.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {args.folder}", file=sys.stderr)
        return 1

    failed = 0
    password = os.getenv("LUMINA_PASSWORD") or getpass.getpass("Lumina password: ")
    with httpx.Client(base_url=args.api.rstrip("/"), timeout=300, headers={"X-Lumina-CSRF": "1"}) as client:
        try:
            client.get("/api/health").raise_for_status()
        except httpx.HTTPError as exc:
            print(f"Can't reach the API at {args.api}: {exc}", file=sys.stderr)
            return 1
        login = client.post("/api/auth/login", json={"email": args.email, "password": password})
        if login.status_code != 200:
            print(f"Sign-in failed: {login.json().get('detail', login.text)}", file=sys.stderr)
            return 1
        workspaces = login.json()["workspaces"]
        ws = args.workspace or next(w["id"] for w in workspaces if w["kind"] == "personal")
        for path in pdfs:
            files = [("files", (path.name, path.read_bytes(), "application/pdf"))]
            res = client.post(f"/api/workspaces/{ws}/documents", files=files)
            if res.status_code != 200:
                print(f"error  {path.name}: {res.json().get('detail', res.text)}")
                failed += 1
                continue
            r = res.json()["results"][0]
            doc = r.get("document") or {}
            if r["status"] == "failed":
                failed += 1
                print(f"failed {path.name}: {r['error']}")
            else:
                print(f"{r['status']:<9} {path.name}: {doc.get('pages')} pages, {doc.get('chunks')} chunks")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
