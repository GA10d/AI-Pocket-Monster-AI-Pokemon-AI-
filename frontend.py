from __future__ import annotations

import argparse
import math
import os
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import pygame

from art_styles import ArtStyle, load_art_styles
from main import run_game


ROOT = Path(__file__).resolve().parent
WIDTH = 980
HEIGHT = 640
FPS = 60

BG = (32, 37, 38)
BG_2 = (44, 50, 46)
INK = (31, 32, 34)
MUTED = (104, 108, 112)
TEAL = (30, 155, 146)
TEAL_DARK = (13, 91, 88)
CORAL = (226, 84, 68)
YELLOW = (244, 188, 65)
PANEL = (255, 249, 232)
BORDER = (35, 39, 42)
DISABLED = (154, 156, 156)
CREAM = (255, 244, 210)
FIELD = (86, 150, 106)
FIELD_DARK = (56, 102, 82)
SKY = (111, 187, 186)

TEXT_PROVIDERS = ["env/default", "openai", "deepseek", "gemini", "qwen", "doubao"]
IMAGE_PROVIDERS = ["env/default", "openai", "gemini"]
MODEL_SPEEDS = ["standard", "fast"]
MODEL_SPEED_LABELS = {
    "standard": "标准",
    "fast": "Fast",
}
NAME_LIMIT = 24
DESCRIPTION_LIMIT = 600


@dataclass
class UISettings:
    style_index: int = 0
    generate_images: bool = True
    text_provider_index: int = 0
    image_provider_index: int = 0
    text_speed_index: int = 0
    image_speed_index: int = 0
    seed_text: str = ""

    def text_provider(self) -> Optional[str]:
        value = TEXT_PROVIDERS[self.text_provider_index]
        return None if value == "env/default" else value

    def image_provider(self) -> Optional[str]:
        value = IMAGE_PROVIDERS[self.image_provider_index]
        return None if value == "env/default" else value

    def text_speed(self) -> str:
        return MODEL_SPEEDS[self.text_speed_index]

    def image_speed(self) -> str:
        return MODEL_SPEEDS[self.image_speed_index]

    def seed(self) -> Optional[int]:
        text = self.seed_text.strip()
        return int(text) if text else None


@dataclass
class PlayerDraft:
    name: str = ""
    description: str = ""


@dataclass
class SkillView:
    name: str
    description: str
    icon_path: Optional[Path]
    element: str
    category: str
    power: int


@dataclass
class MonsterView:
    player: str
    name: str
    hp: int
    max_hp: int
    image_paths: list[Path]
    skills: list[SkillView]


@dataclass
class TurnView:
    turn: int
    attacker: str
    defender: str
    skill_name: str
    narration: str
    judgement: str
    damage: int
    defender_hp: int
    winner: Optional[str]


@dataclass
class Button:
    rect: pygame.Rect
    label: str
    action: Callable[[], None]
    fill: tuple[int, int, int] = TEAL
    text_color: tuple[int, int, int] = (255, 255, 255)
    enabled: bool = True

    def draw(self, screen: pygame.Surface, font: pygame.font.Font, mouse_pos: tuple[int, int]) -> None:
        color = self.fill if self.enabled else DISABLED
        if self.enabled and self.rect.collidepoint(mouse_pos):
            color = _mix(color, (255, 255, 255), 0.18)
        shadow = self.rect.move(0, 5)
        pygame.draw.rect(screen, (16, 18, 18), shadow, border_radius=6)
        pygame.draw.rect(screen, color, self.rect, border_radius=6)
        pygame.draw.rect(screen, _mix(color, (255, 255, 255), 0.28), pygame.Rect(self.rect.x + 5, self.rect.y + 5, self.rect.w - 10, 8), border_radius=3)
        pygame.draw.rect(screen, BORDER, self.rect, width=3, border_radius=6)
        if self.enabled and self.rect.collidepoint(mouse_pos):
            tip = [(self.rect.x + 14, self.rect.centery), (self.rect.x + 26, self.rect.centery - 8), (self.rect.x + 26, self.rect.centery + 8)]
            pygame.draw.polygon(screen, self.text_color, tip)
        text = font.render(self.label, True, self.text_color if self.enabled else (80, 82, 88))
        screen.blit(text, text.get_rect(center=self.rect.center))

    def click(self, mouse_pos: tuple[int, int]) -> bool:
        if self.enabled and self.rect.collidepoint(mouse_pos):
            self.action()
            return True
        return False


