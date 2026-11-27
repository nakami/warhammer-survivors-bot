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
- Faking focus from outside (sending `WM_ACTIVATEAPP`/`WM_ACTIVATE`/
  `WM_NCACTIVATE`/`WM_SETFOCUS`) is not enough.
- **What works (with the owner's permission to modify the game at runtime):**
  Frida hooks inside the game process making `GetForegroundWindow`,
  `GetActiveWindow` and `GetFocus` return the game window. With those, the
  virtual controller works while the game is unfocused. (The game uses
  Rewired for input, which ignores input when the app is not focused.)

- **Side effect of the focus hook, and its fix:** the game reads keyboard and
  mouse from *all* windows (Raw Input with an input sink, plus polling
  `GetKeyboardState` ~120x/s) and only discards them when it believes it is
  unfocused. With the hook, keys typed into other windows (e.g. Esc in a
  terminal) therefore reached the game. The hook now filters that input while
  the game is not really in front (checked via `GetGUIThreadInfo`): Raw Input
  keyboard/mouse events become no-ops, pressed bits from `GetKeyboardState`/
  `GetKeyState`/`GetAsyncKeyState` are cleared, `GetCursorPos` points outside
  the game. Verified: Esc in another window toggled pause with the filter off
  and had no effect with it on. Clicking the game itself restores normal
  keyboard/mouse play.

## Controller layout (Xbox)

- Move: left stick. Pause: START. Pause menu: B Resume, X Objectives,
  Y Quit, LB/RB tabs, LT/RT map zoom.
- Menus, chests, Game Over, Completed Objectives, Recap: A.
- Level Up: selection starts on card 1; D-pad/stick moves it (highlighted
  card has a bright green border); A takes it immediately. RB = Armoury.
- Enhancements: A Finish (then an "End Recap – Confirm" dialog: A Confirm,
  B Cancel), B Back, **Y Refund All**, LB/RB remove/buy a rank, X toggle
  active. Affordable prices are white, unaffordable red.
- If the controller disconnects, a "Player disconnected" dialog appears
  (A/Enter closes it).
- Pause menu Y (Quit) asks "Are you sure you want to quit this run? Any
  completed objectives will be saved." (A Confirm / B Cancel) and leads to
  the Recap.

## Enhancements shop

- 4-column grid; rows 1-3: Strength/Save/Reload/Wounds,
  Toughness/Sustain/Range/Attacks, Skill/Move/Aura/Chance; row 4 (needs
  scrolling): Veterancy/Tithe/Corruption/Redeployment, more below.
- Each cell: name, price with a coin icon (red = not affordable) or "MAX",
  rank squares. The selected cell has a brighter border.
- D-pad moves the selection; RB (keyboard E) buys a rank, LB (Q) removes one.
- After every purchase **all** prices rise (e.g. buying Strength for 416 made
  Wounds go from 416 to 438), so the screen has to be re-read each time.
- A bought rank fills one more square: about 1.25 mean pixel difference over
  the cell's rank area, untouched cells stay at 0.

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
