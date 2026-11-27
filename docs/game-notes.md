# Game notes

Observations gathered by playing the game through the bot's own interface
(screen capture + simulated input). The game files are never read or modified.

## Environment

- Steam app id `3669620`; launch with `steam://rungameid/3669620`.
- Unity (IL2CPP) game, process `WarhammerSurvivors.exe`, window title
  `Warhammer Survivors`. Another window can share that title (e.g. an Explorer
  folder), so the bot matches on title **and** process name.
- Currently windowed, client area 1920x1080. All coordinates below are relative
  to the client area at that resolution.

## Input

- The game accepts `SendInput` keyboard and mouse events.
- **Letter keys are layout-translated.** With NEO 2 active, the on-screen hint
  "E" is triggered by the physical key that types `e` (QWERTY `F` position),
  not by the QWERTY `E` position. `inputs.press("e")` resolves characters
  through the active layout, so the bot can use the letters shown in the game.
- Named keys (Esc, Enter, Space, arrows, Ctrl, Shift) are layout independent.
- Movement: arrow keys and WASD (layout-translated) both work.
- Options > Gameplay > Keyboard Type is `QWERTY` (left unchanged). There is no
  key rebinding screen.

## Screen flow

1. Photosensitivity warning: "PRESS TO START", any key.
2. Title screen: "Click to Start / Press any button".
3. Universe select (Warhammer 40,000 / Age of Sigmar), `START` at (335, 957).
4. Main menu: `START` at (287, 207), Options at (1490, 45).
5. Character select: `Enter` = Next (last character preselected).
6. Mission select: `Enter` = START (last mission preselected).
7. In run.

## In run

- Player is always at the screen center (~960, 505), camera follows.
- Weapons fire automatically; the player only moves.
- HUD: XP bar + level (top), timer (top center), kills and coins (top right),
  weapon/equipment slots (top left), pause button (top right).
- Enemies drop XP skulls (grey / blue) that must be walked over.
- **Level Up** pauses the game and shows 4 cards at roughly x = 425, 782,
  1138, 1495 (y ~ 600). Click a card to take it. `Ctrl` toggles item view,
  `E` opens the Armoury.
- `Esc` pauses: tabs Map / Statistics / Armoury / Options (Q/E to switch),
  map zoom with Z/X, buttons Resume / Objectives / Quit.
