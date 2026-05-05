import base64
import json
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
import requests
from PIL import Image


ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL_SPEED = "standard"
MODEL_SPEEDS = ("standard", "fast")


def load_env(path: Path = ROOT / ".env") -> None:
    """Load simple KEY=VALUE pairs without requiring python-dotenv."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    env_key: str
    base_url: str
    text_models: Dict[str, str]
    image_models: Optional[Dict[str, str]] = None

    @property
    def text_model(self) -> str:
        return self.text_model_for(DEFAULT_MODEL_SPEED)

    @property
    def image_model(self) -> Optional[str]:
        return self.image_model_for(DEFAULT_MODEL_SPEED)

    def text_model_for(self, speed: str) -> str:
        return self.text_models.get(normalize_model_speed(speed), self.text_models[DEFAULT_MODEL_SPEED])

    def image_model_for(self, speed: str) -> Optional[str]:
        if not self.image_models:
            return None
        return self.image_models.get(normalize_model_speed(speed), self.image_models[DEFAULT_MODEL_SPEED])


PROVIDERS: Dict[str, ProviderConfig] = {
    "openai": ProviderConfig(
        name="openai",
        env_key="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        text_models={
            "standard": "gpt-4.1",
            "fast": "gpt-4.1-mini",
        },
        image_models={
            "standard": "gpt-image-1",
            "fast": "gpt-image-1",
        },
    ),
    "deepseek": ProviderConfig(
        name="deepseek",
        env_key="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        text_models={
            "standard": "deepseek-reasoner",
            "fast": "deepseek-chat",
        },
    ),
    "gemini": ProviderConfig(
        name="gemini",
        env_key="GEMINI_API_KEY",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        text_models={
            "standard": "gemini-2.5-pro",
            "fast": "gemini-2.5-flash",
        },
        image_models={
            "standard": "gemini-3.1-flash-image-preview",
            "fast": "gemini-3.1-flash-image-preview",
        },
    ),
    "qwen": ProviderConfig(
        name="qwen",
        env_key="QWEN_API_KEY",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        text_models={
            "standard": "qwen-plus",
            "fast": "qwen-turbo",
        },
    ),
    "doubao": ProviderConfig(
        name="doubao",
        env_key="DOUBAO_API_KEY",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        text_models={
            "standard": "doubao-seed-1-6-250615",
            "fast": "doubao-seed-1-6-flash-250615",
        },
    ),
}


def normalize_model_speed(speed: Optional[str]) -> str:
    if not speed:
        return DEFAULT_MODEL_SPEED
    value = speed.strip().lower()
    aliases = {
        "std": "standard",
        "normal": "standard",
        "balanced": "standard",
        "quick": "fast",
        "lite": "fast",
        "turbo": "fast",
    }
    value = aliases.get(value, value)
    return value if value in MODEL_SPEEDS else DEFAULT_MODEL_SPEED


class LLMError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    def __init__(
        self,
        provider: Optional[str] = None,
        text_model: Optional[str] = None,
        text_speed: Optional[str] = None,
        image_provider: Optional[str] = None,
        image_model: Optional[str] = None,
        image_speed: Optional[str] = None,
        timeout: int = 90,
    ):
        load_env()
        self.timeout = timeout
        self.text_speed = normalize_model_speed(text_speed or os.getenv("AI_TEXT_SPEED"))
        self.image_speed = normalize_model_speed(image_speed or os.getenv("AI_IMAGE_SPEED"))
        self.text_config = self._pick_provider(provider, needs_image=False)
        self.image_config = self._pick_provider(image_provider, needs_image=True, required=False)
        self.text_model = text_model or os.getenv("AI_TEXT_MODEL") or self.text_config.text_model_for(self.text_speed)
        self.image_model = image_model or os.getenv("AI_IMAGE_MODEL") or (
            self.image_config.image_model_for(self.image_speed) if self.image_config else None
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        if system:
            messages = [{"role": "system", "content": system}] + messages
        payload = {
            "model": self.text_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        data = self._post_json(self.text_config, "chat/completions", payload)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected chat response from {self.text_config.name}: {data}") from exc

    def generate_image(self, prompt: str, style: str = "") -> np.ndarray:
        if not self.image_config or not self.image_config.image_model:
            raise LLMError("No image provider is configured. Set AI_IMAGE_PROVIDER or add an image-capable API key.")
        errors: List[str] = []
        configs = [self.image_config]
        configs.extend(
            config
            for config in PROVIDERS.values()
            if config.image_model and config.name != self.image_config.name and os.getenv(config.env_key)
        )
        for config in configs:
            model = self.image_model if config.name == self.image_config.name else config.image_model_for(self.image_speed)
            try:
                return self._generate_image_with_config(config, model, prompt, style)
            except LLMError as exc:
                errors.append(str(exc))
        raise LLMError("All configured image providers failed: " + " | ".join(errors))

    def _generate_image_with_config(
        self,
        config: ProviderConfig,
        image_model: Optional[str],
        prompt: str,
        style: str = "",
    ) -> np.ndarray:
        if not image_model:
            raise LLMError(f"{config.name} is not configured with an image model.")
        if config.name == "gemini":
            return self._generate_gemini_image(image_model, prompt, style)
        payload = {
            "model": image_model,
            "prompt": f"{style} {prompt}".strip(),
            "n": 1,
        }
        data = self._post_json(config, "images/generations", payload)
        try:
            image_data = data["data"][0]
            if image_data.get("b64_json"):
                raw = base64.b64decode(image_data["b64_json"])
            else:
                raw = requests.get(image_data["url"], timeout=self.timeout).content
            return np.array(Image.open(BytesIO(raw)))
        except (KeyError, IndexError, TypeError, OSError) as exc:
            raise LLMError(f"Unexpected image response from {config.name}: {data}") from exc

    def _generate_gemini_image(self, image_model: str, prompt: str, style: str = "") -> np.ndarray:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise LLMError("Missing GEMINI_API_KEY for provider gemini.")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{image_model}:generateContent"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": f"{style} {prompt}".strip(),
                        }
                    ]
                }
            ]
        }
        response = requests.post(
            url,
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            },
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise LLMError(f"gemini API error {response.status_code}: {response.text[:500]}")
        data = response.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            for part in parts:
                inline_data = part.get("inlineData") or part.get("inline_data")
                if inline_data and inline_data.get("data"):
                    raw = base64.b64decode(inline_data["data"])
                    return np.array(Image.open(BytesIO(raw)))
        except (KeyError, IndexError, TypeError, OSError) as exc:
            raise LLMError(f"Unexpected image response from gemini: {data}") from exc
        raise LLMError(f"Gemini returned no image data: {data}")

    def _post_json(self, config: ProviderConfig, endpoint: str, payload: Dict) -> Dict:
        api_key = os.getenv(config.env_key)
        if not api_key:
            raise LLMError(f"Missing {config.env_key} for provider {config.name}.")
        url = f"{config.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise LLMError(f"{config.name} API error {response.status_code}: {response.text[:500]}")
        return response.json()

    def _pick_provider(self, provider: Optional[str], needs_image: bool, required: bool = True) -> Optional[ProviderConfig]:
        env_name = "AI_IMAGE_PROVIDER" if needs_image else "AI_TEXT_PROVIDER"
        preferred = provider or os.getenv(env_name)
        candidates: Iterable[str]
        if preferred:
            candidates = [preferred.lower()]
        elif needs_image:
            candidates = ["openai", "gemini"]
        else:
            candidates = ["openai", "deepseek", "gemini", "qwen", "doubao"]
        for name in candidates:
            config = PROVIDERS.get(name)
            if config and os.getenv(config.env_key) and (not needs_image or config.image_model_for(DEFAULT_MODEL_SPEED)):
                return config
        kind = "image" if needs_image else "text"
        if required:
            raise LLMError(f"No configured {kind} provider found. Check .env or set {env_name}.")
        return None


class Model:
    """Compatibility wrapper for the old notebook's Model API."""

    def __init__(
        self,
        provider: Optional[str] = None,
        image_provider: Optional[str] = None,
        text_speed: Optional[str] = None,
        image_speed: Optional[str] = None,
    ):
        self.provider = OpenAICompatibleProvider(
            provider=provider,
            image_provider=image_provider,
            text_speed=text_speed,
            image_speed=image_speed,
        )

    def generator_model(self, prompt: str) -> str:
        return self.provider.chat([{"role": "user", "content": prompt}], temperature=0.95)

    def referee_model(self, MonsterA, MonsterB, movement, skillA, skillB, skill2use) -> str:
        movement_letter = "A" if movement == MonsterA else "B"
        system = (
            "你是一场虚构宝可梦对战的游戏裁判兼旁白。"
            "根据双方宝可梦的特性、技能描述和当前行动，写出合理、详细、有画面感的战斗过程。"
        )
        messages = [
            {"role": "user", "content": f"宝可梦A名字：{MonsterA.name}\n描述：{self._description(MonsterA)}\n技能：{skillA}"},
            {"role": "user", "content": f"宝可梦B名字：{MonsterB.name}\n描述：{self._description(MonsterB)}\n技能：{skillB}"},
            {"role": "user", "content": f"宝可梦{movement_letter}使用技能 {self._skill_name(movement, skill2use)}。"},
        ]
        return self.provider.chat(messages, system=system, temperature=0.9, max_tokens=1024)

    def damage_model(self, MonsterA, MonsterB, movement, skillA, skill2use, prompt) -> str:
        movement_letter = "A" if movement == MonsterA else "B"
        system = "你是游戏裁判。只回答“优势”或“劣势”，不要输出其他内容。"
        messages = [
            {"role": "user", "content": f"宝可梦A：{MonsterA.name}\n描述：{self._description(MonsterA)}"},
            {"role": "user", "content": f"宝可梦B：{MonsterB.name}\n描述：{self._description(MonsterB)}"},
            {"role": "user", "content": f"宝可梦{movement_letter}使用 {self._skill_name(movement, skill2use)}。战斗过程：{prompt}"},
        ]
        return self.provider.chat(messages, system=system, temperature=0.1, max_tokens=20)

    def image_model(self, question: str, style: str = "") -> np.ndarray:
        return self.provider.generate_image(question, style=style)

    @staticmethod
    def plot_image(img: np.ndarray) -> None:
        import matplotlib.pyplot as plt

        plt.imshow(img)
        plt.axis("off")
        plt.show()

    @staticmethod
    def _description(monster) -> str:
        description = getattr(monster, "description", "")
        if isinstance(description, list):
            return description[0] if description else ""
        return str(description)

    @staticmethod
    def _skill_name(monster, index: int) -> str:
        if hasattr(monster, "skill_name"):
            return monster.skill_name[index]
        if hasattr(monster, "skills"):
            return monster.skills[index].name
        raise AttributeError("monster must expose skill_name or skills")
