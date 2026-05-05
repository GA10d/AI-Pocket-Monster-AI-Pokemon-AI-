from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List


ROOT = Path(__file__).resolve().parent
DEFAULT_STYLE_ID = "pixel-8bit"


@dataclass(frozen=True)
class ArtStyle:
    id: str
    name: str
    prompt: str


def load_art_styles(path: Path = ROOT / "art_styles.json") -> List[ArtStyle]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ArtStyle(**item) for item in data.get("styles", [])]


def get_art_style(style_id: str = DEFAULT_STYLE_ID, path: Path = ROOT / "art_styles.json") -> ArtStyle:
    styles = load_art_styles(path)
    for style in styles:
        if style.id == style_id:
            return style
    available = ", ".join(style.id for style in styles)
    raise ValueError(f"Unknown art style '{style_id}'. Available styles: {available}")


def style_ids(path: Path = ROOT / "art_styles.json") -> List[str]:
    return [style.id for style in load_art_styles(path)]
