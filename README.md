# AutoPrison

Autoclicker and click-sequence recorder for **Prison Legacy**, inspired by MoleDJ's AutoPrisión DX for La Prisión. Written from scratch.

It is an external program: it only simulates mouse and keyboard input (SendInput) and reads screen pixels. It does not open, read or modify the game process. Unofficial project, not affiliated with the game's owners.

> Use at your own risk. Check the game's current rules on automation: the permission given to the original AutoPrisión applied to La Prisión, not to Prison Legacy.

## Usage

Download `AutoPrison.exe` from [Releases](../../releases), run it as your normal user (same as the game, not as administrator) and enter the game. With the game window in the foreground, **TAB** opens the menu:

| Key | Action |
|---|---|
| 1 | Autoclick at the cursor position |
| 2, then 1-9 | Record a sequence into that slot |
| 3, then 1-9 | Play a sequence (looped) |
| 4 | Speed (1 faster, 2 slower, 0 exit) |
| 5 | Simple auto-fight (sends `/repetir` every few seconds) |
| 6 | Double-turn auto-fight: alternates sequences 8 and 9 |
| 0 | Close the menu |

Press **TAB** again to stop or to finish recording. Everything stops if the game loses focus.

### Waiting for a window while recording

While recording, right after the click that opens a window:

- **F9**: dialog window in the screen center (e.g. "MÁQUINA: ¿Echas el dinero?").
- **F10**: menu next to the cursor.

When playing back, the program waits for that screen area to change before continuing. If nothing appears within 3 s it repeats the click once.

## Configuration

`autoprison_data.json`, next to the exe (or in `%APPDATA%\AutoPrison` if the folder is not writable): `hotkey` (`TAB`, `F8`...), `speed`, `jitter` (random timing variation, 0.2 = ±20%), `repeat_command` (use `/repeat` on an English client), etc. Sequences are saved instantly. `autoprison.log` helps with diagnostics.

## Build

```
python autoprison.py
pip install pyinstaller && pyinstaller --onefile --console --name AutoPrison autoprison.py
```

Releases are built by GitHub Actions when a `v*` tag is pushed (`git tag v1.0.1 && git push --tags`), together with the SHA-256 hash of the exe.

## Antivirus

PyInstaller executables that simulate input sometimes trigger false positives. That is why the exe is built publicly from this code; compare the release's SHA-256 with your download's.
