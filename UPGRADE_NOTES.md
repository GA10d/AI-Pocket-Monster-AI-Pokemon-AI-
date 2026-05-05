# Upgrade Notes

## API provider compatibility

The old notebook calls ZhipuAI directly and hard-codes the API key placeholder. The new `ai_providers.py` file adds a small OpenAI-compatible adapter and keeps the old `Model` method names:

```python
from ai_providers import Model

model = Model()
text = model.generator_model("给我生成一个火山系宝可梦设定")
```

It auto-loads `.env` and supports these keys:

- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`
- `GEMINI_API_KEY`
- `QWEN_API_KEY`
- `DOUBAO_API_KEY`

Optional overrides:

```env
AI_TEXT_PROVIDER=openai
AI_TEXT_SPEED=standard
AI_IMAGE_PROVIDER=openai
AI_IMAGE_SPEED=standard
# Optional explicit overrides: AI_TEXT_MODEL / AI_IMAGE_MODEL
```

Supported provider names are `openai`, `deepseek`, `gemini`, `qwen`, and `doubao`.

## Current cleanup status

Done:

1. Moved the core game flow out of `main.ipynb` into normal `.py` modules.
2. Replaced AI-generated skill text parsing with JSON output.
3. Stored monsters, skills, HP, turn results, battle state, and damage rules in dataclasses.
4. Added `main.py` as a command-line entry point.
5. Added selectable art styles in `art_styles.json`.
6. Added a more game-like pygame main menu and settings screen in `frontend.py`.
7. Added `Start_AI_Pokemon.bat` as a one-click Windows launcher.
8. Added an in-game monster configuration screen so players can enter names and descriptions before generation.
9. Fixed Gemini image generation to use the native Gemini image endpoint instead of the OpenAI-compatible images endpoint.
10. Added standard / fast model tiers for text and image providers, configurable from the game settings screen.

Still useful later:

1. Keep notebooks only for demos and experiments.
2. Add a battle playback screen that visualizes each `TurnResult`.
3. Add tests around JSON repair, provider selection, and damage bounds.
4. Rename `sever` to `server` later if the networking work resumes.