class Frontend:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("AI Pokemon")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.clipboard_ready = False
        try:
            pygame.scrap.init()
            self.clipboard_ready = True
        except pygame.error:
            self.clipboard_ready = False
        self.styles = load_art_styles()
        self.settings = UISettings()
        self.screen_name = "menu"
        self.running = True
        self.buttons: list[Button] = []
        self.active_field: Optional[str] = None
        self.held_key: Optional[int] = None
        self.held_key_started = 0.0
        self.held_key_last_repeat = 0.0
        self.status = ""
        self.progress_lines: list[str] = []
        self.winner: Optional[str] = None
        self.battle_lock = threading.Lock()
        self.battle_monsters: dict[str, MonsterView] = {}
        self.battle_turns: list[TurnView] = []
        self.battle_winner: Optional[str] = None
        self.image_cache: dict[tuple[str, tuple[int, int]], Optional[pygame.Surface]] = {}
        self.error: Optional[str] = None
        self.worker: Optional[threading.Thread] = None
        self.started_at = 0.0
        self.frame = 0
        self.particles = [
            {
                "x": random.randint(0, WIDTH),
                "y": random.randint(0, HEIGHT),
                "speed": random.uniform(0.25, 1.1),
                "size": random.choice([2, 3, 4]),
                "color": random.choice([TEAL, YELLOW, CORAL, CREAM]),
            }
            for _ in range(72)
        ]
        self.preview_a = _load_first_image([ROOT / "playerA" / "playerA_image1.png", ROOT / "playerA" / "playerA_image1.jpeg"], (230, 230))
        self.preview_b = _load_first_image([ROOT / "playerB" / "playerB_image1.png", ROOT / "playerB" / "playerB_image1.jpeg"], (230, 230))
        self.vs_image = _load_image(ROOT / "image" / "vs.png", (150, 110))
        name_a, desc_a = _read_player_profile(ROOT / "playerA.txt", "playerA")
        name_b, desc_b = _read_player_profile(ROOT / "playerB.txt", "playerB")
        self.player_a = PlayerDraft(name_a, desc_a)
        self.player_b = PlayerDraft(name_b, desc_b)

        self.font_title = _font(52)
        self.font_logo = _font(72)
        self.font_h1 = _font(34)
        self.font_h2 = _font(24)
        self.font_body = _font(18)
        self.font_small = _font(15)

    def run(self) -> None:
        while self.running:
            mouse_pos = pygame.mouse.get_pos()
            self._handle_events(mouse_pos)
            self._draw(mouse_pos)
            pygame.display.flip()
            self.frame += 1
            self.clock.tick(FPS)
        pygame.quit()

    def _handle_events(self, mouse_pos: tuple[int, int]) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._deactivate_field()
                for button in self.buttons:
                    if button.click(mouse_pos):
                        break
            elif event.type == pygame.TEXTINPUT and self.active_field:
                self._append_text(event.text)
            elif event.type == pygame.KEYDOWN:
                if self.active_field:
                    self._handle_field_key(event)
                    self._start_key_repeat(event.key)
                elif event.key == pygame.K_ESCAPE:
                    self.screen_name = "menu"
            elif event.type == pygame.KEYUP:
                if event.key == self.held_key:
                    self._stop_key_repeat()
        self._handle_key_repeat()

    def _handle_field_key(self, event: pygame.event.Event) -> None:
        if event.key == pygame.K_v and event.mod & pygame.KMOD_CTRL:
            self._append_text(self._clipboard_text())
        elif event.key == pygame.K_BACKSPACE:
            self._backspace_once()
        elif event.key in {pygame.K_RETURN, pygame.K_KP_ENTER}:
            if self._is_description_field(self.active_field):
                self._append_text("\n")
            else:
                self._deactivate_field()
        elif event.key == pygame.K_ESCAPE:
            self._deactivate_field()

    def _start_key_repeat(self, key: int) -> None:
        if key != pygame.K_BACKSPACE:
            self._stop_key_repeat()
            return
        now = time.monotonic()
        self.held_key = key
        self.held_key_started = now
        self.held_key_last_repeat = now

    def _stop_key_repeat(self) -> None:
        self.held_key = None
        self.held_key_started = 0.0
        self.held_key_last_repeat = 0.0

    def _handle_key_repeat(self) -> None:
        if self.held_key != pygame.K_BACKSPACE or not self.active_field:
            return
        now = time.monotonic()
        if now - self.held_key_started < 0.32:
            return
        if now - self.held_key_last_repeat >= 0.045:
            self._backspace_once()
            self.held_key_last_repeat = now

    def _backspace_once(self) -> None:
        self._set_field_value(self._field_value(self.active_field)[:-1])

    def _append_text(self, text: str) -> None:
        if not self.active_field or not text:
            return
        if self.active_field == "seed":
            text = "".join(ch for ch in text if ch.isdigit())
            limit = 9
        elif self.active_field.endswith("_name"):
            text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
            limit = NAME_LIMIT
        else:
            text = text.replace("\r", "")
            limit = DESCRIPTION_LIMIT
        value = self._field_value(self.active_field) + text
        self._set_field_value(value[:limit])

    def _draw(self, mouse_pos: tuple[int, int]) -> None:
        _draw_pixel_background(self.screen, self.particles, self.frame)
        self.buttons = []
        if self.screen_name == "menu":
            self._draw_menu(mouse_pos)
        elif self.screen_name == "monster_setup":
            self._draw_monster_setup(mouse_pos)
        elif self.screen_name == "settings":
            self._draw_settings(mouse_pos)
        elif self.screen_name == "running":
            self._draw_running(mouse_pos)
        elif self.screen_name == "battle":
            self._draw_battle(mouse_pos)
        elif self.screen_name == "result":
            self._draw_result(mouse_pos)
        elif self.screen_name == "error":
            self._draw_error(mouse_pos)
        _draw_scanlines(self.screen)

    def _draw_menu(self, mouse_pos: tuple[int, int]) -> None:
        style = self.current_style()
        _text_center(self.screen, self.font_logo, "AI POKEMON", (WIDTH // 2, 72), CREAM)
        _text_center(self.screen, self.font_body, "原创怪物生成  /  AI 裁判对战  /  游戏画风可选", (WIDTH // 2, 126), (207, 218, 199))

        arena = pygame.Rect(58, 158, 864, 334)
        _draw_arena(self.screen, arena)
        _draw_fighter_card(self.screen, pygame.Rect(92, 190, 275, 260), self.player_a.name, "PLAYER A", self.preview_a, flip=False)
        _draw_fighter_card(self.screen, pygame.Rect(613, 190, 275, 260), self.player_b.name, "PLAYER B", self.preview_b, flip=True)
        if self.vs_image:
            pulse = 1 + math.sin(self.frame / 16) * 0.04
            vs = pygame.transform.smoothscale(self.vs_image, (round(150 * pulse), round(110 * pulse)))
            self.screen.blit(vs, vs.get_rect(center=(WIDTH // 2, 296)))
        else:
            _text_center(self.screen, self.font_title, "VS", (WIDTH // 2, 296), CORAL)

        _draw_status_strip(self.screen, pygame.Rect(95, 506, 790, 46), [
            f"STYLE {style.name}",
            f"IMG {'ON' if self.settings.generate_images else 'OFF'}",
            f"TEXT {MODEL_SPEED_LABELS[self.settings.text_speed()]}",
            f"IMAGE {MODEL_SPEED_LABELS[self.settings.image_speed()]}",
        ], self.font_small)

        self._button((72, 570, 190, 54), "开始游戏", self.start_game, CORAL, mouse_pos)
        self._button((284, 570, 190, 54), "宝可梦配置", lambda: self._go("monster_setup"), TEAL, mouse_pos)
        self._button((496, 570, 190, 54), "设置", lambda: self._go("settings"), YELLOW, mouse_pos, INK)
        self._button((708, 570, 190, 54), "退出", self._quit, TEAL, mouse_pos)

    def _draw_monster_setup(self, mouse_pos: tuple[int, int]) -> None:
        _text(self.screen, self.font_h1, "MONSTER LAB", (70, 40), CREAM)
        _text(self.screen, self.font_body, "在这里现场输入双方宝可梦。描述可以留空，AI 会根据名字自动补全。", (72, 82), (207, 218, 199))

        left = pygame.Rect(58, 128, 414, 386)
        right = pygame.Rect(508, 128, 414, 386)
        self._draw_player_editor(left, "PLAYER A", self.player_a, "player_a", CORAL, mouse_pos)
        self._draw_player_editor(right, "PLAYER B", self.player_b, "player_b", TEAL, mouse_pos)

        _text(self.screen, self.font_small, "开始游戏会把当前配置写入 playerA.txt / playerB.txt，并立即生成技能、图片和战斗日志。", (76, 534), (207, 218, 199))
        self._button((58, 572, 190, 52), "返回主界面", lambda: self._go("menu"), TEAL, mouse_pos)
        self._button((386, 572, 210, 52), "开始游戏", self.start_game, CORAL, mouse_pos)
        self._button((730, 572, 190, 52), "设置", lambda: self._go("settings"), YELLOW, mouse_pos, INK)

    def _draw_player_editor(
        self,
        rect: pygame.Rect,
        title: str,
        draft: PlayerDraft,
        prefix: str,
        accent: tuple[int, int, int],
        mouse_pos: tuple[int, int],
    ) -> None:
        _panel(self.screen, rect, fill=PANEL)
        tag = pygame.Rect(rect.x + 24, rect.y + 22, 132, 32)
        pygame.draw.rect(self.screen, accent, tag, border_radius=5)
        pygame.draw.rect(self.screen, BORDER, tag, width=2, border_radius=5)
        _text_center(self.screen, self.font_small, title, tag.center, (255, 255, 255))

        _text(self.screen, self.font_small, "名字", (rect.x + 28, rect.y + 76), MUTED)
        self._input_field(
            pygame.Rect(rect.x + 28, rect.y + 100, rect.w - 56, 42),
            f"{prefix}_name",
            draft.name,
            "输入宝可梦名字",
            mouse_pos,
        )

        _text(self.screen, self.font_small, "描述 / 关键词", (rect.x + 28, rect.y + 166), MUTED)
        self._input_field(
            pygame.Rect(rect.x + 28, rect.y + 190, rect.w - 56, 136),
            f"{prefix}_description",
            draft.description,
            "可留空，例如：火山、金色龙兽、速度很快",
            mouse_pos,
            multiline=True,
        )
        self._button((rect.right - 118, rect.y + 150, 86, 32), "清空", lambda prefix=prefix: self._clear_description(prefix), YELLOW, mouse_pos, INK)

        preview = draft.description.strip() or "AI 将根据名字自动生成完整设定。"
        for index, line in enumerate(_wrap_text_pixels(preview, self.font_small, rect.w - 64)[:2]):
            _text(self.screen, self.font_small, line, (rect.x + 30, rect.bottom - 42 + index * 20), TEAL_DARK)

    def _draw_settings(self, mouse_pos: tuple[int, int]) -> None:
        _text(self.screen, self.font_h1, "BATTLE SETUP", (70, 44), CREAM)
        _text(self.screen, self.font_body, "调整生成画风和模型选项，然后返回主界面开始。", (72, 88), (207, 218, 199))

        y = 128
        style = self.current_style()
        _panel(self.screen, pygame.Rect(58, y, 864, 205), fill=PANEL)
        _text(self.screen, self.font_h2, "生成画风", (90, y + 24), INK)
        _style_chip(self.screen, self.font_h1, style.name, pygame.Rect(90, y + 64, 310, 58))
        _text(self.screen, self.font_small, f"ID: {style.id}", (420, y + 70), TEAL_DARK)
        for index, line in enumerate(_wrap(style.prompt, 68)[:4]):
            _text(self.screen, self.font_small, line, (420, y + 99 + index * 22), MUTED)
        self._button((90, y + 142, 130, 42), "上一个", self.prev_style, YELLOW, mouse_pos, INK)
        self._button((240, y + 142, 130, 42), "下一个", self.next_style, YELLOW, mouse_pos, INK)

        y = 350
        _panel(self.screen, pygame.Rect(58, y, 864, 184), fill=(255, 247, 224))
        _text(self.screen, self.font_h2, "运行选项", (90, y + 22), INK)
        self._button(
            (90, y + 58, 190, 42),
            f"图片：{'开' if self.settings.generate_images else '关'}",
            self.toggle_images,
            TEAL if self.settings.generate_images else DISABLED,
            mouse_pos,
        )
        self._button((318, y + 58, 200, 42), f"文本：{TEXT_PROVIDERS[self.settings.text_provider_index]}", self.next_text_provider, YELLOW, mouse_pos, INK)
        self._button((558, y + 58, 200, 42), f"图片：{IMAGE_PROVIDERS[self.settings.image_provider_index]}", self.next_image_provider, YELLOW, mouse_pos, INK)
        self._button((318, y + 112, 200, 42), f"文本档位：{MODEL_SPEED_LABELS[self.settings.text_speed()]}", self.next_text_speed, TEAL, mouse_pos)
        self._button((558, y + 112, 200, 42), f"图片档位：{MODEL_SPEED_LABELS[self.settings.image_speed()]}", self.next_image_speed, TEAL, mouse_pos)
        _text(self.screen, self.font_small, "Seed", (90, y + 122), MUTED)
        seed_rect = pygame.Rect(145, y + 112, 145, 36)
        pygame.draw.rect(self.screen, (255, 255, 255), seed_rect, border_radius=6)
        pygame.draw.rect(self.screen, TEAL if self.active_field == "seed" else BORDER, seed_rect, width=2, border_radius=6)
        _text(self.screen, self.font_body, self.settings.seed_text or "随机", (168, y + 129), MUTED if not self.settings.seed_text else INK)
        self.buttons.append(Button(seed_rect, "", lambda: self._activate_field("seed"), fill=(255, 255, 255), text_color=INK))

        _text(self.screen, self.font_small, "标准更稳，Fast 更快；AI_TEXT_MODEL / AI_IMAGE_MODEL 会覆盖这里的档位。", (90, y + 162), MUTED)
        self._button((58, 562, 190, 52), "返回主界面", lambda: self._go("menu"), TEAL, mouse_pos)

    def _draw_running(self, mouse_pos: tuple[int, int]) -> None:
        elapsed = int(time.time() - self.started_at)
        dots = "." * ((elapsed % 3) + 1)
        _draw_logo_mark(self.screen, (80, 56))
        _text(self.screen, self.font_h1, f"LOADING BATTLE{dots}", (198, 74), CREAM)
        _text(self.screen, self.font_small, f"耗时 {elapsed}s  /  {self.status}", (202, 118), YELLOW)
        _draw_loading_bar(self.screen, pygame.Rect(198, 146, 560, 28), self.frame)

        log_rect = pygame.Rect(86, 205, 808, 330)
        _panel(self.screen, log_rect, fill=(255, 249, 232))
        _text(self.screen, self.font_h2, "RUN LOG", (log_rect.x + 26, log_rect.y + 22), INK)
        _draw_progress_log(self.screen, self.font_small, self.progress_lines, pygame.Rect(log_rect.x + 28, log_rect.y + 66, log_rect.w - 56, log_rect.h - 92))
        _text_center(self.screen, self.font_small, "正在实时记录生成与对战阶段，请稍等。", (WIDTH // 2, 570), (207, 218, 199))

    def _draw_battle(self, mouse_pos: tuple[int, int]) -> None:
        with self.battle_lock:
            monsters = dict(self.battle_monsters)
            turns = list(self.battle_turns)
            winner = self.battle_winner

        if "playerA" not in monsters or "playerB" not in monsters:
            self._draw_running(mouse_pos)
            return

        monster_a = monsters["playerA"]
        monster_b = monsters["playerB"]
        latest = turns[-1] if turns else None

        _text(self.screen, self.font_h1, "BATTLE FIELD", (58, 32), CREAM)
        if winner:
            _text(self.screen, self.font_h2, f"WINNER  {winner}", (650, 42), YELLOW)
        else:
            _text(self.screen, self.font_small, self.status or "对战进行中", (312, 52), YELLOW)

        arena = pygame.Rect(48, 82, 884, 252)
        _draw_arena(self.screen, arena)
        self._draw_battle_monster(monster_b, pygame.Rect(580, 110, 310, 188), flip=True)
        self._draw_battle_monster(monster_a, pygame.Rect(90, 146, 330, 188), flip=False)
        if self.vs_image:
            self.screen.blit(self.vs_image, self.vs_image.get_rect(center=(WIDTH // 2, 190)))

        text_rect = pygame.Rect(58, 352, 538, 112)
        _panel(self.screen, text_rect, fill=PANEL)
        if latest:
            _text(self.screen, self.font_small, f"第 {latest.turn} 回合  {latest.attacker} 使用 {latest.skill_name}", (text_rect.x + 22, text_rect.y + 18), TEAL_DARK)
            summary = f"{latest.defender} 受到 {latest.damage} 点伤害，剩余 HP {latest.defender_hp}。{latest.narration}"
        else:
            _text(self.screen, self.font_small, "对战即将开始", (text_rect.x + 22, text_rect.y + 18), TEAL_DARK)
            summary = "双方宝可梦已经入场，AI 裁判正在决定第一回合行动。"
        _draw_clipped_lines(
            self.screen,
            self.font_small,
            _wrap_text_pixels(summary, self.font_small, text_rect.w - 44)[:3],
            pygame.Rect(text_rect.x + 22, text_rect.y + 46, text_rect.w - 44, 58),
            INK,
            20,
        )

        log_rect = pygame.Rect(618, 352, 314, 112)
        _panel(self.screen, log_rect, fill=(255, 247, 224))
        _text(self.screen, self.font_small, "LOG", (log_rect.x + 18, log_rect.y + 16), INK)
        _draw_progress_log(self.screen, self.font_small, self.progress_lines, pygame.Rect(log_rect.x + 14, log_rect.y + 42, log_rect.w - 28, log_rect.h - 54))

        self._draw_skill_bar(monster_a, pygame.Rect(58, 486, 424, 98), accent=CORAL)
        self._draw_skill_bar(monster_b, pygame.Rect(508, 486, 424, 98), accent=TEAL)

        if winner:
            self._button((122, 596, 170, 36), "再来一局", self.start_game, CORAL, mouse_pos)
            self._button((405, 596, 170, 36), "主界面", lambda: self._go("menu"), TEAL, mouse_pos)
            self._button((688, 596, 170, 36), "设置", lambda: self._go("settings"), YELLOW, mouse_pos, INK)

    def _draw_result(self, mouse_pos: tuple[int, int]) -> None:
        _text_center(self.screen, self.font_title, "VICTORY", (WIDTH // 2, 92), CREAM)
        _panel(self.screen, pygame.Rect(128, 155, 724, 245), fill=PANEL)
        winner_name = self.player_a.name if self.winner == "playerA" else self.player_b.name
        _text_center(self.screen, self.font_h1, f"{self.winner}  {winner_name}", (WIDTH // 2, 215), TEAL_DARK)
        _text_center(self.screen, self.font_body, "战斗日志已写入 game_log.txt", (WIDTH // 2, 282), MUTED)
        _text_center(self.screen, self.font_body, "技能 JSON 已保存在 playerA / playerB 文件夹", (WIDTH // 2, 326), MUTED)
        self._button((130, 470, 210, 56), "再来一局", self.start_game, CORAL, mouse_pos)
        self._button((386, 470, 210, 56), "设置", lambda: self._go("settings"), YELLOW, mouse_pos, INK)
        self._button((642, 470, 210, 56), "主界面", lambda: self._go("menu"), TEAL, mouse_pos)

    def _draw_error(self, mouse_pos: tuple[int, int]) -> None:
        _text(self.screen, self.font_h1, "ERROR", (90, 86), CREAM)
        _panel(self.screen, pygame.Rect(90, 150, 800, 250), fill=(255, 238, 228))
        for index, line in enumerate(_wrap(self.error or "", 82)[:7]):
            _text(self.screen, self.font_small, line, (130, 190 + index * 27), INK)
        self._button((90, 455, 210, 56), "返回设置", lambda: self._go("settings"), TEAL, mouse_pos)
        self._button((330, 455, 210, 56), "主界面", lambda: self._go("menu"), YELLOW, mouse_pos, INK)

    def _draw_battle_monster(self, monster: MonsterView, rect: pygame.Rect, flip: bool) -> None:
        _panel(self.screen, rect, fill=(255, 249, 232))
        sprite_path = monster.image_paths[0] if monster.image_paths else None
        sprite = self._cached_image(sprite_path, (150, 150)) if sprite_path else None
        if sprite:
            sprite = pygame.transform.flip(sprite, flip, False)
            self.screen.blit(sprite, sprite.get_rect(center=(rect.x + 82, rect.y + 96)))
        else:
            _draw_logo_mark(self.screen, (rect.x + 34, rect.y + 50))

        info = pygame.Rect(rect.x + 145, rect.y + 24, rect.w - 168, 92)
        pygame.draw.rect(self.screen, (255, 253, 246), info, border_radius=6)
        pygame.draw.rect(self.screen, BORDER, info, width=2, border_radius=6)
        _text(self.screen, self.font_body, monster.name[:12], (info.x + 12, info.y + 10), INK)
        _text(self.screen, self.font_small, f"HP {monster.hp}/{monster.max_hp}", (info.x + 12, info.y + 42), MUTED)
        hp_value = monster.hp / max(1, monster.max_hp)
        _draw_hud_bar(self.screen, pygame.Rect(info.x + 12, info.y + 66, info.w - 24, 14), hp_value)

    def _draw_skill_bar(self, monster: MonsterView, rect: pygame.Rect, accent: tuple[int, int, int]) -> None:
        _panel(self.screen, rect, fill=PANEL)
        tag = pygame.Rect(rect.x + 16, rect.y + 12, 118, 28)
        pygame.draw.rect(self.screen, accent, tag, border_radius=5)
        pygame.draw.rect(self.screen, BORDER, tag, width=2, border_radius=5)
        _text_center(self.screen, self.font_small, monster.player.upper(), tag.center, (255, 255, 255))
        item_y = rect.y + 44
        item_h = max(38, rect.h - 56)
        icon_size = min(32, item_h - 10)
        for index, skill in enumerate(monster.skills[:3]):
            x = rect.x + 16 + index * 134
            item = pygame.Rect(x, item_y, 122, item_h)
            pygame.draw.rect(self.screen, (255, 253, 246), item, border_radius=6)
            pygame.draw.rect(self.screen, BORDER, item, width=2, border_radius=6)
            icon = self._cached_image(skill.icon_path, (icon_size, icon_size)) if skill.icon_path else None
            if icon:
                self.screen.blit(icon, (item.x + 8, item.y + (item.h - icon_size) // 2))
            else:
                pygame.draw.circle(self.screen, accent, (item.x + 24, item.centery), icon_size // 2)
            name = _fit_text_tail(skill.name, "", self.font_small, item.w - 52)
            _text(self.screen, self.font_small, name, (item.x + 48, item.y + 5), INK)
            _text(self.screen, self.font_small, f"PWR {skill.power}", (item.x + 48, item.y + 24), MUTED)

    def _cached_image(self, path: Optional[Path], size: tuple[int, int]) -> Optional[pygame.Surface]:
        if not path:
            return None
        key = (str(path), size)
        if key not in self.image_cache:
            self.image_cache[key] = _load_image(path, size)
        return self.image_cache[key]

    def start_game(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.player_a.name.strip() or not self.player_b.name.strip():
            self.error = "请先在宝可梦配置里填写 playerA 和 playerB 的名字。"
            self.screen_name = "error"
            return
        self.screen_name = "running"
        self.status = f"画风：{self.current_style().name}"
        self.progress_lines = []
        with self.battle_lock:
            self.battle_monsters = {}
            self.battle_turns = []
            self.battle_winner = None
        self.winner = None
        self.error = None
        self.started_at = time.time()
        self.worker = threading.Thread(target=self._run_game_worker, daemon=True)
        self.worker.start()

    def _run_game_worker(self) -> None:
        try:
            winner = run_game(
                player_a_name=self.player_a.name,
                player_a_description=self.player_a.description,
                player_b_name=self.player_b.name,
                player_b_description=self.player_b.description,
                seed=self.settings.seed(),
                no_images=not self.settings.generate_images,
                text_provider=self.settings.text_provider(),
                image_provider=self.settings.image_provider(),
                text_speed=self.settings.text_speed(),
                image_speed=self.settings.image_speed(),
                art_style=self.current_style().id,
                progress=self._add_progress,
                battle_ready=self._on_battle_ready,
                turn_update=self._on_turn_update,
            )
        except Exception as exc:
            self.error = str(exc)
            self.screen_name = "error"
            return
        self.winner = winner
        with self.battle_lock:
            self.battle_winner = winner
        self.screen_name = "battle"

    def _add_progress(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.progress_lines.append(f"[{timestamp}] {message}")
        self.progress_lines = self.progress_lines[-80:]
        self.status = message

    def _on_battle_ready(self, monster_a, monster_b, state) -> None:
        with self.battle_lock:
            self.battle_monsters = {
                "playerA": self._snapshot_monster(monster_a),
                "playerB": self._snapshot_monster(monster_b),
            }
            self.battle_turns = []
            self.battle_winner = None
        self._add_progress("对战界面已加载：双方宝可梦和技能已展示")
        self.screen_name = "battle"

    def _on_turn_update(self, result, state) -> None:
        with self.battle_lock:
            for player, monster in state.monsters.items():
                if player in self.battle_monsters:
                    self.battle_monsters[player].hp = monster.hp
                    self.battle_monsters[player].max_hp = monster.max_hp
            self.battle_turns.append(self._snapshot_turn(result))
            self.battle_turns = self.battle_turns[-30:]
            self.battle_winner = state.winner

    def _snapshot_monster(self, monster) -> MonsterView:
        image_paths = [Path(path) for path in getattr(monster, "image_paths", [])]
        skills = [
            SkillView(
                name=skill.name,
                description=skill.description,
                icon_path=Path(skill.icon_path) if skill.icon_path else None,
                element=skill.element,
                category=skill.category.value if hasattr(skill.category, "value") else str(skill.category),
                power=skill.power,
            )
            for skill in monster.skills
        ]
        return MonsterView(
            player=monster.player,
            name=monster.name,
            hp=monster.hp,
            max_hp=monster.max_hp,
            image_paths=image_paths,
            skills=skills,
        )

    def _snapshot_turn(self, result) -> TurnView:
        return TurnView(
            turn=result.turn,
            attacker=result.attacker,
            defender=result.defender,
            skill_name=result.skill.name,
            narration=result.narration,
            judgement=result.judgement.value if hasattr(result.judgement, "value") else str(result.judgement),
            damage=result.damage,
            defender_hp=result.defender_hp,
            winner=result.winner,
        )

    def current_style(self) -> ArtStyle:
        return self.styles[self.settings.style_index]

    def prev_style(self) -> None:
        self.settings.style_index = (self.settings.style_index - 1) % len(self.styles)

    def next_style(self) -> None:
        self.settings.style_index = (self.settings.style_index + 1) % len(self.styles)

    def toggle_images(self) -> None:
        self.settings.generate_images = not self.settings.generate_images

    def next_text_provider(self) -> None:
        self.settings.text_provider_index = (self.settings.text_provider_index + 1) % len(TEXT_PROVIDERS)

    def next_image_provider(self) -> None:
        self.settings.image_provider_index = (self.settings.image_provider_index + 1) % len(IMAGE_PROVIDERS)

    def next_text_speed(self) -> None:
        self.settings.text_speed_index = (self.settings.text_speed_index + 1) % len(MODEL_SPEEDS)

    def next_image_speed(self) -> None:
        self.settings.image_speed_index = (self.settings.image_speed_index + 1) % len(MODEL_SPEEDS)

    def _field_value(self, field: Optional[str]) -> str:
        if field == "seed":
            return self.settings.seed_text
        if field == "player_a_name":
            return self.player_a.name
        if field == "player_a_description":
            return self.player_a.description
        if field == "player_b_name":
            return self.player_b.name
        if field == "player_b_description":
            return self.player_b.description
        return ""

    def _set_field_value(self, value: str) -> None:
        if self.active_field == "seed":
            self.settings.seed_text = "".join(ch for ch in value if ch.isdigit())[:9]
        elif self.active_field == "player_a_name":
            self.player_a.name = value[:NAME_LIMIT]
        elif self.active_field == "player_a_description":
            self.player_a.description = value[:DESCRIPTION_LIMIT]
        elif self.active_field == "player_b_name":
            self.player_b.name = value[:NAME_LIMIT]
        elif self.active_field == "player_b_description":
            self.player_b.description = value[:DESCRIPTION_LIMIT]

    def _clear_description(self, prefix: str) -> None:
        if prefix == "player_a":
            self.player_a.description = ""
        else:
            self.player_b.description = ""
        self._activate_field(f"{prefix}_description")

    def _is_description_field(self, field: Optional[str]) -> bool:
        return bool(field and field.endswith("_description"))

    def _clipboard_text(self) -> str:
        if not self.clipboard_ready:
            return ""
        raw = pygame.scrap.get(pygame.SCRAP_TEXT)
        if not raw:
            return ""
        for encoding in ("utf-8", "gbk", "utf-16"):
            try:
                return raw.decode(encoding).replace("\x00", "")
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="ignore").replace("\x00", "")

    def _button(
        self,
        rect_args: tuple[int, int, int, int],
        label: str,
        action: Callable[[], None],
        fill: tuple[int, int, int],
        mouse_pos: tuple[int, int],
        text_color: tuple[int, int, int] = (255, 255, 255),
        enabled: bool = True,
    ) -> None:
        button = Button(pygame.Rect(*rect_args), label, action, fill, text_color, enabled)
        self.buttons.append(button)
        button.draw(self.screen, self.font_body, mouse_pos)

    def _input_field(
        self,
        rect: pygame.Rect,
        field: str,
        value: str,
        placeholder: str,
        mouse_pos: tuple[int, int],
        multiline: bool = False,
    ) -> None:
        active = self.active_field == field
        fill = (255, 255, 255) if active else (255, 253, 246)
        pygame.draw.rect(self.screen, (19, 21, 22), rect.move(0, 4), border_radius=6)
        pygame.draw.rect(self.screen, fill, rect, border_radius=6)
        pygame.draw.rect(self.screen, TEAL if active else BORDER, rect, width=3 if active else 2, border_radius=6)
        text_color = INK if value else (132, 134, 132)
        text_area = rect.inflate(-24, -24)
        if multiline:
            all_lines = _wrap_text_pixels(value if value else placeholder, self.font_small, text_area.w - 8)
            max_lines = max(1, (text_area.h - 22) // 22)
            lines = all_lines[-max_lines:] if active and value else all_lines[:max_lines]
            _draw_clipped_lines(self.screen, self.font_small, lines, text_area, text_color, line_height=22)
            counter = f"{len(value)}/{DESCRIPTION_LIMIT}"
            _text(self.screen, self.font_small, counter, (rect.right - self.font_small.size(counter)[0] - 10, rect.bottom - 22), MUTED)
        else:
            display = _fit_text_tail(value, placeholder, self.font_body, text_area.w)
            _draw_clipped_lines(self.screen, self.font_body, [display], text_area, text_color, line_height=24)
        if active and (self.frame // 28) % 2 == 0:
            if multiline:
                value_lines = _wrap_text_pixels(value, self.font_small, text_area.w - 8) or [""]
                max_lines = max(1, (text_area.h - 22) // 22)
                visible_lines = value_lines[-max_lines:]
                last_line = visible_lines[-1] if visible_lines else ""
                cursor_x = text_area.x + min(text_area.w - 4, self.font_small.size(last_line)[0])
                cursor_y = text_area.y + (len(visible_lines) - 1) * 22
            else:
                tail = _fit_text_tail(value, "", self.font_body, text_area.w)
                cursor_x = text_area.x + min(text_area.w - 4, self.font_body.size(tail)[0])
                cursor_y = text_area.y
            old_clip = self.screen.get_clip()
            self.screen.set_clip(text_area)
            pygame.draw.line(self.screen, TEAL_DARK, (cursor_x, cursor_y), (cursor_x, cursor_y + 24), 2)
            self.screen.set_clip(old_clip)
        if active:
            pygame.key.set_text_input_rect(rect)
        self.buttons.append(Button(rect, "", lambda field=field: self._activate_field(field), fill=(255, 255, 255), text_color=INK))

    def _activate_field(self, field: str) -> None:
        self.active_field = field
        pygame.key.start_text_input()

    def _deactivate_field(self) -> None:
        self.active_field = None
        self._stop_key_repeat()
        pygame.key.stop_text_input()

    def _go(self, screen_name: str) -> None:
        self.screen_name = screen_name
        self._deactivate_field()

    def _quit(self) -> None:
        self.running = False


def _font(size: int) -> pygame.font.Font:
    font_path = ROOT / "font" / "HYPixel11pxU-2.ttf"
    if font_path.exists():
        return pygame.font.Font(str(font_path), size)
    return pygame.font.SysFont("microsoftyahei", size)


def _panel(screen: pygame.Surface, rect: pygame.Rect, fill: tuple[int, int, int] = PANEL) -> None:
    pygame.draw.rect(screen, fill, rect, border_radius=8)
    pygame.draw.rect(screen, BORDER, rect, width=2, border_radius=8)


def _text(screen: pygame.Surface, font: pygame.font.Font, text: str, pos: tuple[int, int], color: tuple[int, int, int]) -> None:
    screen.blit(font.render(text, True, color), pos)


def _text_center(screen: pygame.Surface, font: pygame.font.Font, text: str, center: tuple[int, int], color: tuple[int, int, int]) -> None:
    rendered = font.render(text, True, color)
    screen.blit(rendered, rendered.get_rect(center=center))


def _draw_clipped_lines(
    screen: pygame.Surface,
    font: pygame.font.Font,
    lines: list[str],
    rect: pygame.Rect,
    color: tuple[int, int, int],
    line_height: int,
) -> None:
    old_clip = screen.get_clip()
    screen.set_clip(rect)
    y = rect.y
    for line in lines:
        if y > rect.bottom:
            break
        rendered = font.render(line, True, color)
        if rendered.get_width() > rect.w:
            scale = rect.w / max(1, rendered.get_width())
            rendered = pygame.transform.smoothscale(rendered, (rect.w, max(1, round(rendered.get_height() * scale))))
        screen.blit(rendered, (rect.x, y))
        y += line_height
    screen.set_clip(old_clip)


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _wrap_text_pixels(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
    if not text:
        return [""]
    max_width = max(12, max_width)
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for char in paragraph:
            candidate = current + char
            if _safe_text_width(font, candidate) <= max_width or not current:
                current = candidate
            else:
                lines.append(current.rstrip())
                current = char.lstrip()
        lines.append(current.rstrip())
    return lines or [""]


def _fit_text_tail(value: str, placeholder: str, font: pygame.font.Font, max_width: int) -> str:
    if not value:
        return placeholder
    if _safe_text_width(font, value) <= max_width:
        return value
    suffix = ""
    for char in reversed(value):
        candidate = "..." + char + suffix
        if _safe_text_width(font, candidate) > max_width:
            break
        suffix = char + suffix
    return "..." + suffix


def _safe_text_width(font: pygame.font.Font, text: str) -> int:
    # Pygame font metrics can be optimistic for some CJK glyphs; add a small buffer.
    return font.size(text)[0] + 8


def _mix(color: tuple[int, int, int], other: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(round(color[index] * (1 - amount) + other[index] * amount) for index in range(3))


def _draw_logo_mark(screen: pygame.Surface, pos: tuple[int, int]) -> None:
    x, y = pos
    pygame.draw.circle(screen, CORAL, (x + 48, y + 48), 48)
    pygame.draw.circle(screen, (255, 255, 255), (x + 48, y + 48), 20)
    pygame.draw.rect(screen, INK, pygame.Rect(x + 3, y + 43, 90, 10), border_radius=3)
    pygame.draw.circle(screen, INK, (x + 48, y + 48), 23, width=5)
    pygame.draw.circle(screen, YELLOW, (x + 74, y + 24), 9)


def _draw_pixel_background(screen: pygame.Surface, particles: list[dict], frame: int) -> None:
    screen.fill(BG)
    for y in range(0, HEIGHT, 32):
        shade = _mix(BG, BG_2, 0.28 if (y // 32) % 2 else 0.12)
        pygame.draw.rect(screen, shade, pygame.Rect(0, y, WIDTH, 32))
    for x in range(-80, WIDTH, 80):
        offset = (frame // 2) % 80
        pygame.draw.line(screen, (51, 62, 58), (x + offset, 0), (x + offset + 160, HEIGHT), 1)
    for particle in particles:
        particle["y"] += particle["speed"]
        if particle["y"] > HEIGHT + 8:
            particle["y"] = -8
            particle["x"] = random.randint(0, WIDTH)
        alpha_wave = 0.45 + math.sin((frame + particle["x"]) / 28) * 0.25
        color = _mix(BG, particle["color"], max(0.18, alpha_wave))
        rect = pygame.Rect(round(particle["x"]), round(particle["y"]), particle["size"], particle["size"])
        pygame.draw.rect(screen, color, rect)


def _draw_arena(screen: pygame.Surface, rect: pygame.Rect) -> None:
    pygame.draw.rect(screen, (23, 26, 25), rect.move(0, 8), border_radius=10)
    pygame.draw.rect(screen, SKY, rect, border_radius=10)
    horizon = rect.y + 130
    pygame.draw.rect(screen, (168, 214, 197), pygame.Rect(rect.x, rect.y, rect.w, 145), border_radius=10)
    pygame.draw.rect(screen, FIELD, pygame.Rect(rect.x, horizon, rect.w, rect.h - 130), border_radius=10)
    pygame.draw.ellipse(screen, FIELD_DARK, pygame.Rect(rect.x + 92, rect.y + 214, 250, 70))
    pygame.draw.ellipse(screen, FIELD_DARK, pygame.Rect(rect.right - 342, rect.y + 214, 250, 70))
    pygame.draw.line(screen, (245, 236, 192), (rect.x + 24, horizon + 18), (rect.right - 24, horizon + 18), 4)
    pygame.draw.rect(screen, BORDER, rect, width=4, border_radius=10)


def _draw_fighter_card(
    screen: pygame.Surface,
    rect: pygame.Rect,
    name: str,
    label: str,
    image: Optional[pygame.Surface],
    flip: bool = False,
) -> None:
    pygame.draw.rect(screen, (19, 21, 22), rect.move(0, 7), border_radius=8)
    pygame.draw.rect(screen, CREAM, rect, border_radius=8)
    pygame.draw.rect(screen, BORDER, rect, width=3, border_radius=8)
    tag = pygame.Rect(rect.x + 14, rect.y + 12, 104, 28)
    pygame.draw.rect(screen, CORAL if not flip else TEAL, tag, border_radius=5)
    pygame.draw.rect(screen, BORDER, tag, width=2, border_radius=5)
    font = _font(14)
    _text_center(screen, font, label, tag.center, (255, 255, 255))
    _text(screen, _font(22), name[:12], (rect.x + 18, rect.y + 49), INK)
    if image:
        sprite = pygame.transform.flip(image, flip, False)
        screen.blit(sprite, sprite.get_rect(center=(rect.centerx, rect.y + 153)))
    else:
        _draw_logo_mark(screen, (rect.centerx - 48, rect.y + 100))
    _draw_hud_bar(screen, pygame.Rect(rect.x + 24, rect.bottom - 42, rect.w - 48, 18), 1.0)


def _draw_hud_bar(screen: pygame.Surface, rect: pygame.Rect, value: float) -> None:
    pygame.draw.rect(screen, BORDER, rect, border_radius=4)
    inner = rect.inflate(-4, -4)
    fill = pygame.Rect(inner.x, inner.y, round(inner.w * max(0, min(1, value))), inner.h)
    pygame.draw.rect(screen, YELLOW, fill, border_radius=3)
    pygame.draw.rect(screen, _mix(YELLOW, (255, 255, 255), 0.45), pygame.Rect(fill.x, fill.y, fill.w, max(2, fill.h // 3)), border_radius=2)


def _draw_status_strip(screen: pygame.Surface, rect: pygame.Rect, items: list[str], font: pygame.font.Font) -> None:
    pygame.draw.rect(screen, (20, 23, 24), rect, border_radius=7)
    pygame.draw.rect(screen, BORDER, rect, width=2, border_radius=7)
    slot_w = rect.w // len(items)
    for index, item in enumerate(items):
        x = rect.x + index * slot_w
        if index:
            pygame.draw.line(screen, (70, 75, 72), (x, rect.y + 8), (x, rect.bottom - 8), 1)
        _text_center(screen, font, item[:24], (x + slot_w // 2, rect.centery), CREAM)


def _style_chip(screen: pygame.Surface, font: pygame.font.Font, label: str, rect: pygame.Rect) -> None:
    pygame.draw.rect(screen, TEAL, rect, border_radius=7)
    pygame.draw.rect(screen, BORDER, rect, width=3, border_radius=7)
    pygame.draw.rect(screen, _mix(TEAL, (255, 255, 255), 0.25), pygame.Rect(rect.x + 5, rect.y + 5, rect.w - 10, 9), border_radius=3)
    _text_center(screen, font, label[:16], rect.center, (255, 255, 255))


def _draw_loading_bar(screen: pygame.Surface, rect: pygame.Rect, frame: int) -> None:
    pygame.draw.rect(screen, (18, 20, 20), rect.move(0, 5), border_radius=6)
    pygame.draw.rect(screen, CREAM, rect, border_radius=6)
    pygame.draw.rect(screen, BORDER, rect, width=3, border_radius=6)
    inner = rect.inflate(-8, -8)
    block_w = 28
    for x in range(inner.x, inner.right, block_w + 8):
        if ((x + frame * 7) // (block_w + 8)) % 3 != 0:
            pygame.draw.rect(screen, TEAL, pygame.Rect(x, inner.y, block_w, inner.h), border_radius=3)


def _draw_progress_log(screen: pygame.Surface, font: pygame.font.Font, lines: list[str], rect: pygame.Rect) -> None:
    old_clip = screen.get_clip()
    screen.set_clip(rect)
    pygame.draw.rect(screen, (28, 33, 32), rect, border_radius=6)
    pygame.draw.rect(screen, BORDER, rect, width=2, border_radius=6)
    visible = lines[-10:] if lines else ["等待任务开始..."]
    y = rect.y + 14
    for index, line in enumerate(visible):
        is_latest = index == len(visible) - 1 and bool(lines)
        color = YELLOW if is_latest else (223, 232, 215)
        prefix_color = TEAL if is_latest else (118, 178, 166)
        wrapped = _wrap_text_pixels(line, font, rect.w - 34)
        for sub_index, wrapped_line in enumerate(wrapped[:2]):
            if y + 20 > rect.bottom:
                break
            if sub_index == 0:
                marker = ">" if is_latest else "-"
                _text(screen, font, marker, (rect.x + 12, y), prefix_color)
            _text(screen, font, wrapped_line, (rect.x + 32, y), color)
            y += 23
        if y + 20 > rect.bottom:
            break
    screen.set_clip(old_clip)


def _draw_scanlines(screen: pygame.Surface) -> None:
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    for y in range(0, HEIGHT, 4):
        pygame.draw.line(overlay, (0, 0, 0, 18), (0, y), (WIDTH, y))
    screen.blit(overlay, (0, 0))


def _load_image(path: Path, size: tuple[int, int]) -> Optional[pygame.Surface]:
    if not path.exists():
        return None
    try:
        image = pygame.image.load(str(path)).convert_alpha()
    except pygame.error:
        return None
    return pygame.transform.smoothscale(image, size)


def _load_first_image(paths: list[Path], size: tuple[int, int]) -> Optional[pygame.Surface]:
    for path in paths:
        image = _load_image(path, size)
        if image:
            return image
    return None


def _read_player_profile(path: Path, fallback: str) -> tuple[str, str]:
    if not path.exists():
        return fallback, ""
    lines = path.read_text(encoding="utf-8").splitlines()
    name = fallback
    description = ""
    if lines and lines[0].strip():
        name = lines[0].strip()
    if len(lines) > 1:
        description = " ".join(line.strip() for line in lines[1:] if line.strip())
    return name, description


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open the AI Pokemon pygame frontend.")
    parser.add_argument("--smoke", action="store_true", help="Load UI resources without opening a window.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.smoke:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        app = Frontend()
        sample_skills = [
            SkillView("Spark Guard", "", None, "electric", "attack", 52),
            SkillView("Crystal Rush", "", None, "water", "attack", 47),
            SkillView("Pulse Wall", "", None, "light", "defense", 35),
        ]
        app.battle_monsters = {
            "playerA": MonsterView("playerA", "Aster", 76, 100, [], sample_skills),
            "playerB": MonsterView("playerB", "Voltbud", 58, 100, [], sample_skills),
        }
        app.battle_turns = [
            TurnView(2, "playerA", "playerB", "Crystal Rush", "Aster dashes forward and forces Voltbud back.", "advantage", 24, 58, None)
        ]
        app.progress_lines = ["battle ui smoke", "skills and sprites visible"]
        for screen_name in ["menu", "monster_setup", "settings", "running", "battle", "result", "error"]:
            app.screen_name = screen_name
            app.winner = "playerA"
            app.error = "smoke error preview"
            app.started_at = time.time()
            app._draw((0, 0))
        pygame.quit()
        print(f"frontend smoke ok: {len(app.styles)} styles")
        return
    Frontend().run()


if __name__ == "__main__":
    main()
