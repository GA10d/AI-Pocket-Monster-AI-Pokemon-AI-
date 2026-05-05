from __future__ import annotations

import random
from typing import Callable, Optional

from ai_providers import Model
from game_log import GameLog
from game_models import BattleState, DamageJudgement, DamageRule, Monster, TurnResult


class BattleEngine:
    def __init__(
        self,
        model: Optional[Model] = None,
        log: Optional[GameLog] = None,
        damage_rule: Optional[DamageRule] = None,
        rng: Optional[random.Random] = None,
        progress: Optional[Callable[[str], None]] = None,
        turn_callback: Optional[Callable[[TurnResult, BattleState], None]] = None,
    ):
        self.model = model or Model()
        self.log = log or GameLog()
        self.damage_rule = damage_rule or DamageRule()
        self.rng = rng or random.Random()
        self.progress = progress or (lambda message: None)
        self.turn_callback = turn_callback or (lambda result, state: None)

    def create_state(self, monster_a: Monster, monster_b: Monster) -> BattleState:
        first = "playerA" if self.rng.random() > 0.5 else "playerB"
        self.log.update("游戏开始初始化")
        self.log.update(f"{first}先手")
        self.progress(f"对战初始化完成，{first} 先手")
        return BattleState(
            monsters={
                "playerA": monster_a,
                "playerB": monster_b,
            },
            active_player=first,
        )

    def run(self, state: BattleState, max_turns: int = 50) -> str:
        while not state.is_over and state.turn <= max_turns:
            attacker = state.attacker()
            skill_index = self.rng.randint(0, len(attacker.skills) - 1)
            self.progress(f"第 {state.turn} 回合：{attacker.player} 准备行动")
            self.play_turn(state, skill_index)
        if not state.winner:
            state.winner = max(state.monsters.values(), key=lambda monster: monster.hp).player
            self.log.update(f"达到最大回合数，{state.winner} 以剩余血量优势获胜")
            self.progress(f"达到最大回合数，{state.winner} 以剩余血量优势获胜")
        return state.winner

    def play_turn(self, state: BattleState, skill_index: int) -> TurnResult:
        attacker = state.attacker()
        defender = state.defender()
        skill = attacker.skills[skill_index]

        self.log.update(f"{attacker.player} 释放了技能：{skill.name}", attacker.player)
        self.progress(f"第 {state.turn} 回合：{attacker.name} 使用 {skill.name}")
        narration = self._narrate(attacker, defender, skill)
        self.log.update(narration, attacker.player)
        self.progress(f"第 {state.turn} 回合：旁白生成完成")

        judgement = self._judge(attacker, defender, skill, narration)
        damage = self.damage_rule.calculate(judgement, skill, self.rng)
        defender.apply_damage(damage)
        self.progress(f"第 {state.turn} 回合：{defender.name} 受到 {damage} 点伤害，剩余 HP {defender.hp}")

        self.log.update(f"{defender.name} 受到{damage}点伤害", defender.player)
        result = TurnResult(
            turn=state.turn,
            attacker=attacker.player,
            defender=defender.player,
            skill=skill,
            narration=narration,
            judgement=judgement,
            damage=damage,
            defender_hp=defender.hp,
        )

        if defender.alive:
            self.log.update(f"{defender.name} 剩余血量：{defender.hp}", defender.player)
            state.history.append(result)
            self.turn_callback(result, state)
            state.advance()
        else:
            state.winner = attacker.player
            result.winner = attacker.player
            state.history.append(result)
            self.log.update(f"{attacker.name} 获胜")
            self.progress(f"战斗结束：{attacker.player}（{attacker.name}）获胜")
            self.turn_callback(result, state)
        return result

    def _narrate(self, attacker: Monster, defender: Monster, skill) -> str:
        system = (
            "你是一场原创宝可梦对战的游戏裁判兼旁白。"
            "根据双方设定和技能，写出本回合战斗过程。不要给出数值伤害。"
        )
        messages = [
            {"role": "user", "content": f"攻击方：{attacker.name}\n描述：{attacker.description}\n技能列表：\n{attacker.skill_block()}"},
            {"role": "user", "content": f"防守方：{defender.name}\n描述：{defender.description}\n技能列表：\n{defender.skill_block()}"},
            {"role": "user", "content": f"{attacker.name} 使用技能 {skill.name}：{skill.description}"},
        ]
        return self.model.provider.chat(messages, system=system, temperature=0.9, max_tokens=900).strip()

    def _judge(self, attacker: Monster, defender: Monster, skill, narration: str) -> DamageJudgement:
        system = "你是游戏裁判。只回答“优势”或“劣势”。不要解释。"
        messages = [
            {"role": "user", "content": f"攻击方：{attacker.name}\n描述：{attacker.description}"},
            {"role": "user", "content": f"防守方：{defender.name}\n描述：{defender.description}"},
            {"role": "user", "content": f"技能：{skill.name}\n描述：{skill.description}\n战斗过程：{narration}"},
        ]
        judgement_text = self.model.provider.chat(messages, system=system, temperature=0.1, max_tokens=20)
        return DamageJudgement.from_text(judgement_text)
