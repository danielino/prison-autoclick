"""The control window: autoclick settings, slots, library, hunt area and forbidden zones."""
import copy, ctypes, json, os, random, re, sys, threading, time
from ctypes import wintypes
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from .config import *
from .winapi import *
from .vision import *
from .minimap import *
from . import llm


class Gui:
    """Control window: autoclick delay, the 9 sequence slots with names, and a library of named sequences."""

    def __init__(self, app):
        self.app, self.cfg = app, app.cfg
        w = self.win = tk.Toplevel(app.root)
        w.title("AutoPrison")
        w.geometry("780x720")
        w.minsize(680, 680)
        w.protocol("WM_DELETE_WINDOW", app.root.destroy)  # closing this window quits the program

        nb = self.nb = ttk.Notebook(w)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        tab_click, tab_hunt, tab_vision, tab_seq = (ttk.Frame(nb) for _ in range(4))
        nb.add(tab_click, text="  Autoclick  ")
        nb.add(tab_hunt, text="  Auto-hunt  ")
        nb.add(tab_vision, text="  Vision  ")
        nb.add(tab_seq, text="  Sequences  ")

        # ---- tab 1: autoclick -------------------------------------------------------------------------------
        top = ttk.LabelFrame(tab_click, text="Autoclick (menu option 1)")
        top.pack(fill="x", padx=10, pady=(10, 4))
        self.delay = tk.StringVar(value=str(int(round(self.cfg["click_interval"] * 1000))))
        self.jit = tk.StringVar(value=str(int(round(self.cfg["jitter"] * 100))))
        self.speed = tk.StringVar(value="%g" % self.cfg["speed"])
        self.settle = tk.StringVar(value=str(int(round(self.cfg["bg_settle"] * 1000))))
        self.rep = tk.StringVar(value="%g" % max(self.cfg["repeat_interval"], 5.0))
        for col, (label, var, lo, hi, inc) in enumerate((
                ("Delay between clicks (ms)", self.delay, 10, 60000, 10),
                ("Random variation (Â±%)", self.jit, 0, 90, 5),
                ("Sequence speed (x)", self.speed, 0.1, 8, 0.05),
                ("Auto-fight delay (s, min 5)", self.rep, 5, 300, 0.5))):
            ttk.Label(top, text=label).grid(row=0, column=col, padx=8, pady=(6, 0), sticky="w")
            self.spin(top, var, lo, hi, inc, 10, self.apply).grid(row=1, column=col, padx=8, pady=(0, 8), sticky="w")
        ttk.Label(top, text="Delay and variation apply to autoclick; speed applies to recorded sequences.",
                  foreground="gray").grid(row=2, column=0, columnspan=4, padx=8, pady=(0, 6), sticky="w")

        bgf = ttk.LabelFrame(tab_click, text="Background mode (experimental)")
        bgf.pack(fill="x", padx=10, pady=4)
        self.bgvar = tk.BooleanVar(value=bool(self.cfg["background"]))
        ttk.Checkbutton(bgf, variable=self.bgvar, command=self.apply, text=(
            "Send the clicks to the game window without moving your mouse, so you can use other programs.\n"
            "Keep the game window open, not minimized. F12 stops from anywhere.")).grid(
            row=0, column=0, columnspan=2, padx=8, pady=(6, 4), sticky="w")
        ttk.Label(bgf, text="Pause before each click (ms)").grid(row=1, column=0, padx=8, pady=(0, 8), sticky="w")
        self.spin(bgf, self.settle, 0, 2000, 25, 10, self.apply).grid(row=1, column=1, padx=8, pady=(0, 8), sticky="w")

        # ---- tab 2: auto-hunt -------------------------------------------------------------------------------
        hunt = ttk.LabelFrame(tab_hunt, text="Area (bots outside this rectangle are ignored)")
        hunt.pack(fill="x", padx=10, pady=(10, 4))
        self.cv = tk.Canvas(hunt, width=240, height=135, bg="#1b1b1b", highlightthickness=1,
                            highlightbackground="#666")
        self.cv.grid(row=0, column=0, rowspan=3, padx=8, pady=8)
        self.harea = [tk.StringVar() for _ in range(4)]
        for col, (label, var) in enumerate(zip(("Left (%)", "Top (%)", "Right (%)", "Bottom (%)"), self.harea)):
            ttk.Label(hunt, text=label).grid(row=0, column=1 + col, padx=6, pady=(8, 0), sticky="w")
            self.spin(hunt, var, 0, 100, 1, 7, self.apply_area).grid(row=1, column=1 + col, padx=6, sticky="w")
        ttk.Button(hunt, text="Clear area", command=self.clear_area).grid(row=1, column=5, padx=6, sticky="w")
        self.hinfo = ttk.Label(hunt, foreground="gray", wraplength=470, justify="left")
        self.hinfo.grid(row=2, column=1, columnspan=5, padx=6, pady=(4, 8), sticky="w")

        self.gap = tk.StringVar(value="%g" % round(self.cfg["hunt_gap"] * 100, 1))
        self.mgap = tk.StringVar(value="%g" % round(self.cfg["hunt_map_gap"] * 100, 1))
        self.hmin = tk.StringVar(value="%g" % round(self.cfg["hunt_min_health"] * 100))
        self.lootwait = tk.StringVar(value="%g" % self.cfg.get("loot_again_delay", 3.0))
        self.walkvar = tk.BooleanVar(value=bool(self.cfg["hunt_walk"]))
        self.patrolvar = tk.BooleanVar(value=bool(self.cfg["hunt_patrol"]))
        self.homevar = tk.BooleanVar(value=bool(self.cfg["hunt_home"]))
        self.destroyvar = tk.BooleanVar(value=bool(self.cfg["hunt_destroy_unique"]))
        self.llmvar = tk.BooleanVar(value=bool(self.cfg.get("llm_enabled")))
        self.llmurl = tk.StringVar(value=self.cfg.get("ollama_url", llm.DEFAULT_URL))
        self.llmmodel = tk.StringVar(value=self.cfg.get("ollama_model", llm.DEFAULT_MODEL))
        self.llmmode = tk.StringVar(value=self.cfg.get("llm_mode", "assist"))
        self.llmtimeout = tk.StringVar(value="%g" % self.cfg.get("llm_timeout", 20))
        self.llmwidth = tk.StringVar(value=str(int(self.cfg.get("llm_max_width", 1024))))

        pick = ttk.LabelFrame(tab_hunt, text="Choosing bots")
        pick.pack(fill="x", padx=10, pady=4)
        ttk.Label(pick, text="Min distance between bots, screen (% of width)").grid(
            row=0, column=0, padx=8, pady=(6, 6), sticky="w")
        self.spin(pick, self.gap, 0, 100, 1, 6, self.apply).grid(row=0, column=1, padx=(0, 18))
        ttk.Label(pick, text="on the minimap (%)").grid(row=0, column=2, sticky="w")
        self.spin(pick, self.mgap, 0, 100, 1, 6, self.apply).grid(row=0, column=3, padx=(6, 8))

        move = ttk.LabelFrame(tab_hunt, text="Movement")
        move.pack(fill="x", padx=10, pady=4)
        for text, var in (
                ("Walk to the next lone bot by clicking the minimap when none is in the area "
                 "(avoids the fixed orange points = exits)", self.walkvar),
                ("Patrol: when nothing is found, walk a tour of minimap points (bots show on the minimap only "
                 "after moving)", self.patrolvar),
                ("When no lone bot is left, walk back to the starting point of the hunt", self.homevar)):
            ttk.Checkbutton(move, variable=var, command=self.apply, text=text).pack(anchor="w", padx=8, pady=(4, 0))
        zrow = ttk.Frame(move)
        zrow.pack(anchor="w", padx=8, pady=(6, 8))
        ttk.Button(zrow, text="Forbidden zones on the minimapâ€¦", command=self.zones_dialog).pack(side="left")
        self.zinfo = ttk.Label(zrow, foreground="gray")
        self.zinfo.pack(side="left", padx=8)
        self.zones_label()

        care = ttk.LabelFrame(tab_hunt, text="Health and loot")
        care.pack(fill="x", padx=10, pady=4)
        ttk.Label(care, text="Heal (or wait) while health is below (%)").grid(
            row=0, column=0, padx=8, pady=(6, 0), sticky="w")
        self.spin(care, self.hmin, 0, 100, 5, 6, self.apply).grid(row=0, column=1, pady=(6, 0), sticky="w")
        self.hfood = ttk.Label(care, foreground="gray")
        self.hfood.grid(row=1, column=0, columnspan=3, padx=8, pady=(2, 0), sticky="w")
        ttk.Label(care, text="Pause before the next /loot (s)").grid(row=2, column=0, padx=8, pady=(6, 0), sticky="w")
        self.spin(care, self.lootwait, 0, 10, 0.5, 6, self.apply).grid(row=2, column=1, pady=(6, 0), sticky="w")
        ttk.Checkbutton(care, variable=self.destroyvar, command=self.apply, text=(
            "Destroy UNIQUE items we already own (right click, then Yes) so the next one can be picked up")).grid(
            row=3, column=0, columnspan=3, padx=8, pady=(6, 8), sticky="w")
        self.build_vision(tab_vision)
        self.hunt_last = "unset"
        self.hunt_sync()

        # ---- tab 3: sequences -------------------------------------------------------------------------------
        body = ttk.Frame(tab_seq)
        body.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        body.columnconfigure((0, 1), weight=1, uniform="c")
        body.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(body, text="Slots (keys 1-9 in game)")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.slots = self.tree(left, ("slot", "name", "clicks"), ("Slot", "Name", "Clicks"), (45, 190, 55))
        self.slots.bind("<Double-1>", lambda e: self.rename_slot())
        bar = ttk.Frame(left)
        bar.pack(fill="x", padx=6, pady=6)
        for text, cmd in (("Rename", self.rename_slot), ("Clear", self.clear_slot),
                          ("Save to library â†’", self.to_library)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 4))

        right = ttk.LabelFrame(body, text="Library (saved sequences)")
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.lib = self.tree(right, ("name", "clicks"), ("Name", "Clicks"), (210, 55))
        self.lib.bind("<Double-1>", lambda e: self.rename_lib())
        bar = ttk.Frame(right)
        bar.pack(fill="x", padx=6, pady=6)
        for text, cmd in (("â† Load into slot", self.from_library), ("Rename", self.rename_lib),
                          ("Delete", self.delete_lib)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 4))

        ttk.Label(tab_seq, foreground="gray", wraplength=720, text=(
            "Record in game: TAB, 2, then 1-9. Play: TAB, 3, then 1-9. Name a slot, save it to the library, "
            "and load it back into any slot later.")).pack(fill="x", padx=12, pady=(2, 10))
        self.refresh()

    @staticmethod
    def spin(parent, var, lo, hi, inc, width, callback):
        """A spinbox that applies its value as soon as it changes (arrows, typing, leaving the field)."""
        sp = ttk.Spinbox(parent, from_=lo, to=hi, increment=inc, textvariable=var, width=width, command=callback)
        sp.bind("<KeyRelease>", lambda e: callback())
        sp.bind("<FocusOut>", lambda e: callback())
        return sp

    @staticmethod
    def tree(parent, cols, heads, widths):
        t = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse", height=9)
        for c, h, wd in zip(cols, heads, widths):
            t.heading(c, text=h)
            t.column(c, width=wd, anchor="w" if c == "name" else "center")
        t.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        return t

    # -- settings
    def apply(self):
        self.cfg["background"] = bool(self.bgvar.get())
        try:
            self.cfg["click_interval"] = min(max(float(self.delay.get()), 10), 60000) / 1000
            self.cfg["jitter"] = min(max(float(self.jit.get()), 0), 90) / 100
            self.cfg["speed"] = min(max(float(self.speed.get().replace(",", ".")), 0.1), 8)
            self.cfg["bg_settle"] = min(max(float(self.settle.get()), 0), 2000) / 1000
            self.cfg["repeat_interval"] = min(max(float(self.rep.get().replace(",", ".")), 5), 300)
            self.cfg["hunt_gap"] = min(max(float(self.gap.get().replace(",", ".")), 0), 100) / 100
            self.cfg["hunt_map_gap"] = min(max(float(self.mgap.get().replace(",", ".")), 0), 100) / 100
            self.cfg["hunt_min_health"] = min(max(float(self.hmin.get().replace(",", ".")), 0), 100) / 100
            self.cfg["loot_again_delay"] = min(max(float(self.lootwait.get().replace(",", ".")), 0), 10)
            self.cfg["hunt_destroy_unique"] = bool(self.destroyvar.get())
            self.cfg["hunt_walk"] = bool(self.walkvar.get())
            self.cfg["hunt_home"] = bool(self.homevar.get())
            self.cfg["hunt_patrol"] = bool(self.patrolvar.get())
            self.cfg["llm_timeout"] = min(max(float(self.llmtimeout.get().replace(",", ".")), 2), 300)
            self.cfg["llm_max_width"] = int(min(max(float(self.llmwidth.get()), 256), 2048))
            self.cfg["llm_enabled"] = bool(self.llmvar.get())
            self.cfg["ollama_url"] = self.llmurl.get().strip() or llm.DEFAULT_URL
            self.cfg["ollama_model"] = self.llmmodel.get().strip() or llm.DEFAULT_MODEL
            self.cfg["llm_mode"] = self.llmmode.get() if self.llmmode.get() in ("assist", "decide") else "assist"
            llm.reset()  # a changed address or model gets a fresh start
            self.llm_switch()
        except ValueError:
            return  # half-typed value: ignore until it is a number
        save(self.cfg)

    # -- vision helper (Ollama)
    def build_vision(self, tab):
        box = ttk.LabelFrame(tab, text="Ollama server")
        box.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Checkbutton(box, variable=self.llmvar, command=self.apply, text=(
            "Use a vision model in fights: a second opinion on which bot is weakest and how many attacks are left.\n"
            "Screenshots of the game are sent to the server below. Uncheck it to turn the whole feature off.")).grid(
            row=0, column=0, columnspan=4, padx=8, pady=(6, 6), sticky="w")
        ttk.Label(box, text="Server address").grid(row=1, column=0, padx=8, sticky="w")
        eu = ttk.Entry(box, textvariable=self.llmurl, width=34)
        eu.grid(row=1, column=1, columnspan=2, padx=4, sticky="w")
        eu.bind("<KeyRelease>", lambda ev: self.apply())
        b_test = ttk.Button(box, text="Test connection", command=self.llm_test)
        b_test.grid(row=1, column=3, padx=8, sticky="w")
        ttk.Label(box, text="Model").grid(row=2, column=0, padx=8, pady=(6, 0), sticky="w")
        self.llmbox = ttk.Combobox(box, textvariable=self.llmmodel, width=32, values=())
        self.llmbox.grid(row=2, column=1, columnspan=2, padx=4, pady=(6, 0), sticky="w")
        self.llmbox.bind("<<ComboboxSelected>>", lambda ev: self.apply())
        self.llmbox.bind("<KeyRelease>", lambda ev: self.apply())
        row = ttk.Frame(box)
        row.grid(row=2, column=3, padx=8, pady=(6, 0), sticky="w")
        b_list = ttk.Button(row, text="Installed models", command=self.llm_refresh)
        b_list.pack(side="left")
        b_pull = ttk.Button(row, text="Download", command=self.llm_pull)
        b_pull.pack(side="left", padx=(6, 0))
        ttk.Label(box, text="Mode").grid(row=3, column=0, padx=8, pady=(6, 0), sticky="w")
        cm = ttk.Combobox(box, textvariable=self.llmmode, values=("assist", "decide"), width=10, state="readonly")
        cm.grid(row=3, column=1, padx=4, pady=(6, 0), sticky="w")
        cm.bind("<<ComboboxSelected>>", lambda ev: self.apply())
        ttk.Label(box, text="Wait for an answer (s)").grid(row=4, column=0, padx=8, pady=(6, 0), sticky="w")
        s_time = self.spin(box, self.llmtimeout, 2, 300, 1, 8, self.apply)
        s_time.grid(row=4, column=1, padx=4, pady=(6, 0), sticky="w")
        ttk.Label(box, text="Image width (px)").grid(row=4, column=2, padx=(12, 4), pady=(6, 0), sticky="e")
        s_width = self.spin(box, self.llmwidth, 256, 2048, 128, 8, self.apply)
        s_width.grid(row=4, column=3, padx=8, pady=(6, 0), sticky="w")
        b_screen = ttk.Button(box, text="Test on the game screen", command=self.llm_screen)
        b_screen.grid(row=5, column=0, columnspan=2, padx=8, pady=(10, 4), sticky="w")
        self.llmbar = ttk.Progressbar(box, length=300, maximum=100)
        self.llmbar.grid(row=5, column=2, columnspan=2, padx=8, pady=(10, 4), sticky="w")
        self.llminfo = ttk.Label(box, foreground="gray", wraplength=680, justify="left", text="")
        self.llminfo.grid(row=6, column=0, columnspan=4, padx=8, pady=(2, 8), sticky="w")
        ttk.Label(tab, foreground="gray", wraplength=720, justify="left", text=(
            "assist: the colour detectors choose the bot; the model only breaks ties or helps when the health bars cannot "
            "be measured.\ndecide: the model's choice wins.\nAny error or odd answer just means no hint, and after 3 "
            "failures in a row the model is left alone until the program restarts.\nA vision model of 8B parameters "
            "(for example qwen3-vl:8b-instruct) is enough; the Download button does `ollama pull` for the model above.")).pack(
            fill="x", padx=12, pady=(2, 8))
        self.llm_job = None
        self.llm_names = ()
        self.llm_fields = [(eu, "normal"), (self.llmbox, "normal"), (cm, "readonly"), (b_test, "normal"), (b_list, "normal"),
                           (b_pull, "normal"), (s_time, "normal"), (s_width, "normal"), (b_screen, "normal")]
        self.llm_switch()

    def llm_switch(self):
        """With the helper off, its settings are greyed out: nothing is sent anywhere and the program works as without it."""
        on = bool(self.llmvar.get())
        for w, state in self.llm_fields:
            w.configure(state=state if on else "disabled")
        if not on:
            self.llminfo.config(foreground="gray", text="Off: no screenshot is sent anywhere and no model is needed. "
                                "Leave it off on a PC that cannot run Ollama; the program works the same.")

    def llm_run(self, work):
        """Run work(report) in a thread; report(text, fraction=None, done=False, ok=True) is polled by the window."""
        if self.llm_job and self.llm_job["alive"]:
            return
        self.apply()
        job = self.llm_job = {"alive": True, "msg": ("Working...", None, False, True)}

        def report(text, frac=None, done=False, ok=True):
            job["msg"] = (text, frac, done, ok)

        def run():
            try:
                work(report)
            except Exception as e:
                report("Error: %s" % e, None, True, False)
            job["alive"] = False
        threading.Thread(target=run, daemon=True).start()
        self.llm_poll()

    def llm_poll(self):
        job = self.llm_job
        if not job:
            return
        text, frac, done, ok = job["msg"]
        self.llminfo.config(text=text, foreground="gray" if not done else ("#1a7f37" if ok else "#b3261e"))
        if frac is None:
            self.llmbar.config(mode="indeterminate") if not done else self.llmbar.config(mode="determinate", value=0)
            if not done:
                self.llmbar.step(8)
        else:
            self.llmbar.config(mode="determinate", value=frac * 100)
        if done:
            self.llmbox.config(values=self.llm_names)
        if job["alive"] or not done:
            self.win.after(150, self.llm_poll)

    def llm_test(self):
        def work(report):
            ok, text = llm.test_connection(self.cfg)
            report(text, None, True, ok)
            if ok:
                self.llm_models_ready()
        self.llm_run(work)

    def llm_models_ready(self):
        ok, names = llm.list_models(self.cfg)
        if ok:
            self.llm_names = names

    def llm_refresh(self):
        def work(report):
            ok, names = llm.list_models(self.cfg)
            if ok:
                self.llm_names = names
                report("%d models installed: %s" % (len(names), ", ".join(names) or "none"), None, True, True)
            else:
                report(names, None, True, False)
        self.llm_run(work)

    def llm_pull(self):
        def work(report):
            report("Downloading %s ..." % self.cfg["ollama_model"], None)
            ok, text = llm.pull_model(self.cfg, lambda status, frac: report("%s: %s" % (self.cfg["ollama_model"], status), frac))
            report(text, 1.0 if ok else None, True, ok)
        self.llm_run(work)

    def llm_screen(self):
        def work(report):
            h = find_game()
            if not h:
                report("The game window was not found: start the game first.", None, True, False)
                return
            report("Sending the game screen...", None)
            ok, text = llm.test_on_screen(self.cfg, h)
            report(text, None, True, ok)
        self.llm_run(work)

    # -- auto-hunt area (the in-game setup, option 7, writes the same cfg value)
    def hunt_sync(self):
        cur = self.cfg.get("hunt_area")
        if cur != self.hunt_last:
            self.hunt_last = list(cur) if cur else cur
            for var, v in zip(self.harea, cur or ("", "", "", "")):
                var.set("" if v == "" else "%g" % round(v * 100, 2))
        self.draw_area()
        self.hfood.config(text=("Food for healing: saved. " if self.cfg.get("heal_item") else
                                "Food for healing: not set. ") +
                          "In game: TAB, 7, open Ctrl+1, mouse on the food, press F8.")
        self.win.after(500, self.hunt_sync)

    def draw_area(self):
        cv, cur = self.cv, self.cfg.get("hunt_area")
        cv.delete("all")
        cv.create_text(120, 67, text="game window", fill="#555")
        if cur:
            cv.create_rectangle(cur[0] * 240, cur[1] * 135, cur[2] * 240, cur[3] * 135,
                                outline="#ffe14d", width=2, fill="#4d4410", stipple="gray50")
            text = "Saved: left %.1f%%, top %.1f%%, right %.1f%%, bottom %.1f%% of the game window." % tuple(
                v * 100 for v in cur)
            g = find_game()
            if g:
                _, _, w, hh = client_rect(g)
                text += " Now (%dx%d): x %d-%d, y %d-%d px." % (
                    w, hh, cur[0] * w, cur[2] * w, cur[1] * hh, cur[3] * hh)
        else:
            text = "No area saved yet. In game: TAB, 7, put the mouse on a corner and press F9 (top-left) and F10 (bottom-right)."
        self.hinfo.config(text=text)

    def apply_area(self):
        try:
            l, t, r, b = (min(max(float(v.get().replace(",", ".")), 0), 100) / 100 for v in self.harea)
        except ValueError:
            return  # half-typed value
        if r - l < 0.03 or b - t < 0.03:
            return
        self.cfg["hunt_area"] = [round(l, 4), round(t, 4), round(r, 4), round(b, 4)]
        self.hunt_last = list(self.cfg["hunt_area"])
        save(self.cfg)
        self.draw_area()

    def clear_area(self):
        self.cfg["hunt_area"] = None
        save(self.cfg)
        self.hunt_sync_now()

    def hunt_sync_now(self):
        vis = ttk.LabelFrame(tab_hunt, text="Vision helper (Ollama, optional)")
        vis.pack(fill="x", padx=10, pady=4)
        ttk.Checkbutton(vis, variable=self.llmvar, command=self.apply, text=(
            "Ask an Ollama vision model for a second opinion in fights (which bot is weakest, attacks left). "
            "Screenshots of the game are sent to the address below.")).grid(
            row=0, column=0, columnspan=4, padx=8, pady=(6, 2), sticky="w")
        ttk.Label(vis, text="Server").grid(row=1, column=0, padx=8, sticky="w")
        eu = ttk.Entry(vis, textvariable=self.llmurl, width=30)
        eu.grid(row=1, column=1, padx=4, sticky="w")
        ttk.Label(vis, text="Model").grid(row=1, column=2, padx=(12, 4), sticky="w")
        em = ttk.Entry(vis, textvariable=self.llmmodel, width=18)
        em.grid(row=1, column=3, padx=4, sticky="w")
        for e in (eu, em):
            e.bind("<KeyRelease>", lambda ev: self.apply())
        ttk.Label(vis, text="Mode").grid(row=2, column=0, padx=8, pady=(4, 0), sticky="w")
        cm = ttk.Combobox(vis, textvariable=self.llmmode, values=("assist", "decide"), width=8, state="readonly")
        cm.grid(row=2, column=1, padx=4, pady=(4, 0), sticky="w")
        cm.bind("<<ComboboxSelected>>", lambda ev: self.apply())
        ttk.Button(vis, text="Test connection", command=self.llm_test).grid(row=2, column=2, padx=(12, 4), pady=(4, 0), sticky="w")
        self.llminfo = ttk.Label(vis, foreground="gray", wraplength=640, justify="left", text=(
            "assist: the colour detectors choose, the model only breaks ties or helps when the bars cannot be measured. "
            "decide: the model's choice wins."))
        self.llminfo.grid(row=3, column=0, columnspan=4, padx=8, pady=(4, 8), sticky="w")
        self.hunt_last = "unset"
        cur = self.cfg.get("hunt_area")
        self.hunt_last = list(cur) if cur else cur
        for var in self.harea:
            var.set("")
        self.draw_area()

    # -- forbidden zones, drawn on a snapshot of the minimap
    def zones_label(self):
        n = len(self.cfg.get("hunt_forbidden") or [])
        self.zinfo.config(text="%d zone%s: the hunt never walks into them" % (n, "" if n == 1 else "s") if n
                          else "none: the hunt only avoids red diamonds and visors")

    def zones_dialog(self):
        CW = 460
        g = find_game()
        mx, my, mw, mh = map_area(g) if g else MAP_AREA
        if g:
            _, _, gw, gh = client_rect(g)
            CH = int(CW * (mh * gh) / (mw * gw))
        else:
            CH = int(CW * 0.97)
        d = tk.Toplevel(self.win)
        d.title("Forbidden zones on the minimap")
        d.transient(self.win)
        ttk.Label(d, wraplength=CW, justify="left", text=(
            "Drag on the map to mark an area the character must never enter or cross (red). The hunt then walks, "
            "patrols and picks targets around it. Use Capture with the game visible to get the current minimap.")
                  ).pack(padx=10, pady=(10, 4))
        cv = tk.Canvas(d, width=CW, height=CH, bg="#1b1b1b", highlightthickness=1, highlightbackground="#666")
        cv.pack(padx=10, pady=4)
        st = {"img": None, "drag": None, "map": None}

        def redraw():
            cv.delete("all")
            if st["img"]:
                cv.create_image(0, 0, anchor="nw", image=st["img"])
            else:
                cv.create_text(CW // 2, CH // 2, text="no snapshot: press Capture", fill="#777")
            for x0, y0, x1, y1 in self.cfg.get("hunt_forbidden") or []:
                cv.create_rectangle(x0 * CW, y0 * CH, x1 * CW, y1 * CH, outline="#ff4040", width=2,
                                    fill="#ff2020", stipple="gray50")
            self.zones_label()

        def store(rects):
            self.cfg["hunt_forbidden"] = rects
            if st["map"]:  # the zones belong to the map they were drawn on
                self.cfg["hunt_forbidden_map"] = st["map"]
            save(self.cfg)
            redraw()

        def clamp(v, hi):
            return round(min(max(v, 0), hi) / hi, 4)

        def press(e):
            if not st["map"]:  # a zone must be tied to the map it is drawn on
                return messagebox.showinfo("AutoPrison", "Press Capture first: the zones belong to that map.", parent=d)
            st["drag"] = (e.x, e.y)

        def move(e):
            cv.delete("drag")
            if st["drag"]:
                cv.create_rectangle(st["drag"][0], st["drag"][1], e.x, e.y, outline="#ffe14d", dash=(3, 2), tags="drag")

        def release(e):
            if not st["drag"]:
                return
            (sx, sy), st["drag"] = st["drag"], None
            x0, x1 = sorted((clamp(sx, CW), clamp(e.x, CW)))
            y0, y1 = sorted((clamp(sy, CH), clamp(e.y, CH)))
            cv.delete("drag")
            if x1 - x0 >= 0.03 and y1 - y0 >= 0.03:
                store((self.cfg.get("hunt_forbidden") or []) + [[x0, y0, x1, y1]])

        def undo():
            store((self.cfg.get("hunt_forbidden") or [])[:-1])

        def clear():
            store([])

        def snap():
            gg = find_game()
            if not gg or u32.IsIconic(gg):
                return messagebox.showinfo("AutoPrison", "Open the game window (not minimized) first.", parent=d)
            d.withdraw()
            self.win.withdraw()

            def take():
                try:
                    buf, rw, rh = grab_minimap(gg)
                    out = bytearray(b"P6\n%d %d\n255\n" % (CW, CH))
                    for y in range(CH):
                        row = (y * rh // CH) * rw
                        for x in range(CW):
                            i = (row + x * rw // CW) * 4
                            out += bytes((buf[i + 2], buf[i + 1], buf[i]))
                    st["img"] = tk.PhotoImage(data=bytes(out))
                    st["map"] = grab_zone(gg)
                finally:
                    self.win.deiconify()
                    d.deiconify()
                    redraw()
            self.win.after(2500, take)

        cv.bind("<ButtonPress-1>", press)
        cv.bind("<B1-Motion>", move)
        cv.bind("<ButtonRelease-1>", release)
        bar = ttk.Frame(d)
        bar.pack(pady=(4, 10))
        for text, cmd in (("Capture minimap (2.5 s)", snap), ("Undo last", undo), ("Clear all", clear),
                          ("Close", d.destroy)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=4)
        redraw()

    # -- helpers
    def sel(self, tree):
        s = tree.selection()
        return tree.item(s[0], "values")[0] if s else None

    def refresh(self):
        keep_s, keep_l = self.sel(self.slots), self.sel(self.lib)
        self.slots.delete(*self.slots.get_children())
        self.lib.delete(*self.lib.get_children())
        for n in range(1, 10):
            s = str(n)
            evs = self.cfg["sequences"].get(s)
            self.slots.insert("", "end", iid=s, values=(
                s, self.cfg["names"].get(s, "") if evs else "", self.clicks(evs) if evs else "â€”"))
        for name in sorted(self.cfg["library"], key=str.lower):
            self.lib.insert("", "end", iid=name, values=(name, self.clicks(self.cfg["library"][name])))
        if keep_s and self.slots.exists(keep_s):
            self.slots.selection_set(keep_s)
        if keep_l and self.lib.exists(keep_l):
            self.lib.selection_set(keep_l)

    @staticmethod
    def clicks(evs):
        return sum(1 for e in evs if "wait" not in e)

    def ask(self, title, prompt, initial=""):
        v = simpledialog.askstring(title, prompt, initialvalue=initial, parent=self.win)
        return v.strip() if v and v.strip() else None

    def busy(self):
        if self.app.state in ("REC", "RUN"):
            messagebox.showinfo("AutoPrison", "Stop the recording or playback first.", parent=self.win)
            return True
        return False

    # -- slot actions
    def rename_slot(self):
        s = self.sel(self.slots)
        if not s or s not in self.cfg["sequences"]:
            return messagebox.showinfo("AutoPrison", "Select a slot that has a recorded sequence.", parent=self.win)
        name = self.ask("Rename", "Name for slot %s:" % s, self.cfg["names"].get(s, ""))
        if name:
            self.cfg["names"][s] = name
            save(self.cfg)
            self.refresh()

    def clear_slot(self):
        s = self.sel(self.slots)
        if self.busy() or not s or s not in self.cfg["sequences"]:
            return
        if messagebox.askyesno("Clear slot", "Clear slot %s? Save it to the library first to keep it." % s,
                               parent=self.win):
            self.cfg["sequences"].pop(s, None)
            self.cfg["names"].pop(s, None)
            save(self.cfg)
            self.refresh()

    def to_library(self):
        s = self.sel(self.slots)
        if not s or s not in self.cfg["sequences"]:
            return messagebox.showinfo("AutoPrison", "Select a slot that has a recorded sequence.", parent=self.win)
        name = self.cfg["names"].get(s) or self.ask("Save to library", "Name for this sequence:", "Sequence %s" % s)
        if not name:
            return
        if name in self.cfg["library"] and not messagebox.askyesno(
                "Overwrite", "'%s' already exists in the library. Overwrite it?" % name, parent=self.win):
            return
        self.cfg["names"][s] = name
        self.cfg["library"][name] = copy.deepcopy(self.cfg["sequences"][s])
        save(self.cfg)
        self.refresh()

    # -- library actions
    def from_library(self):
        name, s = self.sel(self.lib), self.sel(self.slots)
        if self.busy():
            return
        if not name or not s:
            return messagebox.showinfo("AutoPrison", "Select a library entry and a target slot.", parent=self.win)
        if s in self.cfg["sequences"] and not messagebox.askyesno(
                "Replace", "Slot %s already has a sequence. Replace it?" % s, parent=self.win):
            return
        self.cfg["sequences"][s] = copy.deepcopy(self.cfg["library"][name])
        self.cfg["names"][s] = name
        save(self.cfg)
        self.refresh()

    def rename_lib(self):
        old = self.sel(self.lib)
        if not old:
            return
        new = self.ask("Rename", "New name:", old)
        if not new or new == old:
            return
        if new in self.cfg["library"]:
            return messagebox.showinfo("AutoPrison", "A library entry named '%s' already exists." % new,
                                       parent=self.win)
        self.cfg["library"][new] = self.cfg["library"].pop(old)
        for s, n in self.cfg["names"].items():
            if n == old:
                self.cfg["names"][s] = new
        save(self.cfg)
        self.refresh()

    def delete_lib(self):
        name = self.sel(self.lib)
        if name and messagebox.askyesno("Delete", "Delete '%s' from the library?" % name, parent=self.win):
            self.cfg["library"].pop(name, None)
            save(self.cfg)
            self.refresh()


__all__ = [n for n in list(globals()) if not n.startswith("__")]
