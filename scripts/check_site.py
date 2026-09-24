#!/usr/bin/env python3
"""Inspect local HTML destinations and fragment identifiers in a built site."""

from html.parser import HTMLParser
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit


class Page(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.ids = set()
        self.links = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        for key in ("href", "src"):
            if key in attrs:
                self.links.append(attrs[key])


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "site").resolve()
    pages = {p: Page(p.read_text(encoding="utf-8")) for p in root.rglob("*.html")}
    if not pages or root / "index.html" not in pages:
        raise SystemExit("No built website index")
    errors = []
    inspected = 0
    for path, page in pages.items():
        if path.name == "404.html":
            continue
        for link in page.links:
            url = urlsplit(link)
            if url.scheme or url.netloc or url.path.startswith("/"):
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            if target.is_dir():
                target /= "index.html"
            inspected += 1
            if not target.is_relative_to(root) or not target.is_file():
                errors.append(f"{path.relative_to(root)}: missing {link}")
            elif url.fragment and target in pages and unquote(url.fragment) not in pages[target].ids:
                errors.append(f"{path.relative_to(root)}: missing fragment {link}")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Website links: {inspected} local destinations inspected across {len(pages)} HTML pages")


if __name__ == "__main__":
    main()
