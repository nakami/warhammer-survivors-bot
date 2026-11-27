# warhammer-survivors-bot

An educational bot for playing *Warhammer Survivors* (local, singleplayer).

The goal of this project is to learn about game automation techniques such as
screen capture, computer vision, and simulated input — not to gain any
advantage over other players.

## Requirements

- Windows 10/11
- Python 3.13+

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Usage

```powershell
python -m warhammer_survivors_bot

# Exploration helper: one action, then a screenshot in ./screenshots
python -m warhammer_survivors_bot.explore shot
python -m warhammer_survivors_bot.explore key e        # layout-aware letter
python -m warhammer_survivors_bot.explore key left 1.0 # hold for 1s
python -m warhammer_survivors_bot.explore click 960 540
```

See [docs/game-notes.md](docs/game-notes.md) for observations about the game.

## Development

```powershell
pytest
```

## Disclaimer

This is an unofficial fan project for educational purposes only. It is not
affiliated with or endorsed by Games Workshop or the game's developers.
Use only in offline, singleplayer play.
