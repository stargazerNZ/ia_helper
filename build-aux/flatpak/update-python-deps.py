#!/usr/bin/env python3
"""Regenerate python3-internetarchive.json (the pinned Flatpak dep module).

Works like flatpak-pip-generator but is OS-independent: it pins
platform-neutral artifacts (py3-none-any wheels, sdist fallback) from the
PyPI JSON API. Run it when the internetarchive dependency tree changes,
review the printed pins, and commit the result.

Keep PACKAGES in sync with `pip install --dry-run --report` output for
`internetarchive` (Linux markers: no colorama, no importlib-metadata on
Python > 3.10). Entries with version None pin the latest release.
"""

import json
import urllib.request
from pathlib import Path

PACKAGES = [
    ("certifi", None),
    ("charset-normalizer", None),
    ("idna", None),
    ("urllib3", None),
    ("jsonpointer", None),
    ("jsonpatch", None),
    ("tqdm", None),
    ("requests", None),
    ("internetarchive", None),
]

UA = {"User-Agent": "IAHelper build tooling (flatpak dep pinning)"}
OUTPUT = Path(__file__).with_name("python3-internetarchive.json")


def pypi_json(name, version=None):
    url = f"https://pypi.org/pypi/{name}/json" if version is None \
        else f"https://pypi.org/pypi/{name}/{version}/json"
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    sources = []
    for name, version in PACKAGES:
        if version is None:
            version = pypi_json(name)["info"]["version"]
        files = pypi_json(name, version)["urls"]
        wheel = next(
            (f for f in files if f["filename"].endswith("py3-none-any.whl")), None
        )
        chosen = wheel or next(f for f in files if f["packagetype"] == "sdist")
        sources.append(
            {"type": "file", "url": chosen["url"], "sha256": chosen["digests"]["sha256"]}
        )
        print(f"  {name}=={version}: {chosen['filename']}")

    module = {
        "name": "python3-internetarchive",
        "buildsystem": "simple",
        "build-commands": [
            (
                "pip3 install --verbose --exists-action=i --no-index "
                '--find-links="file://${PWD}" --prefix=${FLATPAK_DEST} '
                '"internetarchive" --no-build-isolation'
            )
        ],
        "sources": sources,
    }
    OUTPUT.write_text(json.dumps(module, indent=4) + "\n")
    print(f"\nwrote {OUTPUT}")


if __name__ == "__main__":
    main()
