"""AutoPrison: autoclick and click-sequence recorder for Prison Legacy (clean-room rewrite).

EXTERNAL program: it only simulates mouse and keyboard input (SendInput) and reads screen pixels.
It never opens, reads or modifies the game process (the window is found by its title only).
It acts only while the game window is in the foreground.

Usage: TAB opens the menu, then:
  1 autoclick   2 record (then 1-9)   3 play (then 1-9)   4 speed (1 up, 2 down, 0 exit)
  5 simple auto-fight (/repeat)   6 double-turn auto-fight (alternates sequences 8 and 9)
  7 auto-hunt (finds bots by their label, fights, /loot, next bot)   0 close menu
TAB stops everything. Sequences are saved immediately to autoprison_data.json.

The code lives in the prisonbot package (config, winapi, vision, minimap, hunt, gui, app).
"""
from prisonbot.app import App
from prisonbot.config import log, rotate_log

if __name__ == "__main__":
    rotate_log()
    log("AutoPrison started")
    print("AutoPrison is running. Close the AutoPrison window to quit (everything is already saved).")
    App().loop()
