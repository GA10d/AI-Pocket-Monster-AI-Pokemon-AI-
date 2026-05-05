from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Callable

from ai_providers import Model
from art_styles import DEFAULT_STYLE_ID
from battle_engine import BattleEngine
from game_log import GameLog
from monster_builder import MonsterBuilder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an AI Pokemon battle.")
    parser.add_argument("--player-a", default="playerA.txt")
    parser.add_argument("--player-b", default="playerB.txt")
    parser.add_argument("--log-path", default="game_log.txt")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--no-images", action="store_true", help="Skip monster and skill icon generation.")
    parser.add_argument("--text-provider", default=None, help="openai/deepseek/gemini/qwen/doubao")
    parser.add_argument("--image-provider", default=None, help="openai/gemini")
    parser.add_argument("--text-speed", choices=["standard", "fast"], default=None)
    parser.add_argument("--image-speed", choices=["standard", "fast"], default=None)
    parser.add_argument("--art-style", default=DEFAULT_STYLE_ID, help="Art style id from art_styles.json.")
    return parser.parse_args()


def run_game(
    player_a: str = "playerA.txt",
    player_b: str = "playerB.txt",
    player_a_name: str | None = None,
    player_a_description: str | None = None,
    player_b_name: str | None = None,
    player_b_description: str | None = None,
    log_path: str | Path = "game_log.txt",
    seed: int | None = None,
    no_images: bool = False,
    text_provider: str | None = None,
    image_provider: str | None = None,
    text_speed: str | None = None,
    image_speed: str | None = None,
    art_style: str = DEFAULT_STYLE_ID,
    progress: Callable[[str], None] | None = None,
    battle_ready: Callable | None = None,
    turn_update: Callable | None = None,
) -> str:
    progress = progress or (lambda message: None)
    rng = random.Random(seed)
    progress("初始化模型 provider")
    model = Model(
        provider=text_provider,
        image_provider=image_provider,
        text_speed=text_speed,
        image_speed=image_speed,
    )
    progress(
        f"文本模型：{model.provider.text_config.name} / {model.provider.text_speed} / {model.provider.text_model}"
    )
    if model.provider.image_config:
        progress(
            f"图片模型：{model.provider.image_config.name} / {model.provider.image_speed} / {model.provider.image_model}"
        )
    log = GameLog(Path(log_path))
    log.clear()
    log.update("游戏开始")
    progress("游戏日志已清空，开始生成宝可梦")

    builder = MonsterBuilder(
        model=model,
        log=log,
        generate_images=not no_images,
        generate_skill_icons=not no_images,
        art_style_id=art_style,
        progress=progress,
    )
    if player_a_name is not None or player_a_description is not None:
        monster_a = builder.build_from_profile(
            "playerA",
            player_a_name or "playerA",
            player_a_description or "",
            source_path=Path(player_a),
        )
    else:
        monster_a = builder.build_from_file(player_a)

    if player_b_name is not None or player_b_description is not None:
        monster_b = builder.build_from_profile(
            "playerB",
            player_b_name or "playerB",
            player_b_description or "",
            source_path=Path(player_b),
        )
    else:
        monster_b = builder.build_from_file(player_b)

    progress("双方宝可梦生成完成，进入对战")
    engine = BattleEngine(model=model, log=log, rng=rng, progress=progress, turn_callback=turn_update)
    state = engine.create_state(monster_a, monster_b)
    if battle_ready:
        battle_ready(monster_a, monster_b, state)
    winner = engine.run(state)
    log.write()
    progress(f"日志已写入 {log.path}")
    return winner


def main() -> str:
    args = parse_args()
    winner = run_game(
        player_a=args.player_a,
        player_b=args.player_b,
        log_path=args.log_path,
        seed=args.seed,
        no_images=args.no_images,
        text_provider=args.text_provider,
        image_provider=args.image_provider,
        text_speed=args.text_speed,
        image_speed=args.image_speed,
        art_style=args.art_style,
    )
    print(f"{winner} win!")
    return winner


if __name__ == "__main__":
    main()
