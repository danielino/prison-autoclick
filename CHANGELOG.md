# Changelog

## Unreleased

### Added
- **Other screen sizes**: the window size is written to the log at the start of a hunt (with a warning when the shape is not 16:9), shown in the Auto-hunt tab (`Screen size`), and `Save diagnostic report` stores a screenshot of the game window plus what every detector sees in a folder to send to the author. Detector tests now run at 1280x720 up to 3840x2160.
- **Vision helper log**: every request is logged (what was asked, model, image size) and the start of the answer with the time it took; the weakest-bot answer is compared with the bars (with their percentages) and the attacks-left digit with the colour reader's, and a `LLM stats` line at the end of each fight shows how often the model agreed.
- **Vision tab**: the Ollama settings have their own tab: server address, model list (installed models), Download (does `ollama pull` with a progress bar), mode, timeout, image width, a test of the connection and a test on the game screen. Unchecking the box turns the whole feature off (settings greyed out, nothing is sent anywhere); it is off by default, so a PC that cannot run Ollama needs nothing.
- **Vision helper (Ollama, optional)**: in the Auto-hunt tab, give the address of an Ollama server (this PC or the network) and a vision model (default `qwen3-vl:8b-instruct`). In fights the screen is sent to it with numbered markers on the bots and it says which has the least health and how many attacks are left. `assist` (default): the colour detectors choose, the model breaks ties or helps when the bars cannot be measured; `decide`: the model wins. Any error or odd answer is just no hint; after 3 failures in a row it is left alone until restart. Off by default; screenshots go only to the address typed in.
- **Attacks left**: the ATAQUES number of the HUD is read (by shape, no OCR engine). The manual attacks of a turn follow
  it (so the third attack is played whenever the game gives it), and a turn showing 3 is played by hand once so that
  Ctrl+R repeats it. Without a readable number it falls back to the health rule (below 50%).

### Fixed
- **Vision helper timing out**: the first request made Ollama load the model (20+ s) in the middle of a turn, and the connection test never loaded it. The model is now loaded when a hunt starts (and kept in memory for 30 minutes); a fight goes on without the helper until it is ready, and a request waits at most 15 s. `Test on the game screen` reports the loading time apart.
- **Smaller or larger windows**: the ATAQUES digit reader accepts the drift of the glyph at other sizes (closest digit, clearly closer than the others), name labels and bar checks scale their pixel limits with the window size.
- **Hurt bots not found in a fight**: the health bar of a damaged bot is mostly dark red, which was not recognised, so
  no bot was found and nothing was attacked. Both reds of the bar count now. Bars are also looked for at the very top of the room (a bot standing there has its name and bar at the screen edge).
- **Second attack of a turn**: when the bot is not seen any more (its bar hidden by the hit's effects), the click goes to
  where the last attack landed. Ctrl+R is only tried before any action of the turn (the game answers
  "No es posible REPETIR el turno ahora" otherwise); with an attack already done it passes the turn with Ctrl+T.
- **Ctrl+R too early**: the green rings of the buttons stay on while the enemy plays, so Ctrl+R was sent in the enemy's
  turn ("No es posible REPETIR el turno ahora"). It now waits for the yellow "El turno es tuyo." as the newest chat line
  (15 s at most). Below 50% health with no readable ATAQUES number, a fresh turn is played with three attacks at once.
  If the ATAQUES number cannot be read, a snapshot of the HUD is saved in snapshots/.
- **Attacks skipped after Ctrl+R**: Ctrl+R worked, but 3 s later the bot judged it failed (the green rings stay on) and clicked manual attacks in the enemy's turn. Now the chat decides: if it no longer ends with "El turno es tuyo." the repeat worked and nothing is done until the turn comes back (also after Ctrl+T). The status box no longer covers the ATAQUES number while running.
- **Two bots in a fight**: both attacks of a turn go to the bot hit first until it dies; before, if its bar was hidden, the other bot's bar won and the attacks were split.
- **Third attack cut short**: the ATAQUES reader mistakes the digits 2, 1 and 0 (a 2 read as 1, a 1 as 0), so the turn ended after two attacks. Only a 3 at the start of a turn is believed now; after that the attacks are counted by the bot itself.
- **Target choice with several bots**: the health left of every bar is measured (bright part over the whole bar) and a new target is the bot with the least health, hit until it dies; then the next weakest. Before, it was the one nearest to the opening click.
- **Attacks drifting to another bot**: when the click on the chosen bot registered nothing, the attack went to the other bot (and stayed there). Now the chosen bot gets up to 4 clicks around it first (the click point that worked last is tried first, e.g. the feet), and only then another bot.
- **Weakest bot, every turn**: the health of every bar is measured at each attack and a bot clearly weaker (by more than 5 points) than the one being hit takes over. The spot of the last hit is forgotten at the start of each turn (the camera may have moved) and the area is scanned again.
- **Wasted clicks on a missing third attack**: the ATAQUES reader had no template for the digit 3 and guessed it for any wide shape (a 2 read as 3), so a third attack was planned that did not exist. It now has real cuts of 1, 2 and 3 and returns nothing for an unknown shape. The red 0 after an attack ends the turn at once, and a third attack that does nothing gets two clicks only, then Ctrl+T. After a missed click the area is scanned again before the next one.
- **Stuck in a fight**: when the only candidate of a manual attack does nothing, the click is shifted around it (the same
  points as the opening aim) instead of repeating the same click; after 3 rounds without a working click it sends
  Ctrl+R, after 6 Ctrl+T, so the fight moves on.
- Second loot window opening late: pause before the second `/loot` is 3 s, and a window left open is emptied.

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
