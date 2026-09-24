#!/usr/bin/env python3
"""Prepare website Markdown from the README, roadmap and chapter renderer."""

import os
from pathlib import Path
import posixpath
import re
import shutil
from urllib.parse import quote, urlsplit, urlunsplit

from render import render_all


ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / ".site-src"
LINK = re.compile(r"(?P<prefix>\]\()(?P<url>[^\s)]+)(?P<suffix>\))")


def prepare():
    repository = os.environ.get(
        "HANDBOOK_REPOSITORY", "mouteee/autonomous-offensive-llm-handbook"
    )
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise ValueError("HANDBOOK_REPOSITORY should be owner/repository")
    revision = quote(os.environ.get("HANDBOOK_REF", "main"), safe="")
    source_base = f"https://github.com/{repository}/blob/{revision}/"
    chapters = render_all(ROOT)
    chapters.pop("rendered/README.md")
    destinations = {
        source: source.replace("rendered/", "chapters/", 1) for source in chapters
    }
    destinations.update({
        "README.md": "index.md",
        "rendered/README.md": "index.md",
        "docs/BUILD_ROADMAP.md": "roadmap.md",
        "docs/CONNECT_YOUR_MODEL.md": "connect-your-model.md",
    })
    assets = {
        "docs/assets/control-boundary.svg": "assets/control-boundary.svg",
        "docs/assets/autonomous-agent.png": "assets/autonomous-agent.png",
        "docs/stylesheets/handbook.css": "assets/handbook.css",
    }
    for figure in sorted((ROOT / "docs" / "assets" / "course").glob("*.svg")):
        relative = figure.relative_to(ROOT).as_posix()
        assets[relative] = relative.replace("docs/assets/", "assets/", 1)

    def rewrite(text, source, destination):
        def replace(found):
            url = urlsplit(found["url"])
            if url.scheme or url.netloc or not url.path:
                return found[0]
            relative = posixpath.normpath(posixpath.join(
                posixpath.dirname(source), url.path
            ))
            path = (ROOT / relative).resolve()
            if not path.is_relative_to(ROOT) or not path.exists():
                raise ValueError(f"Missing or escaping link in {source}: {url.path}")
            local = destinations.get(relative) or assets.get(relative)
            if local:
                target = posixpath.relpath(local, posixpath.dirname(destination) or ".")
            else:
                target = source_base + quote(relative, safe="/")
            return "](" + urlunsplit(("", "", target, url.query, url.fragment)) + ")"

        result = []
        fence = None
        for line in text.splitlines(keepends=True):
            marker = re.match(r"^\s*(`{3,}|~{3,})", line)
            if marker:
                run = marker[1]
                if fence is None:
                    fence = run
                elif run[0] == fence[0] and len(run) >= len(fence):
                    fence = None
                result.append(line)
            else:
                result.append(line if fence else LINK.sub(replace, line))
        return "".join(result)

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    marker = "\n## The chapters\n"
    if marker not in readme:
        raise ValueError("README is missing the website introduction boundary")
    pages = {"README.md": readme.split(marker, 1)[0] + "\n"}
    pages["docs/BUILD_ROADMAP.md"] = (ROOT / "docs/BUILD_ROADMAP.md").read_text(encoding="utf-8")
    pages["docs/CONNECT_YOUR_MODEL.md"] = (ROOT / "docs/CONNECT_YOUR_MODEL.md").read_text(encoding="utf-8")
    pages.update(chapters)
    rendered = {
        destinations[source]: rewrite(content, source, destinations[source])
        for source, content in pages.items()
    }
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir()
    for destination, content in rendered.items():
        path = STAGE / destination
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    for source, destination in assets.items():
        path = STAGE / destination
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / source, path)
    print(f"Prepared {len(rendered)} reading pages in {STAGE.name}/")


if __name__ == "__main__":
    prepare()
