from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
from PIL import Image

from ai_providers import Model
from art_styles import DEFAULT_STYLE_ID, ArtStyle, get_art_style
from game_log import GameLog
from game_models import Monster, Skill


ROOT = Path(__file__).resolve().parent
TRANSPARENT_ASSET_PROMPT = (
    "transparent background, isolated subject, no scenery, no frame, no border, "
    "no text, no watermark, clean cutout game asset"
)


class MonsterBuilder:
    def __init__(
        self,
        model: Optional[Model] = None,
        log: Optional[GameLog] = None,
        root: Path = ROOT,
        generate_images: bool = True,
        generate_skill_icons: bool = True,
        art_style_id: str = DEFAULT_STYLE_ID,
        art_style: Optional[ArtStyle] = None,
        progress: Optional[Callable[[str], None]] = None,
    ):
        self.model = model or Model()
        self.log = log or GameLog()
        self.root = root
        self.generate_images = generate_images
        self.generate_skill_icons = generate_skill_icons
        self.art_style = art_style or get_art_style(art_style_id)
        self.progress = progress or (lambda message: None)

    def build_from_file(self, filename: str | Path) -> Monster:
        path = self.root / filename
        player = path.stem
        name, description = self._read_player_file(path)
        return self.build_from_profile(player, name, description, source_path=path)

    def build_from_profile(
        self,
        player: str,
        name: str,
        description: str = "",
        source_path: Optional[Path] = None,
    ) -> Monster:
        name = name.strip()
        description = description.strip()
        if not name:
            raise ValueError(f"{player} must have a monster name.")
        self.progress(f"{player}: 读取配置 - {name}")
        if not description:
            self.progress(f"{player}: 描述为空，正在调用 AI 补全设定")
            description = self.generate_description(name)
            self.log.update(f"检测到{player}没有写描述，已自动生成描述。")
            self.progress(f"{player}: AI 描述生成完成")
        else:
            self.progress(f"{player}: 使用玩家输入的描述")
        if source_path:
            source_path.write_text(f"{name}\n{description}\n", encoding="utf-8")
            self.progress(f"{player}: 已写入 {source_path.name}")

        monster = Monster(player=player, name=name, description=description)
        self.log.update(f"{player} 玩家信息已录入")
        self.log.update(f"{player} 宝可梦名字：{name}已录入")
        self.log.update(f"{player} 宝可梦初始描述已录入")
        self.log.update(f"{player} 图片风格：{self.art_style.name}")

        output_dir = self.root / player
        output_dir.mkdir(exist_ok=True)
        if self.generate_images:
            image_path = self.generate_monster_image(monster, output_dir)
            monster.image_paths.append(image_path)
        else:
            self.progress(f"{player}: 跳过怪物图片生成")
        monster.skills = self.generate_skills(monster, output_dir)
        if self.generate_images and self.generate_skill_icons:
            self.generate_icons(monster, output_dir)
        elif not self.generate_images:
            self.progress(f"{player}: 跳过技能图标生成")
        return monster

    def generate_description(self, name: str) -> str:
        prompt = (
            "请为一个将在虚构竞技场中战斗的原创宝可梦写一段人物小传。"
            "它可能是幻想生物，也可能来自日常物品。"
            f"宝可梦名字：{name}"
        )
        return self.model.generator_model(prompt).replace("\n", "").strip()

    def generate_monster_image(self, monster: Monster, output_dir: Path) -> Path:
        self.progress(f"{monster.player}: 正在生成怪物图片 prompt")
        prompt = (
            "Transform the following monster description into an English image prompt. "
            "Use comma-separated keywords only, no extra prose. "
            f"Target art direction: {self.art_style.prompt}. "
            f"Asset requirements: {TRANSPARENT_ASSET_PROMPT}. "
            f"Name: {monster.name}. Description: {monster.description}"
        )
        image_prompt = self.model.generator_model(prompt)
        self.progress(f"{monster.player}: 正在生成怪物图片")
        image = self.model.image_model(
            image_prompt,
            style=f"{self.art_style.prompt}, single character, only one character, {TRANSPARENT_ASSET_PROMPT}",
        )
        image_path = output_dir / f"{monster.player}_image1.png"
        _save_image(image, image_path)
        _save_image(image, output_dir / f"{monster.player}_image1.jpeg")
        self.log.update(f"{image_path} 宝可梦图片已录入")
        self.progress(f"{monster.player}: 怪物图片已保存 {image_path.name}")
        return image_path

    def generate_skills(self, monster: Monster, output_dir: Path) -> List[Skill]:
        self.progress(f"{monster.player}: 正在生成技能 JSON")
        payload = self._ask_for_skill_json(monster)
        raw_skills = payload.get("skills", [])
        if not isinstance(raw_skills, list) or len(raw_skills) != 3:
            raise ValueError("AI skill response must contain exactly 3 skills.")

        skills = [Skill.from_dict(item) for item in raw_skills]
        for index, skill in enumerate(skills, start=1):
            if not skill.name or not skill.description:
                raise ValueError(f"Skill {index} is missing name or description.")

        json_path = output_dir / f"{monster.player}_skill.json"
        json_path.write_text(
            json.dumps({"skills": [skill.to_dict() for skill in skills]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        legacy_txt = "\n\n".join(f"[{skill.name}]: {skill.description}" for skill in skills)
        (output_dir / f"{monster.player}_skill.txt").write_text(legacy_txt + "\n", encoding="utf-8")
        self.log.update(f"{monster.player} 技能 JSON 已生成")
        self.progress(f"{monster.player}: 技能生成完成 - " + " / ".join(skill.name for skill in skills))
        return skills

    def generate_icons(self, monster: Monster, output_dir: Path) -> None:
        for index, skill in enumerate(monster.skills, start=1):
            self.progress(f"{monster.player}: 正在生成技能图标 {index}/3 - {skill.name}")
            prompt = (
                "Create an English comma-separated image prompt for a square game skill icon. "
                f"Target art direction: {self.art_style.prompt}. "
                f"Asset requirements: {TRANSPARENT_ASSET_PROMPT}. "
                f"Skill name: {skill.name}. Description: {skill.description}. "
                f"Element: {skill.element}. Category: {skill.category.value}."
            )
            image_prompt = self.model.generator_model(prompt)
            icon = self.model.image_model(image_prompt, style=f"{self.art_style.prompt}, skill icon, {TRANSPARENT_ASSET_PROMPT}")
            icon_path = output_dir / f"{monster.player}_skill_icon{index}.png"
            _save_image(icon, icon_path)
            _save_image(icon, output_dir / f"{monster.player}_skill_icon{index}.jpeg")
            skill.icon_path = icon_path
            self.log.update(f"{monster.player} 生成了第{index}个技能图片（{icon_path.name}）")
            self.progress(f"{monster.player}: 技能图标已保存 {icon_path.name}")

    def _ask_for_skill_json(self, monster: Monster) -> Dict:
        system = (
            "你是宝可梦式技能设计师。只输出合法 JSON，不要 markdown，不要解释。"
            "JSON 顶层必须是对象，包含 skills 数组，数组长度必须为 3。"
        )
        user = f"""
请根据宝可梦名字和描述生成 3 个技能。

字段要求：
- name: 中文技能名
- description: 中文技能描述，不要写具体伤害数字
- element: 技能属性，例如 fire/water/electric/grass/psychic/normal
- category: 只能是 attack、defense、support、control
- power: 1 到 100 的整数，辅助/防御技能也需要给一个较低数值
- accuracy: 0.1 到 1.0 的小数
- effect: 简短效果标签或说明

宝可梦名字：{monster.name}
宝可梦描述：{monster.description}

输出示例：
{{
  "skills": [
    {{
      "name": "技能名",
      "description": "技能描述",
      "element": "normal",
      "category": "attack",
      "power": 40,
      "accuracy": 0.95,
      "effect": "brief effect"
    }}
  ]
}}
"""
        messages = [{"role": "user", "content": user}]
        for attempt in range(2):
            text = self.model.provider.chat(messages, system=system, temperature=0.65, max_tokens=1200)
            try:
                return _extract_json_object(text)
            except ValueError:
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": "上一条不是合法 JSON。请只重新输出合法 JSON 对象。"})
        raise ValueError("AI did not return valid skill JSON.")

    @staticmethod
    def _read_player_file(path: Path) -> tuple[str, str]:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or not lines[0].strip():
            raise ValueError(f"{path} must contain a monster name on the first line.")
        name = lines[0].strip()
        description = "\n".join(line.strip() for line in lines[1:] if line.strip())
        return name, description


def _extract_json_object(text: str) -> Dict:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.lower().startswith("json"):
            candidate = candidate[4:].strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found.")
    try:
        data = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON object.") from exc
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object.")
    return data


def _save_image(image: np.ndarray, path: Path) -> None:
    array = np.asarray(image)
    if array.dtype.kind == "f":
        array = np.clip(array * 255, 0, 255).astype("uint8")
    elif array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype("uint8")
    pil_image = Image.fromarray(array)
    if path.suffix.lower() in {".jpg", ".jpeg"} and pil_image.mode in {"RGBA", "LA"}:
        background = Image.new("RGB", pil_image.size, (255, 255, 255))
        background.paste(pil_image, mask=pil_image.getchannel("A"))
        pil_image = background
    pil_image.save(path)
