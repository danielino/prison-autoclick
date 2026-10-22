"""Auto-hunt: find a bot, attack, fight, loot, walk the minimap, patrol, avoid danger."""
import copy, ctypes, json, os, random, re, sys, threading, time
from ctypes import wintypes
from .config import *
from .winapi import *
from .vision import *
from .minimap import *
from . import llm, diagnostic, stats, live


class HuntMixin:
    """Methods of App for option 7 (auto-hunt)."""

    def hunt_corners(self, h):
        x, y, w, hh = client_rect(h)
        cx, cy = cursor_pos()
        pt = (min(max((cx - x) / max(w, 1), 0.0), 1.0), min(max((cy - y) / max(hh, 1), 0.0), 1.0))
        for vk, key in ((VK["F9"], "tl"), (VK["F10"], "br")):
            if self.pressed(vk):
                self.hunt_pts[key] = pt
                log("HUNT corner %s = (%.3f, %.3f)" % (key, pt[0], pt[1]))
        if self.pressed(VK["F8"]):  # the food in the open character sheet (Ctrl+1)
            self.cfg["heal_item"] = [round(pt[0], 4), round(pt[1], 4)]
            save(self.cfg)
            self.msg = "Food position saved"
            log("HUNT food item = (%.3f, %.3f)" % pt)

    def on_hunt_setup(self, d):
        if d == 0:
            self.state = "IDLE"
        elif d == 1:
            if len(self.hunt_pts) < 2:
                self.msg = "Set both corners first (F9 and F10)"
                return
            (ax, ay), (bx, by) = self.hunt_pts["tl"], self.hunt_pts["br"]
            area = [min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)]
            if area[2] - area[0] < 0.03 or area[3] - area[1] < 0.03:
                self.msg = "Area too small: pick two opposite corners"
                return
            self.cfg["hunt_area"] = [round(v, 4) for v in area]
            save(self.cfg)
            self.run("Auto-hunt running", self.w_hunt)
        elif d == 2:
            if self.cfg.get("hunt_area"):
                self.run("Auto-hunt running (saved area)", self.w_hunt)
            else:
                self.msg = "No saved area yet"

    # -- auto-hunt: attack the bot at the starting spot, repeat the attack each turn, loot, wait for it to respawn
    def hunt_say(self, text):
        self.msg = "Auto-hunt: " + text
        live.update(status=text)
        log("HUNT " + text)

    def hunt_move(self, h, fx, fy):
        x, y, w, hh = client_rect(h)
        u32.SetCursorPos(x + int(fx * w), y + int(fy * hh))
        time.sleep(0.12)

    def hunt_in_combat(self, h):
        """(in combat?, banner fraction, turn-buttons fraction). Either cue counts: the red COMBATE banner or the
        green turn buttons, so a miss of one does not hide a fight."""
        banner, fc = detect(h, "combat")
        mine, ft = detect(h, "turn")
        return banner or mine, fc, ft

    @staticmethod
    def hunt_px(h, p):
        x, y, w, hh = client_rect(h)
        return x + int(p[0] * w), y + int(p[1] * hh)

    LEAD = 0.2  # seconds between the last look at the bot and the click landing
    MAX_LEAD = 0.07  # never aim further than this (screen fraction) from where the bot was seen

    def hunt_aim(self, h, spot, lead=None):
        """Look at the bot twice and aim ahead of it if it is walking. Returns the point to click."""
        def seen():
            near = [p for p in find_bots(h) if abs(p[0] - spot[0]) < 0.10 and abs(p[1] - spot[1]) < 0.12]
            return min(near, key=lambda p: (p[0] - spot[0]) ** 2 + (p[1] - spot[1]) ** 2) if near else None
        t1 = time.time()
        a = seen()
        t2 = time.time()
        b = seen() if a else None
        t3 = time.time()
        if not a:
            return spot
        if not b:
            return a
        dt = max((t2 + t3) / 2 - (t1 + t2) / 2, 0.05)  # time between the middles of the two scans
        lead = self.LEAD if lead is None else lead
        dx, dy = (b[0] - a[0]) / dt * lead, (b[1] - a[1]) / dt * lead
        d = (dx * dx + dy * dy) ** 0.5
        if d > self.MAX_LEAD:
            dx, dy = dx * self.MAX_LEAD / d, dy * self.MAX_LEAD / d
        p = (b[0] + dx, b[1] + dy)
        if d > 0.004:
            log("HUNT bot is moving: aiming (%.3f,%.3f) -> (%.3f,%.3f)" % (b[0], b[1], p[0], p[1]))
        return p

    # Where exactly the game accepts the attack click depends on the room (in a diamond-shaped room it is the feet) and
    # on the bot (its name label is not always above its body): each retry tries another point around the first one
    AIM_VARIANTS = [(0.0, 0.0), (0.025, 0.02), (-0.025, 0.02), (0.0, 0.045), (0.03, -0.015), (-0.03, -0.015)]
    aim_pref = 0  # the variant that worked last time: tried first from then on
    manual_pref = 0  # the same for the manual attacks of a fight

    HOVER_WAIT = 0.35  # seconds the pointer rests on a spot before the label (if any) is looked for
    hover_shots = 0  # screenshots saved of refused spots (a few, to see what the game showed)
    attack_refused = False  # the last attack was not made because a door or exit label was under the pointer

    def hunt_hover_label(self, h, p):
        """Move the pointer to `p` WITHOUT clicking and look for a text label that appears near it: the game names doors,
        exits and objects under the pointer ("CELDAS DE SEGURIDAD NORESTE" with an arrow). The screen is compared with how
        it looked before the pointer arrived, so labels that are always on screen (bot names) do not count.
        -> (label found, number of new white-text pixels)."""
        x, y, w, hh = client_rect(h)
        k = w / 2000.0
        fx0, fy0 = max(p[0] - 0.16, 0.0), max(p[1] - 0.25, 0.0)
        fw, fh = min(0.32, 1 - fx0), min(0.35, 1 - fy0)
        rw, rh = int(fw * w), int(fh * hh)
        gx, gy = x + int(fx0 * w), y + int(fy0 * hh)
        before = grab(gx, gy, rw, rh)
        self.hunt_move(h, *p)
        time.sleep(self.HOVER_WAIT)
        after = grab(gx, gy, rw, rh)
        new, lo, hi = 0, rw, 0
        for j in range(0, rh, 2):
            base = j * rw * 4
            for i in range(0, rw, 2):
                q = base + i * 4
                if min(after[q], after[q + 1], after[q + 2]) >= 225 and min(before[q], before[q + 1], before[q + 2]) < 200:
                    new += 1
                    lo, hi = min(lo, i), max(hi, i)
        wide = (hi - lo) >= 0.05 * w
        return (new * 4 >= 150 * k * k and wide), new * 4

    def hunt_hover_ok(self, h, p, what="click"):
        """True if it is safe to click at `p`: no door/exit label shows when the pointer rests there. With the vision model
        on, a label that it reads as a character or an item (not an exit) is let through."""
        found, n = self.hunt_hover_label(h, p)
        if not found:
            return True
        log("HUNT hover check at (%.3f,%.3f): a label appeared (%d new text pixels) before the %s" % (p[0], p[1], n, what))
        cfg = getattr(self, "cfg", None) or {}
        said = llm.read_hover(cfg, h, p) if llm.active(cfg) else None
        if said is not None and said[1] is False and said[0]:
            log("HUNT the label reads %r: not an exit, going on" % said[0])
            return True
        log("HUNT NOT clicking at (%.3f,%.3f): %s" % (p[0], p[1], ("the label reads %r, an exit" % said[0]) if said else
                                                         "a label (door, exit or object) is under the pointer"))
        if HuntMixin.hover_shots < 6:
            HuntMixin.hover_shots += 1
            snapshot(h, "hover-label", (max(p[0] - 0.16, 0.0), max(p[1] - 0.25, 0.0), 0.32, 0.35))
        stats.add("clicks_refused")
        return False

    CHASE_EVERY = 3.5  # seconds of walking after a click before the bot is looked for again and clicked again
    attack_quick_miss = False  # the last attack click made nothing happen at all (the character did not even start walking)
    marked = 0  # annotated screenshots saved of failed attacks (a few, to see where the clicks went)

    def hunt_attack(self, h, spot, variant=0):
        """Ctrl+A, then click the bot (it may have to walk there first). True once a fight is detected. While the
        character walks after a bot that keeps moving, the bot is looked for again every few seconds and clicked again."""
        self.attack_quick_miss = False
        for attempt in (1,):
            if self.hunt_loot_leftover(h):
                return False  # the window hid the scene: look for the target again
            self.hunt_say("attacking (Ctrl+A + click)")
            self.attack_refused = False
            target = spot
            # the bots walk around: aim where this one will be when the click lands (the check below takes a while too)
            spot = self.hunt_aim(h, spot, self.LEAD + self.HOVER_WAIT + 0.2)
            dx, dy = self.AIM_VARIANTS[variant % len(self.AIM_VARIANTS)]
            spot = (spot[0] + dx, spot[1] + dy)
            log("HUNT aim variant %d: click at (%.3f,%.3f)" % (variant % len(self.AIM_VARIANTS), spot[0], spot[1]))
            if not self.hunt_hover_ok(h, spot, "attack"):  # never click on a door or an exit
                self.attack_refused = True
                self.attack_quick_miss = True
                return False
            key_combo(0x1D, 0x1E)  # Ctrl+A: the cursor becomes the attack pointer
            u32.SetCursorPos(*self.hunt_px(h, spot))
            time.sleep(0.05)
            mouse_click("L")
            # the character now WALKS to the bot and the fight starts when it arrives: keep waiting while it moves,
            # give up when it has stood still for 3 s without a fight (1.6 s if it never moved at all: the click hit
            # nothing) or after 30 s. A bot that walks away is looked for again and clicked again every few seconds.
            t0, best, still, last = time.time(), (0.0, 0.0), 0.0, find_self(h)
            clicked, moved, rechases = t0, False, 0
            lastm = read_minimap(*grab_minimap(h))[0]  # the minimap arrow also tells whether we are walking
            while time.time() - t0 < 30:
                if not self.wait(0.4):
                    return False
                ok, fc, ft = self.hunt_in_combat(h)
                best = (max(best[0], fc), max(best[1], ft))
                if ok:
                    log("HUNT fight detected after %.1f s (banner %.3f, buttons %.3f)" % (time.time() - t0, fc, ft))
                    log("HUNT ACTION opening attack (Ctrl+A + click) landed on the bot at (%.3f,%.3f)" % spot)
                    stats.add("fights_started")
                    return True
                me = find_self(h)
                pm = read_minimap(*grab_minimap(h))[0]
                same_scene = bool(me and last) and abs(me[0] - last[0]) < 0.004 and abs(me[1] - last[1]) < 0.004
                same_map = bool(pm and lastm) and abs(pm[0] - lastm[0]) < 0.006 and abs(pm[1] - lastm[1]) < 0.006
                if same_scene and (same_map or not pm):
                    still += 0.4
                else:
                    still = 0.0
                    moved = True
                last, lastm = me or last, pm or lastm
                if moved and still < 0.8 and time.time() - clicked >= self.CHASE_EVERY and rechases < 5:
                    # still walking after the bot, no fight yet: it has moved on. Look for it near where it was.
                    near = [p for p in find_bots(h) if abs(p[0] - target[0]) < 0.22 and abs(p[1] - target[1]) < 0.22]
                    if near:
                        target = min(near, key=lambda p: (p[0] - target[0]) ** 2 + (p[1] - target[1]) ** 2)
                        spot = self.hunt_aim(h, target, self.LEAD + self.HOVER_WAIT + 0.2)
                        spot = (spot[0] + dx, spot[1] + dy)
                        rechases += 1
                        if not self.hunt_hover_ok(h, spot, "new click"):
                            self.attack_refused = True
                            break
                        key_combo(0x1D, 0x1E)
                        log("HUNT chasing: the bot moved, clicking again at (%.3f,%.3f) (%d)" % (spot[0], spot[1], rechases))
                        u32.SetCursorPos(*self.hunt_px(h, spot))
                        time.sleep(0.05)
                        mouse_click("L")
                        clicked = time.time()
                if still >= (3.0 if moved else 1.6) and time.time() - t0 > 1.5:
                    break
            self.attack_quick_miss = not moved
            log("HUNT attempt %d at (%.3f,%.3f): no fight after %.1f s (best banner %.3f, buttons %.3f)%s" % (
                attempt, spot[0], spot[1], time.time() - t0, best[0], best[1],
                "; the click made nothing happen" if not moved else ""))
            stats.add("opening_failed")
            if HuntMixin.marked < 8:  # where the click went, and what the game said in the chat (for tuning the aim)
                HuntMixin.marked += 1
                diagnostic.save_marked(h, "no-fight", [spot, target])
                snapshot(h, "no-fight-chat")
        return False

    def hunt_approach(self, h, bot):
        """The game refuses attacks on bots that are too far ("escapado de tu radio de acciÃ³n"): click the floor part of
        the way towards the bot, then wait until the character stops. False if we cannot see ourselves."""
        me = find_self(h)
        if not me:
            log("HUNT approach: own label not found")
            return False
        mx, my = me[0], me[1] + FEET_DROP
        bx, by = bot[0], bot[1] + 0.11  # body point + a bit = the bot's feet
        self.hunt_say("moving closer to the bot")
        for part in (0.6, 0.45, 0.75, 0.3):  # a point on the way; the first one with no door or exit label under it
            px, py = mx + (bx - mx) * part, min(my + (by - my) * part, 0.88)
            log("HUNT approach: me=(%.3f,%.3f) bot=(%.3f,%.3f) click=(%.3f,%.3f)" % (mx, my, bx, by, px, py))
            if self.hunt_hover_ok(h, (px, py), "walk"):
                break
        else:
            log("HUNT approach: every point on the way has a label under it: not walking")
            return False
        self.hunt_move(h, px, py)
        mouse_click("L")
        last, still, t0 = me, 0.0, time.time()
        while time.time() - t0 < 8:
            if not self.wait(0.4):
                return False
            cur = find_self(h)
            if cur and last and abs(cur[0] - last[0]) < 0.004 and abs(cur[1] - last[1]) < 0.004:
                still += 0.4
                if still >= 1.2:
                    return True
            else:
                still = 0.0
            last = cur or last
        return True

    def hunt_engage(self, h, bot):
        """Attack; if the bot is out of range, walk closer and try again (up to 4 times)."""
        for step in range(4):
            variant = (self.aim_pref + step) % len(self.AIM_VARIANTS)
            if self.hunt_attack(h, bot, variant):
                if variant != self.aim_pref:
                    log("HUNT aim variant %d worked: using it first from now on" % variant)
                self.aim_pref = variant
                return True
            if not self.alive() or step == 3:
                return False
            if self.attack_quick_miss and step < 2 and find_self(h):
                # the character did not even start walking: the click hit nothing (the bot moved). Look again and click
                # again at once instead of walking first; walking closer is for the clicks the game refuses
                self.hunt_say("click missed the bot: looking again")
            elif not self.hunt_approach(h, bot):
                return False
            near = [p for p in find_bots(h) if abs(p[0] - bot[0]) < 0.25 and abs(p[1] - bot[1]) < 0.25]
            bot = min(near, key=lambda p: (p[0] - bot[0]) ** 2 + (p[1] - bot[1]) ** 2) if near else bot
        return False

    OPENING = 2  # manual attacks (Ctrl+A + click) before Ctrl+R has something to repeat

    def llm_pick(self, h, cands, fills, locked=None):
        """Second opinion of the vision model (Ollama) on which bot has the least health. It replaces the order found by
        the colour detectors only when it is switched to "decide", or when the bars cannot tell (not measured, or within
        10 points of each other). Returns the list of candidates, reordered or not."""
        cfg = getattr(self, "cfg", None) or {}
        if len(cands) < 2 or not llm.active(cfg) or (locked and cfg.get("llm_mode") != "decide"):
            return cands  # (a bot already being hit keeps being hit unless the model may decide)
        shown = cands[:6]
        idx, said = llm.fight_advice(cfg, h, shown)
        if said is not None:  # how the model's digit compares with the colour reader's (for judging the helper)
            mine_left = read_attacks(h)
            if mine_left is not None:
                llm.STATS["attacks_same" if mine_left == said else "attacks_differ"] += 1
                log("HUNT attacks left: the model says %d, the colour reader %d" % (said, mine_left))
        if idx is not None:
            llm.STATS["agree" if shown[idx] == cands[0] else "differ"] += 1
        if idx is None or shown[idx] == cands[0]:
            if idx is not None:
                log("HUNT the vision model agrees with the bars: (%.3f,%.3f)" % cands[0])
            return cands
        pick, mine = shown[idx], cands[0]
        unsure = pick not in fills or mine not in fills or abs(fills[pick] - fills[mine]) < 0.1
        if cfg.get("llm_mode") == "decide" or unsure:
            log("HUNT the vision model prefers (%.3f,%.3f, bar %s) to (%.3f,%.3f, bar %s): %s" % (
                pick[0], pick[1], (("%.0f%%" % (fills[pick] * 100)) if pick in fills else "?"), mine[0], mine[1], (("%.0f%%" % (fills[mine] * 100)) if mine in fills else "?"), "following it" if unsure else "decide mode"))
            return [pick] + [c for c in cands if c != pick]
        log("HUNT the vision model prefers (%.3f,%.3f, bar %s) but the bars are clear: keeping (%.3f,%.3f, bar %s)" % (
            pick[0], pick[1], (("%.0f%%" % (fills[pick] * 100)) if pick in fills else "?"), mine[0], mine[1], (("%.0f%%" % (fills[mine] * 100)) if mine in fills else "?")))
        return cands
    def hunt_manual_attack(self, h, spot, max_tries=6):
        """One manual attack inside the fight: click the bot nearest to `spot` (the second bot of a fight
        stands somewhere else, so the scene is scanned again)."""
        locked = getattr(self, "fight_spot", None)  # the bot hit first: keep hitting that one
        me = find_self(h)
        bars = find_bars(h)
        fills = {p: f for p, f in LAST_BARS if p in bars}  # health left of each bar of this scan
        cands = []  # the red health bars are the reliable cue in a fight (the name label changes colour and the
        for group in (bars, find_bots(h)):  # label scan also picks up floor and text): bars first, then labels
            for p in group:
                if me and abs(p[0] - me[0]) < 0.07 and -0.02 < p[1] - me[1] < 0.26:
                    continue  # that is our own character (label to feet)
                if all(abs(p[0] - q[0]) > 0.05 or abs(p[1] - q[1]) > 0.05 for q in cands):
                    cands.append(p)
        if fills:
            log("HUNT health of the bots: %s" % ", ".join("(%.3f,%.3f) %.0f%%" % (p[0], p[1], f * 100) for p, f in fills.items()))
        if locked and cands and min((p[0] - locked[0]) ** 2 + (p[1] - locked[1]) ** 2 for p in cands) > 0.1 ** 2:
            log("HUNT the bot hit before is gone (dead): choosing the weakest one")
            locked = self.fight_spot = None
        if locked:
            # both attacks of a turn go to the same bot until it dies: whatever was seen near the last hit (bar or
            # label) comes first, even if its bar is hidden and only the label shows
            cands.sort(key=lambda p: (p[0] - locked[0]) ** 2 + (p[1] - locked[1]) ** 2)
            # ...but the health is measured at every attack: a bot clearly weaker than the one being hit (by more than
            # 5 points) takes over (the one being hit keeps it while its bar is hidden or the difference is small)
            if cands and cands[0] in fills:
                weaker = [p for p in cands if p in fills and fills[p] < fills[cands[0]] - 0.05]
                if weaker:
                    w = min(weaker, key=lambda p: fills[p])
                    log("HUNT a weaker bot at (%.3f,%.3f): %.0f%% against %.0f%%" % (w[0], w[1], fills[w] * 100, fills[cands[0]] * 100))
                    cands.remove(w)
                    cands.insert(0, w)
                    stats.add("weaker_switch")
        else:
            # a new target: the bar with the least health first (bars within 10% of each other count as equal, then
            # the one nearest to the spot of the attack); labels have no health to compare and come after the bars
            ref = spot or (0.5, 0.5)
            cands.sort(key=lambda p: (p not in bars, round(fills.get(p, 1.0) / 0.1), (p[0] - ref[0]) ** 2 + (p[1] - ref[1]) ** 2))
        cands = self.llm_pick(h, cands, fills, locked)
        if not cands and locked:
            log("HUNT manual attack: no bot seen, clicking where the last attack landed")
            cands = [locked]  # the bot hit a moment ago has not gone anywhere; its bar may be hidden by the hit's effects
        if spot and not cands:
            cands = [spot]
        if not cands:
            log("HUNT manual attack: no bot found on the screen")
            return False
        log("HUNT manual attack candidates: %s" % ", ".join("(%.3f,%.3f)" % p for p in cands[:4]))
        live.update(bots=[{"x": round(c[0], 3), "y": round(c[1], 3), "health": fills.get(c)} for c in cands[:6]], target=0)
        self.live_target = fills.get(cands[0])
        # the chosen bot first, with the click point that worked last time: the body point under the bar is often not what
        # the game accepts (diamond rooms: the feet are), and a failed click must not send the attack to another bot
        n, c0 = len(self.AIM_VARIANTS), cands[0]
        order = [(self.manual_pref + k) % n for k in range(n if len(cands) < 2 else 4)]
        steps = [(c0, v) for v in order] + [(c, None) for c in cands[1:3]]
        seen = ", ".join("(%.3f,%.3f)%s" % (c[0], c[1], (" %.0f%%" % (fills[c] * 100)) if c in fills else "")
                         for c in cands[:4])
        for k, (c, v) in enumerate(steps[:max_tries]):
            if v is not None:
                c = c0  # the bot may have moved (camera, walking) since the last click: follow it
                dx, dy = self.AIM_VARIANTS[v]
                p = (min(max(c[0] + dx, 0.0), 1.0), min(max(c[1] + dy, 0.0), 1.0))
            else:
                p = c
            base = grab_chat(h)
            self.hunt_move(h, *p)
            time.sleep(0.25)  # let the game notice the pointer over the bot before clicking
            mouse_click("L")  # inside a fight a plain click on the bot attacks (no Ctrl+A)
            for _ in range(6):  # an attack always writes a line in the chat: no new line = the click hit nothing
                time.sleep(0.3)
                if changed(base, grab_chat(h), min_frac=0.01, tol=40):
                    log("HUNT manual attack at (%.3f,%.3f): done" % p)
                    stats.add("attacks_manual")
                    live.sample(target=fills.get(c0))
                    log("HUNT ACTION attack #%d by hand: clicked (%.3f,%.3f) on the bot at (%.3f,%.3f), its health %s; bots seen: %s" % (
                        stats.get("attacks_manual"), p[0], p[1], c0[0], c0[1],
                        ("%.0f%%" % (fills[c0] * 100)) if c0 in fills else "?", seen))
                    self.fight_spot = p
                    if v is not None:
                        self.manual_pref = v
                    return True
            log("HUNT manual attack at (%.3f,%.3f): nothing happened, trying the next click" % p)
            stats.add("attack_misses")
            # scan the area again before the next click: the camera or the bot may have moved
            near = [q for q in find_bars(h) if (q[0] - c0[0]) ** 2 + (q[1] - c0[1]) ** 2 < 0.1 ** 2]
            if near:
                c0 = min(near, key=lambda q: (q[0] - c0[0]) ** 2 + (q[1] - c0[1]) ** 2)
        return False
    def hunt_fight(self, h, spot=None):
        """The fight (see hunt_fight_loop), with its state published for the live web page."""
        live.fight_start()
        self.live_target = None
        try:
            return self.hunt_fight_loop(h, spot)
        finally:
            live.fight_end()

    def hunt_fight_loop(self, h, spot=None):
        """Attack by hand for the first turns (Ctrl+R has nothing to repeat yet), then Ctrl+R on every turn of yours until
        the fight is over (banner gone for 2 s). If Ctrl+R does not pass the turn (e.g. the bot it repeated is dead and a
        second one is in the fight), it starts again with manual attacks. False if stopped/timeout."""
        last, gone, t0 = 0.0, None, time.time()
        manual, sent_r, end_turn, away, fails = self.OPENING, None, False, None, 0
        self.fight_spot = None
        bonus = False  # the third attack (health below 50%) was already used in this manual phase
        rage = False  # the turn with the third attack has been played by hand (Ctrl+R repeats it from now on)
        total = self.OPENING  # manual attacks planned in this phase
        mine_t = -99.0
        miss = 0  # manual attack rounds in a row where no click worked
        held_since = None  # since when Ctrl+R waits for the chat to say it is our turn
        unread = 0  # snapshots saved of the ATAQUES box while it could not be read
        await_turn = None  # since when we wait for "El turno es tuyo." after ending the turn or repeating it
        while True:
            if not self.wait(0.4):
                return False
            now = time.time()
            in_combat, fc, ft = self.hunt_in_combat(h)
            if ft >= DETECT["turn"][5]:
                mine_t = now
            mine = now - mine_t < 1.2  # the green ring pulses: a short gap does not mean the turn is over
            if in_combat:
                gone = None
                # the turn really passed (buttons away for 2 s): nothing left to end, the repeat worked
                away = (away or now) if not mine else None
                if away and now - away >= 2.0:
                    end_turn, sent_r, fails = False, None, 0
                if sent_r and mine and now - sent_r >= 3.0:
                    # what the chat says after Ctrl+R: a green line (our attack) below "El turno es tuyo." = it worked;
                    # only red lines there = the game refused ("No es posible REPETIR el turno ahora": nothing to repeat)
                    st = chat_state(h)
                    if st == "acted" or (st is None and not chat_turn_is_mine(h)):
                        sent_r = None
                        log("HUNT Ctrl+R worked: waiting for my next turn")
                        stats.add("repeats_ok")
                        await_turn = now
                    elif st == "refused" or now - sent_r >= 5.0:
                        sent_r = None
                        # nothing was done: attack by hand (also when the game says the sequence cannot be executed
                        # because the bot it repeated on is dead and another one is in the fight)
                        log("HUNT Ctrl+R did not work (%s): %d manual attacks, then Ctrl+T" % (
                            "refused by the game" if st == "refused" else "no attack in the chat", self.OPENING))
                        stats.add("repeats_failed")
                        snapshot(h, "ctrl-r-failed")  # what the chat says (the game explains why it cannot repeat)
                        manual, end_turn, self.fight_spot, bonus, rage = self.OPENING, False, None, False, False
                        total = self.OPENING  # first bot dead: new target
                # after the first attack the green rings get thin and may vanish for a while although it is still our
                # turn (attacks left): keep going for 8 s after they were last seen
                still_mine = mine or (0 < manual < total and away is not None and now - away < 8.0)
                if still_mine and now - last >= max(self.cfg["repeat_interval"], 5.0):
                    hp = read_health(h)
                    log("HUNT health %.0f%% in the fight" % (hp * 100))
                    live.update(my_health=hp)
                    live.sample(my=hp, target=getattr(self, "live_target", None))
                    left = read_attacks(h)  # the ATAQUES number of the HUD (None if it cannot be read)
                    live.update(attacks_left=left)
                    if left is not None:
                        log("HUNT attacks left this turn: %d" % left)
                    elif unread < 2:
                        unread += 1
                        log("HUNT the ATAQUES number cannot be read: saving a snapshot of the HUD")
                        snapshot(h, "ataques-unreadable", (0.0, 0.0, 0.30, 0.16))
                    if await_turn is not None:
                        # after Ctrl+T / Ctrl+R the enemy plays: any click now would be wasted (the chat changes with its
                        # lines and the click would count as done). Wait for the newest chat line "El turno es tuyo."
                        # (20 s at most, in case the line cannot be read)
                        if chat_turn_is_mine(h) or now - await_turn >= 20.0:
                            await_turn = None
                            live.update(turn="mine")
                            # a new turn: the camera may have moved, so the spot of the last hit means nothing; the area
                            # is scanned again and the weakest bot chosen from scratch
                            self.fight_spot = None
                        else:
                            self.hunt_say("waiting for the enemy to finish its turn")
                            live.update(turn="enemy")
                            last = now - max(self.cfg["repeat_interval"], 5.0) + 1.0
                            continue
                    if left is None and llm.active(self.cfg):
                        left = llm.read_attacks(self.cfg, h)  # the colour reader found no digit: ask the vision model
                    third = (left is not None and left >= 3) or hp < 0.5  # the third attack exists below 50% health
                    if (left is None or left < 3) and manual == total == self.OPENING and hp < 0.5 and not bonus:
                        # no HUD number and below 50% health: a fresh turn has three attacks, do not wait for the
                        # second one to see it
                        manual = total = self.OPENING + 1
                        bonus = rage = True
                        log("HUNT health below 50%: this turn has three attacks")
                    if manual == 0 and not end_turn and third and not rage:
                        # Ctrl+R repeats the turn we did last, so it would never contain the third attack:
                        # play one turn by hand with three, then repeat that one
                        manual = total = self.OPENING + 1
                        bonus = rage = True
                        log("HUNT three attacks available: one manual turn with all of them")
                    if left is not None and left >= 3 and manual > 0 and manual == total and not bonus:
                        # the HUD shows 3 at the start of a turn: play three. Its other digits are not trusted (a 2 is
                        # read as 1 or 3, a 1 as 0): after the first attack we count our own, never the HUD's number
                        manual, total, bonus = left, max(total, left), True
                        rage = True  # a turn played by hand with three attacks is what Ctrl+R repeats next
                    if left == 0 and 0 < manual < total:
                        # the red 0 of the HUD (after at least one attack of this turn) cannot be mistaken for another digit
                        log("HUNT the HUD shows 0 attacks left: ending the turn")
                        manual, end_turn = 0, True
                    if manual > 0:
                        log("HUNT my turn (buttons %.3f) -> manual attack (%d left)" % (ft, manual))
                        self.hunt_say("my turn: attacking (click on the bot)")
                        third_try = bonus and total == self.OPENING + 1 and manual == 1  # the attack that may not exist
                        if self.hunt_manual_attack(h, spot, 2 if third_try else 6):
                            manual -= 1
                            if third_try:
                                stats.add("third_attacks")
                            if manual == 0 and hp < 0.5 and not bonus:
                                manual, bonus, rage, total = 1, True, True, self.OPENING + 1  # third attack below 50%
                                log("HUNT health below 50%: third attack")
                            end_turn = manual == 0  # both attacks done: spend the leftover action points by ending the turn
                            miss = 0
                        elif third_try:
                            log("HUNT the third attack did not work: there was none, ending the turn")
                            manual, end_turn, miss = 0, True, 0
                        else:
                            miss += 1
                            if miss % 3 == 0:  # the clicks keep hitting nothing: let the game move on instead of looping
                                # "No es posible REPETIR el turno ahora": Ctrl+R only works at the start of a turn, before
                                # any action; with an attack already done in this turn only Ctrl+T can pass it
                                acted = manual < total
                                use_r = not acted and miss % 6 == 3
                                log("HUNT %d turns without a working attack click: %s" % (miss, "Ctrl+R" if use_r else "Ctrl+T"))
                                key_combo(0x1D, 0x13 if use_r else 0x14)
                                if use_r:
                                    sent_r = now
                                else:
                                    manual, total, end_turn, bonus, rage = self.OPENING, self.OPENING, False, False, False
                                self.fight_spot = None
                    elif end_turn:
                        log("HUNT still my turn after the attacks -> Ctrl+T (end turn)")
                        self.hunt_say("my turn: ending it (Ctrl+T)")
                        log("HUNT ACTION Ctrl+T: end the turn")
                        live.update(turn="enemy")
                        stats.add("end_turns")
                        key_combo(0x1D, 0x14)
                        end_turn = False
                        await_turn = now
                    elif not chat_turn_is_mine(h) and now - (held_since or now) < 15.0:
                        # the green rings stay on while the enemy plays: Ctrl+R then gets "No es posible REPETIR el turno
                        # ahora". It is accepted when the newest chat line is "El turno es tuyo." (15 s at most, in case
                        # the line cannot be read)
                        held_since = held_since or now
                        self.hunt_say("waiting for the enemy to finish its turn")
                        last = now - max(self.cfg["repeat_interval"], 5.0) + 1.0
                        continue
                    else:
                        held_since = None
                        log("HUNT my turn (buttons %.3f) -> Ctrl+R" % ft)
                        log("HUNT ACTION Ctrl+R: repeat the last turn (same attacks, same targets as that turn)")
                        live.update(turn="enemy")
                        stats.add("repeats")
                        self.hunt_say("my turn: Ctrl+R")
                        key_combo(0x1D, 0x13)
                        sent_r = now
                    last = now
                else:
                    self.hunt_say("fighting" if not mine else "my turn, waiting %ds" % max(
                        0, round(max(self.cfg["repeat_interval"], 5.0) - (now - last))))
            else:
                gone = gone or now
                if now - gone >= 2.0:
                    stats.add("fights_done")
                    stats.add("fight_seconds", now - t0)
                    log("HUNT FIGHT over after %.0f s" % (now - t0))
                    if llm.STATS["asks"]:
                        log(llm.stats_line())  # so the log shows how useful the model has been so far
                    return True
            if now - t0 > 900:
                self.hunt_say("fight longer than 15 min: stopped")
                return False

    def hunt_loot(self, h):
        """/loot, and again after each emptied window: a second corpse (two bots in the fight) needs its own /loot."""
        for n in range(4):
            if not self.hunt_loot_once(h):
                return
            log("HUNT loot: window emptied, sending %s again for any other corpse" % self.cfg["loot_command"])
            stats.add("loot_windows")
            # the game answers "Necesitarás esperar un poco más para repetir eso" to a /loot typed too soon
            if not self.wait(self.cfg.get("loot_again_delay", 3.0)):
                return

    def hunt_loot_once(self, h):
        """One /loot and taking the items of the window it opens. True if a window opened and was emptied."""
        if not self.wait(1.0):
            return False
        self.hunt_say("looting (%s)" % self.cfg["loot_command"])
        type_line(self.cfg["loot_command"])
        end = time.time() + 3.5
        top = None
        while time.time() < end and top is None:
            if not self.wait(0.2):
                return False
            top = find_loot(h)
        if top is None:
            log("HUNT loot window did not open")
            return False
        return self.hunt_loot_items(h, top)

    def hunt_loot_leftover(self, h):
        """If a loot window is open (it appeared after the wait for it had run out), empty it. True if there was one:
        it covers the middle of the screen, so no attack click can work while it is open."""
        top = find_loot(h)
        if top is None:
            return False
        log("HUNT a loot window is still open: taking its items")
        self.hunt_say("loot window left open: taking the items")
        self.hunt_loot_items(h, top)
        return True

    def hunt_loot_items(self, h, top):
        """Take the items of the open loot window (header at `top`). True once it has closed."""
        skip, destroyed = 0, 0  # skip = rows at the top that cannot be taken and are left alone
        for k in range(14):
            # item rows (icon + name) sit 0.095 of the screen height below the header, 0.069 apart; the window is
            # re-located every time because it shrinks and re-centres when an item is taken
            row = skip + (0 if k < 10 else k - 9)  # first row until it is empty, then probe the rows below
            log("HUNT loot click %d: header y=%.3f row=%d" % (k, top, row))
            base = grab_chat(h)
            self.hunt_move(h, 0.41, top + 0.095 + row * 0.069)
            mouse_click("L")
            if not self.wait(0.6):
                return False
            if chat_unique_error(h) and changed(base, grab_chat(h), min_frac=0.01, tol=40):
                log("HUNT unique item at row %d (the game says we already have one)" % row)
                if self.cfg["hunt_destroy_unique"] and destroyed < 4 and self.hunt_destroy(h, top, row):
                    destroyed += 1
                else:
                    skip += 1  # leave it and try the next one
            top = find_loot(h)
            if top is None:
                if not self.wait(0.4):
                    return False
                top = find_loot(h)
                if top is None:
                    log("HUNT loot window closed after %d clicks" % (k + 1))
                    return True
        log("HUNT loot window still open after 14 clicks")
        return False

    def hunt_destroy(self, h, top, row):
        """Right click the item -> CONFIRMAR dialog -> SI. The items below move up. True if the dialog was answered."""
        self.hunt_say("destroying a unique item")
        self.hunt_move(h, 0.41, top + 0.095 + row * 0.069)
        mouse_click("R")
        if not self.wait(0.7):
            return False
        ty = find_dialog(h, top + 0.05)
        if ty is None:
            log("HUNT destroy: the CONFIRMAR dialog did not appear")
            return False
        self.hunt_move(h, 0.4665, ty + 0.106)  # the SI button: left of the middle, a little below the title bar
        mouse_click("L")
        if not self.wait(0.8):
            return False
        gone = find_dialog(h, top + 0.05) is None
        log("HUNT destroy: SI clicked, dialog %s" % ("closed" if gone else "STILL OPEN"))
        return gone

    DANGER_R = 0.25  # minimap units (fraction of the minimap width): keep at least this far from a deadly spot
    ALARM_R = 0.20  # if we are this close to one, stop everything

    @staticmethod
    def seg_dist(p, a, b):
        """Distance from point p to the segment a-b."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
        return ((p[0] - a[0] - t * dx) ** 2 + (p[1] - a[1] - t * dy) ** 2) ** 0.5

    def unsafe(self, a, b, deadly):
        """True if the straight walk a -> b passes within DANGER_R of a deadly spot."""
        for d in deadly:
            start = ((a[0] - d[0]) ** 2 + (a[1] - d[1]) ** 2) ** 0.5
            # already inside the keep-away radius (e.g. standing at the safe limit): only walking away is allowed
            if self.seg_dist(d, a, b) < min(d[2], start - 0.01):
                return True
        return False

    def hunt_deadly_near(self, h, factor):
        """Are we within `factor` x the alarm radius of a deadly spot (red diamond or visor fan)?"""
        player, _, _, deadly = read_minimap(*grab_minimap(h))
        return bool(player) and any(((player[0] - d[0]) ** 2 + (player[1] - d[1]) ** 2) ** 0.5 < factor * d[3]
                                    for d in deadly)

    def hunt_forbidden_for_zone(self, h):
        """The forbidden rectangles were drawn on one zone's minimap: use them only if the map in front of us is that
        zone (same shape), otherwise they would fall on random spots of another map."""
        rects = self.cfg.get("hunt_forbidden")
        if not rects:
            return set_forbidden([])
        d = zone_differs(self.cfg.get("hunt_forbidden_map"), grab_zone(h))
        if d is None or d > 0.25:
            log("HUNT forbidden zones ignored: this is not the map they were drawn on (difference %s)" % (
                "unknown" if d is None else "%.2f" % d))
            return set_forbidden([])
        log("HUNT %d forbidden zone(s) active (map difference %.2f)" % (len(rects), d))
        set_forbidden(rects)

    def hunt_zone_changed(self, h, zone0):
        """The zone name (top right) differs from the one at start: we died / left the zone. Stops the hunt."""
        if zone0 is None or self.hunt_in_combat(h)[0]:
            return False  # the name bar is hidden during a fight
        def diff():
            d = zone_differs(zone0, grab_zone(h))
            return d is not None and d > 0.25  # None: map hidden, we cannot tell
        if not diff():
            return False
        for _ in range(3):  # a real change stays: look again a few times before believing it
            if not self.wait(1.5) or self.hunt_in_combat(h)[0] or not diff():
                log("HUNT zone map looked different for a moment: ignored")
                return False
        log("HUNT zone map changed: stopping")
        self.halt("Zone changed (did you die?): hunt stopped")
        return True

    def hunt_isolated(self, p, others, gap):
        """True if no other point in `others` is closer than `gap` (fraction of the screen width) to p."""
        return all(((p[0] - q[0]) ** 2 + ((p[1] - q[1]) * 0.563) ** 2) ** 0.5 >= gap
                   for q in others if q is not p and q != p)

    def is_npc(self, sig):
        """A name label that failed to start a fight twice (an NPC you can only talk to): never attack it."""
        now = time.time()
        return any(n[2] > now and n[1] >= 2 and sig_similar(sig, n[0]) for n in getattr(self, "npc", []))

    def note_failed_attack(self, sig):
        if not sig:
            return
        now = time.time()
        self.npc = [n for n in getattr(self, "npc", []) if n[2] > now]
        for n in self.npc:
            if sig_similar(sig, n[0]):
                n[1] += 1
                n[2] = now + 1800
                if n[1] == 2:
                    log("HUNT this name label failed twice: treated as an NPC (talk only), ignored for 30 min")
                return
        self.npc.append([sig, 1, now + 1800])

    NEAR = 0.22  # bots this close to the player (fraction of the screen width) are attackable even outside the area
    HOP = 0.12  # minimap units walked per click

    def hunt_candidates(self, h, bad):
        """Bots we may attack: in the chosen area, or right next to the player; and far enough from every other bot
        (so only one enters the fight)."""
        ax0, ay0, ax1, ay1 = self.cfg["hunt_area"]
        allbots = find_bots(h)
        npcs = [p for p in allbots if self.is_npc(BOT_SIG.get(p))]
        if npcs:
            allbots = [p for p in allbots if p not in npcs]
        now = time.time()
        me = find_self(h)
        mine = (me[0], me[1] + BODY_DROP) if me else None
        near = lambda p: bool(mine) and ((p[0] - mine[0]) ** 2 + ((p[1] - mine[1]) * 0.563) ** 2) ** 0.5 <= self.NEAR
        # a body point below 0.78 would be a click on the bottom bar, not on the bot
        eligible = [p for p in allbots if p[1] <= 0.78 and ((ax0 <= p[0] <= ax1 and ay0 <= p[1] <= ay1) or near(p))]
        fresh = lambda p: all(abs(p[0] - b[0]) > 0.05 or abs(p[1] - b[1]) > 0.08 for b in bad if b[2] > now)
        self.hunt_counts = (len(allbots), len(eligible))
        self.hunt_outside = [p for p in allbots if p not in eligible and fresh(p)
                             and self.hunt_isolated(p, allbots, self.cfg["hunt_gap"])]
        return [p for p in eligible if self.hunt_isolated(p, allbots, self.cfg["hunt_gap"]) and fresh(p)], len(allbots)

    def hunt_goto(self, h, target, bad, retreat=False, stop_for_target=True):
        """Walk to a minimap point in short hops. The game picks its own route, so one long click could pass right by
        a visor: every hop is checked against the deadly spots first.
        Returns 'arrived', 'stuck', 'blocked', 'danger', 'combat', 'target' or 'stopped'."""
        mx, my, mw, mh = map_area(h)
        dist = lambda a, b: ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
        stuck = 0
        for _ in range(30):
            player, _, dots, deadly = read_minimap(*grab_minimap(h))
            if not player:
                return "stuck"
            if not retreat and any(dist(player, d) < d[3] for d in deadly):
                return "danger"
            left = dist(player, target)
            if left < 0.04:
                return "arrived"
            k = min(1.0, self.HOP / left)
            nxt = (player[0] + (target[0] - player[0]) * k, player[1] + (target[1] - player[1]) * k)
            if not retreat and self.unsafe(player, nxt, deadly):
                return "blocked"
            if any(dist(nxt, o) < 0.045 for o in dots):
                return "blocked"
            self.hunt_move(h, mx + nxt[0] * mw, my + nxt[1] * mh)
            mouse_click("L")
            last, still, t0 = player, 0.0, time.time()
            while time.time() - t0 < 8:
                if not self.wait(0.4):
                    return "stopped"
                if self.hunt_in_combat(h)[0]:
                    return "combat"
                if stop_for_target and not retreat and self.hunt_candidates(h, bad)[0]:
                    return "target"
                pl, _, _, dd = read_minimap(*grab_minimap(h))
                if not retreat and pl and any(dist(pl, d) < d[3] for d in dd):
                    return "danger"
                if pl and abs(pl[0] - last[0]) < 0.008 and abs(pl[1] - last[1]) < 0.008:
                    still += 0.4
                    if still >= 1.2:
                        break
                else:
                    still = 0.0
                last = pl or last
            if dist(last, player) < 0.015:
                stuck += 1
                if stuck >= 2:
                    return "stuck"
            else:
                stuck = 0
        return "arrived"

    def hunt_retreat(self, h):
        """Walk back to the last safe position (or the start) after getting too close to a deadly spot."""
        target = self.safe_pos or self.home
        if not target:
            return False
        self.hunt_say("DANGER: moving away from a deadly bot")
        for attempt in (1, 2):
            r = self.hunt_goto(h, target, [], retreat=True, stop_for_target=False)
            log("HUNT retreat %d towards (%.3f,%.3f): %s" % (attempt, target[0], target[1], r))
            if r == "stopped":
                return False
            if not self.hunt_deadly_near(h, 1.0):
                return True
        return False

    def hunt_alarm(self, h):
        """Too close to a deadly spot (red diamond or visor)? Retreat to the last safe position and go on; stop only if
        the retreat does not work. True if danger was found (and dealt with or stopped)."""
        player, _, _, deadly = read_minimap(*grab_minimap(h))
        if player and any(((player[0] - d[0]) ** 2 + (player[1] - d[1]) ** 2) ** 0.5 < d[3] for d in deadly):
            log("HUNT DANGER: deadly diamond / visor close to the player (%.3f,%.3f)" % player)
            if not self.hunt_retreat(h):
                self.halt("DANGER: a deadly bot (red or with a visor) is close and I could not back off. Hunt stopped")
            return True
        if player and all(((player[0] - d[0]) ** 2 + (player[1] - d[1]) ** 2) ** 0.5 > 1.6 * d[3] for d in deadly):
            self.safe_pos = player
        return False

    def hunt_walk(self, h, tried, bad):
        """Walk (in hops) next to the nearest isolated bot diamond that is not near a deadly spot or an exit.
        True if it did something."""
        buf, rw, rh = grab_minimap(h)
        player, diamonds, dots, deadly = read_minimap(buf, rw, rh)
        now = time.time()
        tried[:] = [t for t in tried if t[2] > now]
        dist = lambda a, b: ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
        gap = self.cfg["hunt_map_gap"]
        free = [d for d in diamonds
                if all(dist(d, q) > q[2] for q in deadly)  # never near a deadly spot
                and all(dist(d, q) >= gap for q in diamonds if q != d)  # alone
                and all(abs(d[0] - t[0]) > 0.04 or abs(d[1] - t[1]) > 0.04 for t in tried)]
        if now - getattr(self, "_mlog", 0) > 3:
            self._mlog = now
            log("HUNT minimap: player=%s diamonds=%d alone-and-new=%d deadly=%d dots=%d" % (
                "yes" if player else "NOT FOUND", len(diamonds), len(free), len(deadly), len(dots)))
        if not player or not free:
            return False
        d = min(free, key=lambda q: dist(q, player))
        tried.append((d[0], d[1], now + 45))
        # stop a little short of the diamond, on the player side
        k = min(0.07 / max(dist(d, player), 1e-6), 0.9)
        goal = (d[0] + (player[0] - d[0]) * k, d[1] + (player[1] - d[1]) * k)
        self.hunt_say("walking to a bot (minimap)")
        log("HUNT walk: diamond (%.3f,%.3f) player (%.3f,%.3f) goal (%.3f,%.3f)" % (d + player + goal))
        r = self.hunt_goto(h, goal, bad)
        log("HUNT walk result: %s" % r)
        if r == "danger":
            self.hunt_alarm(h)
            return True
        return r in ("arrived", "combat", "target", "stopped")

    def hunt_go_home(self, h, home):
        """Walk back to where the hunt started. True if we moved."""
        player, _, dots, deadly = read_minimap(*grab_minimap(h))
        if not player or ((player[0] - home[0]) ** 2 + (player[1] - home[1]) ** 2) ** 0.5 < 0.05:
            return False
        if any(((home[0] - o[0]) ** 2 + (home[1] - o[1]) ** 2) ** 0.5 < 0.045 for o in dots):
            return False  # the starting point is right next to an exit: do not click there
        self.hunt_say("going back to the starting point")
        log("HUNT going back to the start: player (%.3f,%.3f) home (%.3f,%.3f)" % (player + home))
        r = self.hunt_goto(h, home, [], stop_for_target=False)
        log("HUNT going home result: %s" % r)
        if r == "danger":
            self.hunt_alarm(h)
        return r in ("arrived", "combat", "stopped", "danger")

    def hunt_patrol_step(self, h, st, home):
        """One leg of the patrol: walk (in hops) to a minimap point far from the ones already visited. Bot diamonds only
        show up on the minimap after moving, so we walk a tour of K points, dwelling at each one so that the scene
        scan can find bots. Unreachable or unsafe points are dropped."""
        dist = lambda a, b: ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
        player, _, dots, deadly = read_minimap(*grab_minimap(h))
        if not player:
            return False
        if "pts" not in st:  # new tour: grid of candidate points, farthest-first from the start
            grid = [(0.12 + 0.11 * i, 0.12 + 0.11 * j) for i in range(8) for j in range(8)]
            grid = [p for p in grid if all(dist(p, o) > 0.08 for o in dots)]
            order, ref = [], [home or player]
            while grid and len(order) < 40:
                p = max(grid, key=lambda q: min(dist(q, r) for r in ref))
                grid.remove(p)
                order.append(p)
                ref.append(p)
            st["pts"], st["done"] = order, 0
            log("HUNT patrol: new tour, %d candidate points" % len(order))
        for _ in range(4):  # try up to 4 candidates for this leg
            if st["done"] >= self.cfg["hunt_tour"] or not st["pts"]:
                return False
            p = st["pts"].pop(0)
            if any(dist(p, d) < d[2] for d in deadly) or self.unsafe(player, p, deadly):
                log("HUNT patrol point (%.2f,%.2f) skipped: a deadly spot is near it or the way" % p)
                continue
            self.hunt_say("patrol: walking to point %d/%d" % (st["done"] + 1, self.cfg["hunt_tour"]))
            r = self.hunt_goto(h, p, [], stop_for_target=True)
            now_pl = read_minimap(*grab_minimap(h))[0] or player
            moved = dist(now_pl, player)
            log("HUNT patrol point (%.2f,%.2f): %s, moved %.3f on the minimap" % (p[0], p[1], r, moved))
            if r == "danger":
                self.hunt_alarm(h)
                return True
            if r in ("combat", "target", "stopped"):
                return True
            if moved >= 0.03:
                st["done"] += 1
                st["dwell"] = time.time() + 3.0
                return True
            player = now_pl
        return False
    def w_hunt(self):
        stats.start()
        live.update(running=True, since=time.time())
        try:
            self.w_hunt_loop()
        finally:
            live.update(running=False, status="stopped")
            stats.stop()
            log(stats.summary_line())  # the last summary, whatever way the hunt ended

    def w_hunt_loop(self):
        """Find living bots by their name label, attack the nearest isolated one, fight, loot; with the minimap walk
        to the next bot when none is in the area."""
        h = self.game()
        self.hunt_forbidden_for_zone(h)
        park = (0.55, 0.935)  # chat area: no hover tooltips while we look at the scene
        patrol = {}  # state of the patrol tour
        chase = 0  # approach steps towards bots outside the area since the last target
        bad, tried = [], []  # (fx, fy, until): spots where an attack did not start a fight / minimap targets done
        diagnostic.log_window(h)  # the window size goes to the log (and a warning if it is not 16:9)
        if self.cfg.get("llm_enabled"):
            llm.start_warm_up(self.cfg)  # load the vision model now, not in the middle of a fight
        log("HUNT start area=%s gap=%s walk=%s" % (self.cfg["hunt_area"], self.cfg["hunt_gap"], self.cfg["hunt_walk"]))
        zone0 = grab_zone(h)  # the zone name on top: if it changes we died / left the zone
        home = read_minimap(*grab_minimap(h))[0]  # where we started, on the minimap
        self.home = self.safe_pos = home
        log("HUNT home on minimap: %s" % (home,))
        while self.alive():
            if self.hunt_in_combat(h)[0]:  # a bot attacked us (e.g. while walking): fight it
                self.hunt_say("attacked: fighting")
                if not self.hunt_fight(h):
                    return
                self.hunt_loot(h)
                continue
            if self.hunt_loot_leftover(h):  # a loot window that opened late, after we had given up waiting for it
                continue
            if self.hunt_zone_changed(h, zone0):
                return
            if self.hunt_alarm(h):  # backed off from a deadly bot (or stopped): look again
                continue
            hp = read_health(h)
            if hp < self.cfg["hunt_min_health"]:  # a tough bot left us low: do nothing new until we have healed
                if self.cfg.get("heal_item") and time.time() > getattr(self, "_heal_retry", 0):
                    ate = self.hunt_heal(h)
                    stats.add("heals" if ate else "heal_failed")
                    if not self.alive():
                        return
                    if not ate:
                        self._heal_retry = time.time() + 60  # it did not work: do not try again for a minute
                    continue
                self.hunt_say("health %d%% is below %d%%: waiting to heal" % (hp * 100, self.cfg["hunt_min_health"] * 100))
                if time.time() - getattr(self, "_hlog", 0) > 15:
                    self._hlog = time.time()
                    log("HUNT health %.0f%% < %.0f%%: waiting" % (hp * 100, self.cfg["hunt_min_health"] * 100))
                if not self.wait(1.5):
                    return
                continue
            self.hunt_move(h, *park)
            bad = [b for b in bad if b[2] > time.time()]
            bots, seen = self.hunt_candidates(h, bad)
            if not bots:
                if seen and time.time() - getattr(self, "_clog", 0) > 3:
                    self._clog = time.time()
                    log("HUNT no candidate: %d bots on screen, %d in area/near, gap=%.2f, recently failed=%d" % (
                        self.hunt_counts + (self.cfg["hunt_gap"], len(bad))))
                if self.cfg["hunt_walk"] and self.hunt_walk(h, tried, bad):
                    continue
                if self.cfg["hunt_walk"] and self.hunt_outside and not self.hunt_deadly_near(h, 2.0):
                    # no lone bot in the area and none on the minimap: walk towards one that is on screen outside it
                    chase += 1
                    tgt = min(self.hunt_outside, key=lambda p: (p[0] - 0.5) ** 2 + (p[1] - 0.65) ** 2)
                    if chase > 4:
                        bad += [(p[0], p[1], time.time() + 30) for p in self.hunt_outside]
                        chase = 0
                    elif self.hunt_approach(h, tgt):
                        log("HUNT chase %d towards (%.3f,%.3f)" % (chase, tgt[0], tgt[1]))
                        continue
                if self.cfg["hunt_walk"] and self.cfg["hunt_patrol"]:
                    now = time.time()
                    if now < patrol.get("dwell", 0) or now < patrol.get("rest", 0):
                        self.hunt_say("patrol: looking around")
                        if not self.wait(0.8):
                            return
                        continue
                    if self.hunt_patrol_step(h, patrol, home):
                        continue
                    if "pts" in patrol:  # tour finished (or nothing reachable): rest at the start, then start over
                        patrol.pop("pts")
                        patrol["rest"] = time.time() + 30
                        log("HUNT patrol: tour finished")
                        if self.cfg["hunt_home"] and home and self.hunt_go_home(h, home):
                            continue
                if self.cfg["hunt_walk"] and self.cfg["hunt_home"] and home and self.hunt_go_home(h, home):
                    continue
                self.hunt_say("no bot to attack (on screen %d, in area %d, alone-and-new 0)" % self.hunt_counts)
                if not self.wait(0.8):
                    return
                continue
            chase = 0
            target = bots[0]
            tsig = BOT_SIG.get(target)
            log("HUNT bots=%d target=(%.3f,%.3f)" % (len(bots), target[0], target[1]))
            if not self.hunt_engage(h, target):
                if not self.alive():
                    return
                self.note_failed_attack(tsig)
                wait_s = 180 if self.attack_refused else 30  # next to a door: leave that bot alone for a while
                log("HUNT no fight started at that spot: ignoring it for %d s" % wait_s)
                bad.append((target[0], target[1], time.time() + wait_s))
                continue
            if not self.hunt_fight(h, (target[0], target[1])):
                return
            self.hunt_loot(h)  # /loot opens the window whatever the corpse position
            if not self.wait(0.5):
                return


__all__ = [n for n in list(globals()) if not n.startswith("__")]
