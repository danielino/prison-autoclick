# Changelog

## Unreleased

### Fixed
- **Never click on a door or an exit**: an aim click shifted next to a door sent the character out of the zone ("Entrando a CELDAS DE SEGURIDAD NORESTE..."). Before every click in the scene that is not inside a fight (the opening attack, the re-clicks while chasing a bot, the walk towards a bot) the pointer now rests on the spot without clicking, and the screen is compared with how it looked before: a label that appears near the pointer (the game names doors, exits and objects under it) stops the click (no Ctrl+A either). A walk tries other points on the way; a bot standing at a door is left alone for 3 minutes. With the vision model on, the label is read and a label that names a character or an item (not an exit) lets the click through. Refusals are logged (NOT clicking), counted in the Stats tab and the first ones save a picture of what the game showed (`*-hover-label.png`).

### Added
- **Live web page**: a small web server (standard library, no dependencies, nothing loaded from the internet) on port 8080 with a page that shows in real time what the bot is doing and how the fight is going: status, fight number and time, whose turn it is, attacks left, your health, every bot in the fight with its health bar (the target marked), a health chart of the last minutes, the session counters with per-hour rates, the vision model's agreement and the latest events. The data arrives over Server-Sent Events (/events); /api/state gives the same data as JSON once. It only shows data: nothing in it can control the bot or the game. On this computer only by default; a checkbox in the Stats tab opens it to the network, and the port is a setting.

## 1.3.0 - 2026-10-22

### Added
- **Vision helper (Ollama, optional)**, in its own `Vision` tab: give the address of an Ollama server (this PC or the
  network) and a vision model (default `qwen3-vl:8b-instruct`; an 8B model is enough). In fights the screen is sent to it
  with numbered markers on the bots and it says which one has the least health and how many attacks are left. `assist`
  (default): the colour detectors choose and the model breaks ties or helps when a bar cannot be measured; `decide`: the
  model wins. The tab lists the installed models, downloads one (`ollama pull`, with a progress bar), tests the
  connection and tests on the game screen. The model is loaded when a hunt starts (kept in memory 30 minutes) and a
  request waits at most 15 s; any error or odd answer is just no hint, and after 3 failures in a row it is left alone
  until restart. **Off by default** and it can be switched off completely (settings greyed out, nothing is sent
  anywhere), so a PC that cannot run Ollama needs nothing. Every request, the start of the answer, its time and how
  often it agreed with the bars are logged.
