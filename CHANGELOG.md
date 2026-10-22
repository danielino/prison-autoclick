# Changelog

## Unreleased

### Added
- **Attacks left**: the ATAQUES number of the HUD is read (by shape, no OCR engine). The manual attacks of a turn follow
  it (so the third attack is played whenever the game gives it), and a turn showing 3 is played by hand once so that
  Ctrl+R repeats it. Without a readable number it falls back to the health rule (below 50%).

### Fixed
- **Hurt bots not found in a fight**: the health bar of a damaged bot is mostly dark red, which was not recognised, so
  no bot was found and nothing was attacked. Both reds of the bar count now. Bars are also looked for at the very top of the room (a bot standing there has its name and bar at the screen edge).
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
- Calibrated on a 2360x1328 window; other sizes and aspect ratios are untested.
- The hunt is full automation: check the game rules before using it.
