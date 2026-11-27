# warhammer-survivors-bot

An educational bot for playing *Warhammer Survivors* (local, singleplayer).

The goal of this project is to learn about game automation techniques such as
screen capture, computer vision, and simulated input — not to gain any
advantage over other players.

## Requirements

- Windows 10/11
- Python 3.13+
- The game in windowed mode at 1920x1080 (the screen templates assume it)

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Usage

Start the game, then open the control window:

```powershell
python -m warhammer_survivors_bot
```

- **Start** / **Stop** run the bot. **F8** also stops it. When it stops during
  a run, it pauses the game.
- **Features** toggle parts of the bot while it runs (saved to `settings.json`):
  movement, level-up picks, opening wargear chests, starting the next run
  automatically, buying enhancements (off by default; not implemented yet), and
  saving annotated debug frames to `screenshots/overlay/` (off by default).
- The status panel and log show what the bot sees and does.
- A banner shows whether a bot is running: green when started from this window,
  **orange "TEST RUN"** when a bot was started elsewhere (e.g. a test run from a
  script). During a test run, Start is disabled (only one bot may control the
  game) and **Stop test run** asks that run to stop.
- **Background mode** (checkbox, applies on Start) lets you keep using your
  PC while the bot plays. The game ignores keyboard, mouse and controller input
  whenever it is not the active window, so this mode
  - plays with a **virtual Xbox controller** (requires the
    [ViGEmBus](https://github.com/nefarius/ViGEmBus) driver), and
  - attaches to the running game with [Frida](https://frida.re) and hooks
    `GetForegroundWindow`/`GetActiveWindow`/`GetFocus` **in memory**, so the
    game believes it is focused. No game files are changed; the hook is removed
    when the bot stops.

  Install the extra packages with `pip install -e ".[background]"`. The virtual
  controller stays connected while the control window is open; closing it makes
  the game show "Player disconnected" (press Enter to dismiss).
- Without background mode the bot uses keyboard/mouse and **the game must stay
  focused**: when you switch to another window the bot releases all keys and
  waits. The game keeps running unfocused, so stop the bot (which pauses the
  game) before switching away mid-run.
- The bot captures the game window directly, so other windows covering it do
  not disturb what it sees (minimizing does).
- Screens the bot does not recognise are left alone, and a screenshot is saved
  to `screenshots/`.

Exploration helper (one action, then a screenshot in `./screenshots`):

```powershell
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