- **Stats tab and session summary**: counters of what the bot did (fights and their length, attacks by hand and missed
  clicks, third attacks, Ctrl+R sent/worked/refused, Ctrl+T, loot windows, heals, the vision model's agreement), live in
  the new `Stats` tab (per-hour rates, Reset, Copy) and written to the log as a `STATS` line every few minutes (setting in
  the tab, 5 by default, 0 = never) and when the hunt ends.
- **Action log**: every action is logged with `ACTION`: the opening attack, each attack by hand (click point, the bot
  hit, its health and the other bots seen with theirs), Ctrl+R and Ctrl+T; `FIGHT over` gives the fight length.
- **Other screen sizes**: the window size is logged at the start of a hunt (with a warning when it is not 16:9) and
  shown in the Auto-hunt tab; `Save diagnostic report` stores a screenshot of the game window plus what every detector
  sees in a folder to send to the author. Detector tests run from 1280x720 up to 3840x2160.
- **Attacks left**: the ATAQUES number of the HUD is read by shape (real cuts of 1, 2 and 3, no OCR engine); a turn
  showing 3 is played by hand once so that Ctrl+R repeats it, and a red 0 after an attack ends the turn at once. Without
  a readable number it falls back to the health rule (below 50% health: three attacks).
- **Weakest bot first**: the health left of every bar is measured (bright part over the whole bar) at each attack; a new
  target is the bot with the least health and a clearly weaker one (by more than 5 points) takes over. Both attacks of a
  turn go to the same bot until it dies, the spot of the last hit is forgotten at each turn (the camera may move).

### Fixed
- **Waiting 20 s for our turn**: "El turno es tuyo." had to be the very newest chat line, so another player's chat or the
  yellow "La secuencia de repetición no puede ser ejecutada." hid it. The last six chat lines are read now: the newest
  game message decides (yellow = ours, red/green/blue = the turn is running) and other players' chat is skipped.
- **Ctrl+R**: it is only sent when the chat says it is our turn (the green rings stay on while the enemy plays and the
  game answers "No es posible REPETIR el turno ahora"); a repeat that worked is told by the chat, and nothing is clicked
  in the enemy's turn. After an action in the turn only Ctrl+T can pass it.
- **Opening attack on moving bots**: a click that hits nothing is noticed after 1.6 s (it was 6.6 s) and the next click
  follows at once on the bot's new position; a character walking after a bot that moves away looks for it again and
  clicks again every 3.5 s (up to 5 times). The first failures save an annotated screenshot and the chat in `snapshots/`
  (`*-no-fight.png`, `*-no-fight-chat.png`).
- **Hurt bots not found in a fight**: the bar of a damaged bot is mostly dark red; both reds count now, and bars are
  looked for at the very top of the room too.
- **Second and third attacks**: when the bot's bar is hidden the click goes where the last attack landed; a click that
  does nothing is shifted around the bot (the feet) before another bot is tried, and the click point that works is
  remembered; a third attack that does not exist gets two clicks only, then Ctrl+T.
- **Stuck in a fight**: after 3 rounds without a working click it sends Ctrl+R, after 6 Ctrl+T.
- **Smaller or larger windows**: the ATAQUES reader accepts the drift of the glyphs at other sizes, and name labels and
  bar checks scale their pixel limits with the window size.
- Second loot window opening late: the pause before the second `/loot` is 3 s, and a window left open is emptied.
- The status box no longer covers the ATAQUES number while running.

## 1.2.0 - 2026-10-21

### Added
- **Aim**: the opening click leads walking bots, and each retry tries another click point around the bot (the
  game accepts the attack on the feet in diamond-shaped rooms); the one that worked is tried first from then on.
- **Second corpse**: `/loot` is sent again after each emptied loot window (pause set in the window, default 2 s).
- **Auto-hunt (menu option 7)**: finds living bots by their name label, attacks the nearest isolated one (Ctrl+A + click),
  fights, loots with `/loot`, picks the items and starts over.
  - **Hunt area**: choose a rectangle of the screen (F9 top-left, F10 bottom-right); bots outside it are ignored.
    Shown and editable in the window, with the saved coordinates.
  - **Minimap walking**: when no bot is in the area, walks to the next lone bot diamond by clicking the minimap, in short
    hops, avoiding the fixed orange points (exits).
  - **Patrol**: bots only show on the minimap after moving, so with nothing found it walks a tour of minimap points and
    goes back to the starting point.
  - **Isolation**: only attacks bots that are far enough from other bots (screen and minimap distances are settings), so
    one bot enters the fight.
  - **Deadly spots**: never goes near all-red diamonds or bots with a visor (green fan on the minimap); retreats to the
    last safe position instead of stopping.
  - **Forbidden zones**: draw rectangles on a snapshot of the minimap; walking, patrol and target choice keep out of them.
  - **Health gate**: waits to attack while the SALUD bar is below a chosen percentage (default 70%).
  - **Auto-heal**: below that percentage it eats the food you pointed at (open Ctrl+1, mouse on the food, F8 in the
    hunt menu): double click, `+` while "salud +N" is white, `-` once when it turns red, then the green tick.
  - **Third attack** below 50% health: three manual attacks instead of two.
  - **Zone change**: stops if the zone changes (you died / left). The zone is recognised by the shape of its minimap;
    the name is not used because it moves and scrolls when long.
  - **Unique loot items**: when the game answers that an item is UNIQUE (red line in the chat), right click, confirm
    with Yes to destroy it and carry on with the items below. Can be turned off.
- **Fights**: first two turns are manual attacks (click on the bot), then Ctrl+T if action points are left, then Ctrl+R.
  If Ctrl+R cannot repeat (the bot it repeated on is dead and a second one is in the fight) it attacks by hand again.
- **Talk-only NPCs** (e.g. "hablar con"): a target whose attack fails twice is recognised by the shape of its name and
  ignored for 30 minutes.
- **Forbidden zones are tied to the map** they were drawn on and ignored in other zones.
- **Minimap size follows the zone** (it is shorter in some rooms), so clicks never land outside it.
- **Log rotation**: `autoprison.log` is rotated at every start, the last 5 are kept.

### Changed
- `/repetir` now presses Enter (hardware scancode) and `/repetir` waits at least 5 seconds between commands.
- Backspace is sent after the menu digits so they do not stay in the chat and break `/loot`.
- Turn detection accepts a thinner green ring and tolerates it pulsing.
- Minimum distance between bots on screen: 7% (was 12%, which skipped bots 10% apart).

- The window is split into three tabs (Autoclick, Auto-hunt, Sequences); the hunt options are grouped in
  Area / Choosing bots / Movement / Health and loot. New settings: pause before the next `/loot`.
- The code is split into the `prisonbot` package (config, winapi, vision, minimap, hunt, gui, app); `autoprison.py`
  is only the entry point.

### Fixed
- Fights started by a bot: the bot is found by its health bar when its name changes colour, so the manual attacks are sent.
- False "zone changed" stops (name bar moving or scrolling).
- Bots outside the area were never attacked after walking next to them; attacks now wait while the character walks to
  the target.
- Loot window not found with few items; loot clicks landing on the title row.
- Phantom bot detected on the HUD text ("ABS 100%").

### Known limits
- Background mode still moves the real cursor (the game reads it).
- Calibrated on a 2360x1328 (16:9) window. Other 16:9 sizes are checked on scaled screenshots and synthetic scenes only; other aspect ratios (16:10, 21:9, 4:3) are untested: use the diagnostic report.
- The hunt is full automation: check the game rules before using it.
