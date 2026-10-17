# AutoPrison

Autoclicker and click-sequence recorder for **Prison Legacy**, inspired by MoleDJ's AutoPrisión DX for La Prisión. Written from scratch.

It is an external program: it only simulates mouse input (SendInput or window messages), types text for the `/repetir` auto-fight, and reads screen pixels. It does not open, read or modify the game process. Unofficial project, not affiliated with the game's owners.

> Use at your own risk. Check the game's current rules on automation: the permission given to the original AutoPrisión applied to La Prisión, not to Prison Legacy.

## Usage

Download `AutoPrison.exe` from [Releases](../../releases), run it as your normal user (same as the game, not as administrator) and enter the game. The AutoPrison window opens; closing it quits the program.

With the game window in the foreground, **TAB** opens an in-game menu:

| Key | Action |
|---|---|
| 1 | Autoclick at the cursor position |
| 2, then 1-9 | Record a sequence into that slot |
| 3, then 1-9 | Play a sequence (looped) |
| 4 | Speed (1 faster, 2 slower, 0 exit) |
| 5 | Simple auto-fight (sends `/repetir` every few seconds; needs the game focused) |
| 6 | Double-turn auto-fight: alternates sequences 8 and 9 |
| 0 | Close the menu |

Press **TAB** again to stop or to finish recording.

### The AutoPrison window

- **Delay between clicks (ms)** for autoclick, plus random variation and the speed of recorded sequences.
- **Slots 1-9**: give each recorded sequence a name (double-click or *Rename*).
- **Library**: *Save to library* keeps a named copy of a slot; *Load into slot* brings it back later. You can keep as many sequences as you like.

### Waiting for a window while recording

While recording, right after the click that opens a window:

- **F9**: dialog window in the screen center (e.g. "MÁQUINA: ¿Echas el dinero?").
- **F10**: menu next to the cursor.

When playing back, the program waits for that screen area to change before continuing. If nothing appears within 3 s it repeats the click once.

### Background mode (experimental)

Tick *Background mode* in the window. Autoclick and sequences then send their clicks to the game window as messages, without moving your mouse or taking focus, so you can use other programs. Notes:

- Keep the game window open and **not minimized** (a minimized game stops drawing, and window waits stop working).
- **F12** stops from anywhere. It also stops by itself if the game window disappears or is minimized.
- Autoclick remembers where your cursor was over the game when you started it.
- It depends on how the game handles input while unfocused; it may not work on every setup. Test with something harmless first.
- The simple auto-fight (option 5) types text, so it always needs the game focused.

## Configuration

`autoprison_data.json`, next to the exe (or in `%APPDATA%\AutoPrison` if the folder is not writable). Most settings are in the window. Others: `hotkey` (`TAB`, `F8`...), `repeat_command` (use `/repeat` on an English client), `seq_pause`. Everything is saved instantly. `autoprison.log` helps with diagnostics. Set the `AUTOPRISON_HOME` environment variable to use another folder.

## Build

```
python autoprison.py
pip install pyinstaller && pyinstaller --onefile --noconsole --name AutoPrison autoprison.py
```

Releases are built by GitHub Actions when a `v*` tag is pushed (`git tag v1.0.1 && git push --tags`), together with the SHA-256 hash of the exe.

## Antivirus

PyInstaller executables that simulate input sometimes trigger false positives. That is why the exe is built publicly from this code; compare the release's SHA-256 with your download's.
