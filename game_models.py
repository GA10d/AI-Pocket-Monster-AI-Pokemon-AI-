from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class SkillCategory(str, Enum):
    ATTACK = "attack"
    DEFENSE = "defense"
    SUPPORT = "support"
    CONTROL = "control"


class DamageJudgement(str, Enum):
    ADVANTAGE = "优势"
    DISADVANTAGE = "劣势"
    NEUTRAL = "普通"

    @classmethod
    def from_text(cls, text: str) -> "DamageJudgement":
        if "优势" in text:
            return cls.ADVANTAGE
        if "劣势" in text:
            return cls.DISADVANTAGE
        return cls.NEUTRAL


@dataclass
class Skill:
    name: str
    description: str
    element: str = "normal"
    category: SkillCategory = SkillCategory.ATTACK
    power: int = 40
    accuracy: float = 0.95
    effect: str = ""
    icon_path: Optional[Path] = None

    @classmethod
    def from_dict(cls, data: Dict) -> "Skill":
        category = data.get("category", SkillCategory.ATTACK.value)
        try:
            category = SkillCategory(category)
        except ValueError:
            category = SkillCategory.ATTACK
        return cls(
            name=str(data.get("name", "")).strip(),
            description=str(data.get("description", "")).strip(),
            element=str(data.get("element", "normal")).strip() or "normal",
            category=category,
            power=_clamp_int(data.get("power", 40), 1, 100),
            accuracy=_clamp_float(data.get("accuracy", 0.95), 0.1, 1.0),
            effect=str(data.get("effect", "")).strip(),
        )

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "element": self.element,
            "category": self.category.value,
            "power": self.power,
            "accuracy": self.accuracy,
            "effect": self.effect,
            "icon_path": str(self.icon_path) if self.icon_path else None,
        }


@dataclass
class Monster:
    player: str
    name: str
    description: str
    max_hp: int = 100
    hp: int = 100
    skills: List[Skill] = field(default_factory=list)
    image_paths: List[Path] = field(default_factory=list)

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def apply_damage(self, damage: int) -> None:
        self.hp = max(0, self.hp - damage)

    def skill_block(self) -> str:
        return "\n".join(
            f"{index}. {skill.name}: {skill.description} "
            f"(element={skill.element}, category={skill.category.value}, power={skill.power})"
            for index, skill in enumerate(self.skills)
        )


@dataclass(frozen=True)
class DamageBand:
    low: int
    high: int

    def roll(self, rng: random.Random) -> int:
        return rng.randint(self.low, self.high)


@dataclass(frozen=True)
class DamageRule:
    advantage: DamageBand = DamageBand(20, 40)
    neutral: DamageBand = DamageBand(8, 28)
    disadvantage: DamageBand = DamageBand(1, 15)
    min_power_scale: float = 0.7
    max_power_scale: float = 1.35

    def calculate(self, judgement: DamageJudgement, skill: Skill, rng: random.Random) -> int:
        band = {
            DamageJudgement.ADVANTAGE: self.advantage,
            DamageJudgement.DISADVANTAGE: self.disadvantage,
            DamageJudgement.NEUTRAL: self.neutral,
        }[judgement]
        base_damage = band.roll(rng)
        power_scale = max(self.min_power_scale, min(self.max_power_scale, skill.power / 45))
        if skill.category in {SkillCategory.DEFENSE, SkillCategory.SUPPORT}:
            power_scale *= 0.75
        return max(1, round(base_damage * power_scale))


@dataclass
class TurnAction:
    player: str
    skill_index: int


@dataclass
class TurnResult:
    turn: int
    attacker: str
    defender: str
    skill: Skill
    narration: str
    judgement: DamageJudgement
    damage: int
    defender_hp: int
    winner: Optional[str] = None


@dataclass
class BattleState:
    monsters: Dict[str, Monster]
    active_player: str
    turn: int = 1
    winner: Optional[str] = None
    history: List[TurnResult] = field(default_factory=list)

    @property
    def is_over(self) -> bool:
        return self.winner is not None

    def attacker(self) -> Monster:
        return self.monsters[self.active_player]

    def defender(self) -> Monster:
        other = "playerB" if self.active_player == "playerA" else "playerA"
        return self.monsters[other]

    def advance(self) -> None:
        self.active_player = "playerB" if self.active_player == "playerA" else "playerA"
        self.turn += 1


def _clamp_int(value, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = low
    return max(low, min(high, number))


def _clamp_float(value, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = low
    return max(low, min(high, number))
