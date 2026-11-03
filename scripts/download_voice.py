#!/usr/bin/env python3
"""Descarga una voz de Piper desde Hugging Face.

Uso:
    python scripts/download_voice.py                      # voz por defecto
    python scripts/download_voice.py es_MX-claude-high    # otra voz
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from springtrap import config  # noqa: E402

BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def url_for(key: str, extension: str) -> str:
    locale, name, quality = key.split("-", 2)
    language = locale.split("_")[0]
    path = f"{language}/{locale}/{name}/{quality}/{key}.onnx{extension}"
    return f"{BASE}/{path}"


def download(url: str, destination: Path) -> None:
    with requests.get(url, stream=True, timeout=(10, 300)) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        done = 0
        last_shown = -10
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 16):
                handle.write(chunk)
                done += len(chunk)
                if total:
                    percent = done * 100 // total
                    if percent >= last_shown + 10:
                        last_shown = percent
                        print(f"\r  {destination.name}: {percent}%", end="", flush=True)
    print()


def main() -> int:
    key = sys.argv[1] if len(sys.argv) > 1 else config.VOICE_KEY
    config.VOICES_DIR.mkdir(parents=True, exist_ok=True)

    for extension in ("", ".json"):
        destination = config.VOICES_DIR / f"{key}.onnx{extension}"
        if destination.exists():
            print(f"Ya existe: {destination.name}")
            continue
        url = url_for(key, extension)
        print(f"Descargando {url}")
        try:
            download(url, destination)
        except requests.HTTPError as exc:
            print(f"Error: {exc} (¿existe la voz '{key}'?)")
            return 1

    print(f"Voz lista en {config.VOICES_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
