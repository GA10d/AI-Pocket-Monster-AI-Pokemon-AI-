from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List


@dataclass
class GameLog:
    path: Path = Path("game_log.txt")
    entries: List[str] = field(default_factory=list)

    def update(self, content: str, owner: str = "system") -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.entries.append(f"[{timestamp}]: [{owner}]: {content}")

    def clear(self) -> None:
        self.entries.clear()

    def print(self) -> None:
        for entry in self.entries:
            print(entry)

    def write(self) -> None:
        self.path.write_text("\n".join(self.entries) + "\n", encoding="utf-8")
