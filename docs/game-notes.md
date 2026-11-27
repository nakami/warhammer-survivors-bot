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

## Running in the background (game not focused)

- The game keeps running when it loses focus.
- **Capture** works in the background with `PrintWindow(PW_CLIENTONLY |
  PW_RENDERFULLCONTENT)` (~25 ms per 1920x1080 frame), also when covered by
  other windows. Not while minimized. Plain `PW_CLIENTONLY` returns a blank
  image.
- **Keyboard/mouse cannot reach it in the background.** Tested while the game
  was paused and unfocused: posted `WM_KEYDOWN`/`WM_KEYUP` (Esc), the same
  after posting `WM_ACTIVATE` + `WM_SETFOCUS`, and posted `WM_LBUTTONDOWN/UP`
  on the Resume button. None had any effect (the game most likely reads
  keyboard and mouse via Raw Input while focused only).
- **A virtual XInput controller does not work in the background either**
  (ViGEmBus + `vgamepad`, verified with `XInputGetState`). The game detects
  the controller while unfocused (button hints switch to gamepad icons) but
  ignores its button presses until the window is focused. With focus, the
  virtual controller works.
- When a controller that the game is using disconnects, the game shows a
  "Player disconnected – Please reconnect the controller" dialog.
- Conclusion: on a shared desktop the game only accepts input while focused.
  Real background play needs the game on its own desktop session (second
  PC or a VM), or modifying the game, which this project rules out.

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
  `E` opens the Armoury. Readable from pixels: a green **NEW** banner (item not
  owned yet), a damage-type tag such as "Fire"/"Default" (weapons only), and
  the inventory above the cards (6 weapon slots left, 6 passive slots right).
- `Esc` pauses: tabs Map / Statistics / Armoury / Options (Q/E to switch),
  map zoom with Z/X, buttons Resume / Objectives / Quit.
- The game does **not** pause when its window loses focus.
- Imperial Bastion has walls and buildings that block movement.
- **Wargear chests**: a "Wargear Acquired!" dialog (pauses the game) with
  `OPEN` (Enter), an opening animation, then the reward (coins + an item) with
  `Accept` (Enter).

## After a run

1. "GAME OVER" with `Quit` (Enter).
2. Recap: mission stats, weapons, enhancements; `Next` (Enter).
3. Enhancements shop: permanent upgrades bought with coins (costs 416+ at the
   time of writing; unaffordable prices are red). `Finish` (Enter) leaves
   without buying, `Esc` = Back.
4. Main menu.

## Vision

- Screens are recognised by template matching small UI crops
  (`src/warhammer_survivors_bot/templates/`) at fixed positions.
- On Imperial Bastion, enemies (Tyranids) are dark purple (HSV hue ~133),
  blue XP skulls hue ~100, grey XP skulls are unsaturated. The colour ranges
  in `vision.py` will need adjusting for other maps.
