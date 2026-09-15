"""Read public package metadata for the pinned T01 candidates; no installation."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs/技术方案/契约/t01-toolchain-baseline.json"


def check(item: tuple[str, str, str]) -> dict:
    name, version, url = item
    try:
        with urlopen(url, timeout=25) as response:
            body = json.load(response)
        info = body.get("info", body)
        return {
            "name": name,
            "version": version,
            "url": url,
            "available": True,
            "engines": info.get("engines"),
            "requiresPython": info.get("requires_python"),
            "peerDependencies": info.get("peerDependencies"),
        }
    except (HTTPError, URLError, TimeoutError) as error:
        return {
            "name": name,
            "version": version,
            "url": url,
            "available": False,
            "error": str(error),
        }


def main() -> int:
    config = json.loads(BASELINE.read_text(encoding="utf-8"))
    items = [
        (name, version, f"https://registry.npmjs.org/{quote(name, safe='')}/{version}")
        for name, version in config["frontend"].items()
    ]
    items += [
        (
            "pnpm",
            config["tools"]["pnpm"],
            f"https://registry.npmjs.org/pnpm/{config['tools']['pnpm']}",
        )
    ]
    packages = config["backend"] | config["backendDev"] | {"uv": config["tools"]["uv"]}
    items += [
        (name, version, f"https://pypi.org/pypi/{name}/{version}/json")
        for name, version in packages.items()
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, items))
    destination = ROOT / "docs/开发记录/t01-package-metadata.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for result in results:
        print(
            result["name"],
            result["version"],
            "available" if result["available"] else result["error"],
        )
    return 0 if all(r["available"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
