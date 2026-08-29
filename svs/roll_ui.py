# =============================================================================
# roll_ui.py — the piano-roll editor (dark/orange, flat chrome).
# Includes: SETTINGS pane, lyrics -> g2p -> phonemes with a manual-phoneme
# lock, double-click inline editors (phonemes above note, lyrics on note),
# scrub erase, portamento faders, vibrato, curve lanes, thin scroll rails.
# =============================================================================
import json, re
import os, subprocess, tempfile, threading, time
import tkinter as tk
from tkinter import filedialog, messagebox
import numpy as np
from . import synth, manifest
from .plan import plan
import sys

def _base_path():
    """Returns the base path: the bundled temp folder if frozen, else the script folder."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def _exec_dir():
    """Returns the directory containing the executable (for saving settings)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

ROW_H, KEY_W, MIDI_TOP, MIDI_BOT, SCALE = 14, 64, 96, 36, 0.6
CCH = 66 + ROW_H

BG      = "#1b1b1b"
BAR1    = "#141414"
BAR2    = "#2a2a2a"
PANEL   = "#202020"
CHIP    = "#2e2e2e"
LINE    = "#4a4a4a"
GRID    = "#3a3a3a"
FG      = "#f2f2f2"
DIM     = "#9a9a9a"
ACC     = "#f59a23"
ACC_HI  = "#ffb347"
KEYW    = "#9a9a9a"
KEYB    = "#6f6f6f"
LABBG   = "#b9b9b9"
LABFG   = "#222222"
ROLL    = "#2b2b2b"
ROLL_DK = "#262626"
F_BOLD  = ("Helvetica", 10, "bold")
F_BIG   = ("Helvetica", 22, "bold")
F_SMALL = ("Helvetica", 8, "bold")

def is_black(m): return (m % 12) in (1, 3, 6, 8, 10)

CURVE_PARAMS = [("note", "NOTE"), ("pit", "PITCH"), ("vol", "VOLUME"), ("gen", "GENDER"),
                ("voi", "VOICING"), ("bre", "BREATH"), ("bri", "BRIGHT"),
                ("ten", "TENSION"), ("f1", "F1"), ("f2", "F2"), ("f3", "F3")]

class Rail(tk.Canvas):
    def __init__(self, master, orient="vertical", command=None):
        super().__init__(master, bg="#161616", highlightthickness=0,
                         width=10 if orient == "vertical" else 10,
                         height=10 if orient == "horizontal" else 10)
        self.orient = orient; self.command = command
        self.first = 0.; self.last = 1.; self._drag = None
        self.bind("<Button-1>", self._down)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))
        self.bind("<Configure>", lambda e: self._paint())

    def set(self, first, last):
        self.first = float(first); self.last = float(last); self._paint()

    def _paint(self):
        self.delete("all")
        if self.last - self.first >= 0.999: return
        if self.orient == "vertical":
            h = max(1, self.winfo_height())
            y0 = self.first * h; y1 = max(self.last * h, y0 + 24)
            self.create_rectangle(2, y0, self.winfo_width() - 2, min(y1, h), fill="#3f3f3f", outline="")
        else:
            w = max(1, self.winfo_width())
            x0 = self.first * w; x1 = max(self.last * w, x0 + 24)
            self.create_rectangle(x0, 2, min(x1, w), self.winfo_height() - 2, fill="#3f3f3f", outline="")

    def _pos(self, ev):
        return (ev.y / max(1, self.winfo_height())) if self.orient == "vertical" \
            else (ev.x / max(1, self.winfo_width()))

    def _down(self, ev):
        p = self._pos(ev)
        if self.first <= p <= self.last:
            self._drag = p - self.first
        else:
            self._drag = (self.last - self.first) / 2
            self._go(p - self._drag)

    def _move(self, ev):
        if self._drag is not None: self._go(self._pos(ev) - self._drag)

    def _go(self, v):
        if self.command:
            self.command(max(0., min(1. - (self.last - self.first), v)))

class VSlider(tk.Canvas):
    def __init__(self, master, var, lo, hi, length=110, command=None):
        super().__init__(master, width=24, height=length + 14, bg=BAR2,
                         highlightthickness=0, cursor="hand2")
        self.var = var; self.lo = lo; self.hi = hi; self.length = length
        self.command = command
        self.bind("<Button-1>", self._down)
        self.bind("<B1-Motion>", self._move)
        self.bind("<Configure>", lambda e: self._paint())
        var.trace_add("write", lambda *a: self._paint())
        self._paint()

    def _frac(self):
        return (self.var.get() - self.lo) / max(1e-9, self.hi - self.lo)

    def _paint(self):
        self.delete("all")
        L = self.length; x = 12
        self.create_rectangle(x - 2, 7, x + 2, 7 + L, fill="#3a3a3a", outline="")
        y = 7 + L * (1 - max(0., min(1., self._frac())))
        self.create_rectangle(x - 2, y, x + 2, 7 + L, fill=ACC, outline="")
        self.create_rectangle(x - 7, y - 5, x + 7, y + 5, fill="#e8e8e8", outline="")

    def _val(self, y):
        f = 1 - max(0., min(1., (y - 7) / self.length))
        return self.lo + f * (self.hi - self.lo)

    def _down(self, ev):
        self.var.set(self._val(ev.y))
        if self.command: self.command()

    def _move(self, ev):
        self.var.set(self._val(ev.y))
        if self.command: self.command()

class HSlider(tk.Canvas):
    def __init__(self, master, var, lo, hi, command=None):
        super().__init__(master, height=20, bg=BAR2, highlightthickness=0, cursor="hand2")
        self.var = var; self.lo = lo; self.hi = hi; self.command = command
        self.bind("<Button-1>", self._down)
        self.bind("<B1-Motion>", self._move)
        self.bind("<Configure>", lambda e: self._paint())
        var.trace_add("write", lambda *a: self._paint())
        self._paint()

    def _frac(self):
        return (self.var.get() - self.lo) / max(1e-9, self.hi - self.lo)

    def _paint(self):
        self.delete("all")
        W = max(40, self.winfo_width())
        self.create_rectangle(4, 8, W - 4, 12, fill="#3a3a3a", outline="")
        x = 4 + (W - 8) * max(0., min(1., self._frac()))
        self.create_rectangle(x - 4, 4, x + 4, 16, fill="#e8e8e8", outline="")

    def _val(self, x):
        W = max(40, self.winfo_width())
        f = max(0., min(1., (x - 4) / max(1., W - 8)))
        return self.lo + f * (self.hi - self.lo)

    def _down(self, ev):
        self.var.set(self._val(ev.x))
        if self.command: self.command()

    def _move(self, ev):
        self.var.set(self._val(ev.x))
        if self.command: self.command()

class Note:
    __slots__ = ("start", "dur", "midi", "phonemes", "onsets", "chain", "vow", "rel",
                 "ov", "pre", "pt_ol", "pt_or", "pt_dl", "pt_dr", "pt_depl", "pt_depr",
                 "end", "lyric", "locked")
    def __init__(self, start, dur, midi, phonemes=None, onsets=None):
        self.start, self.dur, self.midi = float(start), float(dur), int(midi)
        self.phonemes = phonemes or ["a"]
        self.onsets = onsets or [0.0]
        self.chain = self.vow = self.rel = None
        self.ov = {}; self.pre = None
        self.pt_ol = 0.; self.pt_or = 0.
        self.pt_dl = 120.; self.pt_dr = 120.
        self.pt_depl = 0.; self.pt_depr = 0.
        self.end = self.start + self.dur
        self.lyric = None
        self.locked = False

class Roll2App(tk.Tk):
    CURVE_READY = ("pit", "vol", "gen", "voi", "bre", "bri", "ten", "f1", "f2", "f3")
    CURVE_RANGE = {"vol": (0., 2.), "gen": (0., 2.), "voi": (0., 1.),
                   "pit": (36., 96.), "bre": (0., 2.),
                   "bri": (-18., 18.), "ten": (-18., 18.),
                   "f1": (200., 1200.), "f2": (600., 3000.), "f3": (1500., 4000.)}
    CURVE_NEUTRAL = {"vol": 1., "gen": 1., "voi": 1., "bre": 1., "bri": 0., "ten": 0.}
    PARAMS = [("vol", "VOLUME", 100, 200), ("gen", "GENDER", 50, 100),
              ("gsh", "G-SHIFT", 10, 100), ("pit", "PITCH", 50, 100),
              ("voi", "VOICING", 100, 100), ("bre", "BREATH", 50, 100),
              ("bri", "BRIGHT", 50, 100), ("ten", "TENSION", 50, 100),
              ("mod", "MOD", 100, 100), ("ope", "OPEN", 50, 100)]
    SET_KEYS = ("gsh", "gen", "pit", "voi", "bre", "bri", "ten")
    SETTINGS_PATH = os.path.join(_exec_dir(), "roll_settings.json")

    def __init__(self):
        super().__init__()
        self.title("SVS Piano Roll")
        self.geometry("1280x800")
        self.configure(bg=BG)
        self.db = self.y = self.sel = None
        self.drag = self.drag_s = None
        self._snap = None
        self.notes = []
        self.player = None
        self.playing = False
        self.play_ms = 0.
        self.dirty = True
        self.tool = tk.StringVar(value="select")
        self.show_pitch = tk.BooleanVar(value=True)
        self.curve_open = False
        self._voice_map = {}
        self._ph_edit = None; self._ph_win = None
        self._undo = []; self._redo = []; self._pre = None
        self._restoring = False
        self._seq_path = None
        self.curves = {k: [] for k, _n in CURVE_PARAMS if k != "note"}
        self._curve_tmp = None
        self.curve_param = "note"
        self.vibratos = []
        self._pt_trans = []
        self.pv = {k: tk.DoubleVar(value=d) for k, _n, d, _m in self.PARAMS}
        self._params_win = None
        st = self._load_settings()
        self.set_exc = tk.StringVar(value=st.get("exc_template", "delta"))
        self.set_spp = tk.BooleanVar(value=bool(st.get("use_spp", True)))
        for k, v in (st.get("defaults") or {}).items():
            if k in self.pv:
                try: self.pv[k].set(float(v))
                except Exception: pass
        m1 = tk.Frame(self, bg=BAR1); m1.pack(fill="x")
        def mbtn(txt, cmd):
            b = tk.Label(m1, text=txt, bg=BAR1, fg=FG, font=F_BOLD, cursor="hand2")
            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>", lambda e: b.configure(fg=ACC))
            b.bind("<Leave>", lambda e: b.configure(fg=FG))
            b.pack(side="left", padx=4, pady=8)
        def sep():
            tk.Label(m1, text="|", bg=BAR1, fg="#555555", font=F_BOLD).pack(side="left")
        mbtn("SAVE", self.save_seq); sep(); mbtn("LOAD", self.load_seq)
        sep(); mbtn("NEW", self.new_seq)
        tk.Frame(m1, bg=BAR1, width=40).pack(side="left")
        mbtn("UNDO", self.undo); sep(); mbtn("REDO", self.redo)
        b = tk.Label(m1, text="SETTINGS", bg=BAR1, fg=DIM, font=F_BOLD, cursor="hand2")
        b.bind("<Button-1>", lambda e: self.toggle_settings())
        b.bind("<Enter>", lambda e, b=b: b.configure(fg=ACC))
        b.bind("<Leave>", lambda e, b=b: b.configure(fg=DIM))
        b.pack(side="right", padx=4, pady=8)
        m2 = tk.Frame(self, bg=BAR2); self.m2 = m2; m2.pack(fill="x", padx=8, pady=6)
        self.b_voice = tk.Label(m2, text="voice", bg=ACC, fg="#111111", font=F_BOLD,
                                cursor="hand2", padx=10, pady=6)
        self.b_voice.pack(side="left", padx=6, pady=6)
        self.b_voice.bind("<Button-1>", lambda e: self.voice_menu())
        self.l_cache = tk.Label(m2, text="PLAYBACK\nCACHED", bg=BAR2, fg=ACC, font=F_BOLD, justify="left")
        self.l_cache.pack(side="left", padx=14)
        self.e_bpm = tk.Entry(m2, width=4, bg=BAR2, fg=FG, bd=0, font=F_BIG, insertbackground=FG, justify="center")
        self.e_bpm.insert(0, "120"); self.e_bpm.pack(side="left", padx=4)
        tk.Label(m2, text="BPM", bg=BAR2, fg=FG, font=F_SMALL).pack(side="left")
        self.l_time = tk.Label(m2, text="00:00:00", bg=BAR2, fg=FG, font=F_BIG)
        self.l_time.pack(side="left", padx=18)
        self.e_sig = tk.Entry(m2, width=4, bg=BAR2, fg=FG, bd=0, font=F_BIG, insertbackground=FG, justify="center")
        self.e_sig.insert(0, "4/4"); self.e_sig.pack(side="left", padx=4)
        tk.Label(m2, text="TIMESIG", bg=BAR2, fg=FG, font=F_SMALL).pack(side="left")
        TF = ("Helvetica", 18, "bold")
        def tbtn(txt, cmd):
            b = tk.Label(m2, text=txt, bg=BAR2, fg=FG, font=TF, cursor="hand2", width=3, anchor="center")
            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>", lambda e, b=b: b.configure(fg=ACC))
            b.bind("<Leave>", lambda e, b=b: b.configure(fg=FG))
            b.pack(side="left", padx=4)
            return b
        self.b_play = tbtn("▶", self.toggle_play)
        b_stop = tbtn("◼", self.stop)
        b_stop.bind("<Double-Button-1>", lambda e: self.rewind())
        b = tk.Label(m2, text="EXPORT", bg=BAR2, fg=DIM, font=F_BOLD, cursor="hand2")
        b.bind("<Button-1>", lambda e: self.do_export())
        b.bind("<Enter>", lambda e, b=b: b.configure(fg=ACC))
        b.bind("<Leave>", lambda e, b=b: b.configure(fg=DIM))
        b.pack(side="left", padx=8)
        for txt, cmd in (("PARAMS", self.open_params), ("CURVES", self.toggle_curves)):
            b = tk.Label(m2, text=txt, bg=BAR2, fg=DIM, font=F_BOLD, cursor="hand2")
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, b=b: b.configure(fg=ACC))
            b.bind("<Leave>", lambda e, b=b: b.configure(fg=DIM))
            b.pack(side="left", padx=8)
        for t, txt in (("select", "SELECT"), ("draw", "DRAW"), ("erase", "ERASE")):
            b = tk.Label(m2, text=txt, bg=FG, fg="#111111", font=F_BOLD, cursor="hand2", padx=10, pady=6)
            b.bind("<Button-1>", lambda e, t=t: self.set_tool(t))
            b.pack(side="right", padx=6, pady=6)
            setattr(self, "tb_" + t, b)
        left = tk.Frame(self, bg=BG); left.pack(fill="both", expand=True, padx=8, pady=4)
        self.rv = tk.Canvas(left, height=26, bg="#2e2e2e", highlightthickness=0)
        self.rv.pack(fill="x")
        self.rv.bind("<Button-1>", self.rv_down)
        self.rv.bind("<B1-Motion>", self.rv_down)
        self.hsb = Rail(left, "horizontal", command=self._xview_m)
        self.hsb.pack(side="bottom", fill="x")
        self.sv = tk.Canvas(left, height=66, bg=PANEL, highlightthickness=0)
        self.sv.pack(side="bottom", fill="x")
        self.sv.bind("<Button-1>", self.sv_down)
        self.sv.bind("<B1-Motion>", self.sv_move)
        self.sv.bind("<ButtonRelease-1>", lambda e: (setattr(self, "drag_s", None), self.end_gesture()))
        self.cb_frame = tk.Frame(left, bg=BG)
        self.cb_tabs = tk.Frame(self.cb_frame, bg=BG)
        self.cb_tabs.pack(fill="x")
        self._tabw = {}
        for k, name in CURVE_PARAMS:
            b = tk.Label(self.cb_tabs, text=name, bg=CHIP, fg=DIM, font=F_SMALL, cursor="hand2", padx=6, pady=2)
            b.bind("<Button-1>", lambda e, k=k, name=name: self.select_curve(k, name))
            b.pack(side="left", padx=1)
            self._tabw[k] = b
        self.l_curve = tk.Label(self.cb_tabs, text="NOTE", bg=LABBG, fg=LABFG, font=F_SMALL, padx=6)
        self.l_curve.pack(side="left", padx=6)
        self.ccv = tk.Canvas(self.cb_frame, height=CCH, bg=PANEL, highlightthickness=0, xscrollcommand=self._xscroll)
        self.ccv.bind("<Button-1>", self.ccv_down)
        self.ccv.bind("<B1-Motion>", self.ccv_move)
        self.ccv.bind("<ButtonRelease-1>", lambda e: self.end_drag())
        mid = tk.Frame(left, bg=BG); mid.pack(fill="both", expand=True)
        self.vsb = Rail(mid, "vertical", command=self._yview_m)
        self.vsb.pack(side="right", fill="y")
        self.cv = tk.Canvas(mid, bg=ROLL, highlightthickness=0, xscrollcommand=self._xscroll, yscrollcommand=self._yscroll)
        self.cv.pack(side="left", fill="both", expand=True)
        self.kv = tk.Canvas(mid, width=KEY_W, bg=KEYW, highlightthickness=0)
        self.kv.place(x=0, y=0, relheight=1.0, width=KEY_W)
        self.cv.bind("<Button-1>", self.cv_down)
        self.cv.bind("<B1-Motion>", self.cv_move)
        self.cv.bind("<ButtonRelease-1>", lambda e: self.end_drag())
        self.cv.bind("<Double-Button-1>", self.cv_dbl)
        self.cv.bind("<Button-2>", self.cv_right)
        self.cv.bind("<Button-3>", self.cv_right)
        self.bind("<space>", self._on_space)
        for pat in ("<Control-z>", "<Command-z>"):
            self.bind(pat, lambda e: self.undo())
        for pat in ("<Control-Shift-z>", "<Command-Shift-z>", "<Control-y>"):
            self.bind(pat, lambda e: self.redo())
        for pat in ("<Control-s>", "<Command-s>"):
            self.bind(pat, lambda e: self.save_seq())
        for seq in ("<MouseWheel>", "<Shift-MouseWheel>", "<Button-4>", "<Button-5>", "<Button-6>", "<Button-7>"):
            self.bind_all(seq, self._wheel)
        for w in (self.e_bpm, self.e_sig):
            w.bind("<Return>", lambda e: self.draw_all())
        self.set_pane = tk.Frame(self, bg="#242424", highlightthickness=1, highlightbackground=LINE)
        self._build_settings()
        self.select_curve("note", "NOTE")
        self.refresh_voices()
        self.draw_all()

    def _load_settings(self):
        try:
            with open(self.SETTINGS_PATH, encoding="utf-8") as f: return json.load(f)
        except Exception: return {}

    def _save_settings(self):
        data = dict(exc_template=self.set_exc.get(), use_spp=bool(self.set_spp.get()),
                    defaults={k: float(self.pv[k].get()) for k in self.SET_KEYS})
        try:
            with open(self.SETTINGS_PATH, "w", encoding="utf-8") as f: json.dump(data, f, indent=1)
        except Exception: pass

    def toggle_settings(self):
        if self.set_pane.winfo_manager():
            self.set_pane.pack_forget()
        else:
            for e, get in self._set_entries: e.delete(0, "end"); e.insert(0, f"{get():g}")
            self.set_pane.pack(fill="x", before=self.m2)

    def _set_exc(self, v):
        self.set_exc.set(v)
        for val in ("delta", "glottal"):
            getattr(self, "_exc_" + val).configure(bg="#dcdcdc" if val == v else CHIP, fg="#111111" if val == v else FG)
        self._save_settings(); self.dirty = True; self.update_light()

    def _set_spp(self, on):
        self.set_spp.set(on)
        self._spp_b.configure(bg="#dcdcdc" if on else CHIP, fg="#111111" if on else FG)
        self._epr_b.configure(bg="#dcdcdc" if not on else CHIP, fg="#111111" if not on else FG)
        self._save_settings(); self.dirty = True; self.update_light()

    def _build_settings(self):
        p = self.set_pane; self._set_entries = []
        def head(t, pady=(8, 0)):
            tk.Label(p, text=t, bg="#242424", fg=FG, font=F_BOLD).pack(anchor="w", padx=10, pady=pady)
        head("SETTINGS", pady=(8, 4))
        head("excitation template")
        r = tk.Frame(p, bg="#242424"); r.pack(fill="x", padx=10, pady=4)
        for val in ("delta", "glottal"):
            b = tk.Label(r, text=val, bg=CHIP, fg=FG, font=F_BOLD, cursor="hand2", padx=14, pady=3)
            b.bind("<Button-1>", lambda e, v=val: self._set_exc(v))
            b.pack(side="left", expand=True, fill="x", padx=1)
            setattr(self, "_exc_" + val, b)
        head("spectral peak modeling behaviour")
        r = tk.Frame(p, bg="#242424"); r.pack(fill="x", padx=10, pady=4)
        self._spp_b = tk.Label(r, text="use spp", bg=CHIP, fg=FG, font=F_BOLD, cursor="hand2", padx=14, pady=3)
        self._spp_b.bind("<Button-1>", lambda e: self._set_spp(True))
        self._spp_b.pack(side="left", expand=True, fill="x", padx=1)
        self._epr_b = tk.Label(r, text="use epr comb", bg=CHIP, fg=FG, font=F_BOLD, cursor="hand2", padx=14, pady=3)
        self._epr_b.bind("<Button-1>", lambda e: self._set_spp(False))
        self._epr_b.pack(side="left", expand=True, fill="x", padx=1)
        head("default parameters")
        defs = [
            ("gender shift", lambda: self.pv["gsh"].get() / 100., lambda v: self.pv["gsh"].set(min(max(v * 100., 0.), 100.))),
            ("gender", lambda: 2 ** ((self.pv["gen"].get() - 50) / 100.), lambda v: self.pv["gen"].set(min(max(50 + 100 * np.log2(max(v, 1e-3)), 0.), 100.))),
            ("pitch", lambda: (self.pv["pit"].get() - 50) * 2., lambda v: self.pv["pit"].set(min(max(50 + v / 2., 0.), 100.))),
            ("voicing", lambda: self.pv["voi"].get() / 100., lambda v: self.pv["voi"].set(min(max(v * 100., 0.), 100.))),
            ("breathiness", lambda: self.pv["bre"].get() / 50., lambda v: self.pv["bre"].set(min(max(v * 50., 0.), 100.))),
            ("brightness", lambda: (self.pv["bri"].get() - 50) / 50 * 18., lambda v: self.pv["bri"].set(min(max(50 + v * 50. / 18., 0.), 100.))),
            ("tension", lambda: (self.pv["ten"].get() - 50) / 50 * 18., lambda v: self.pv["ten"].set(min(max(50 + v * 50. / 18., 0.), 100.))),
        ]
        for name, get, set_ in defs:
            r = tk.Frame(p, bg="#242424"); r.pack(fill="x", padx=10, pady=1)
            tk.Label(r, text=name, bg="#242424", fg=FG, font=F_BOLD, anchor="w").pack(side="left")
            tk.Label(r, text="|", bg="#242424", fg=DIM, font=F_BOLD).pack(side="left", padx=6)
            e = tk.Entry(r, width=8, bg="#1b1b1b", fg=FG, bd=0, insertbackground=FG, font=F_BOLD, justify="right")
            e.pack(side="left"); e.insert(0, f"{get():g}"); self._set_entries.append((e, get))
            def commit(ev=None, e=e, get=get, set_=set_):
                try: v = float(e.get())
                except ValueError: v = None
                if v is not None:
                    self.begin_gesture(); set_(v); self.end_gesture()
                    self._save_settings(); self.draw_all()
                e.delete(0, "end"); e.insert(0, f"{get():g}")
            e.bind("<Return>", commit); e.bind("<FocusOut>", commit)
        tk.Label(p, text="", bg="#242424").pack(pady=4)
        self._set_exc(self.set_exc.get()); self._set_spp(bool(self.set_spp.get()))

    def set_tool(self, t):
        self.tool.set(t)
        for k in ("select", "draw", "erase"):
            getattr(self, "tb_" + k).configure(bg=ACC if k == t else FG)
        self.draw_all()

    def _eff_tool(self):
        t = self.tool.get()
        if t in ("draw", "erase") and self.curve_open and self.curve_param != "note":
            return "pencil" if t == "draw" else "cerase"
        return t

    def toggle_curves(self):
        self.curve_open = not self.curve_open
        if self.curve_open: self.cb_frame.pack(fill="x", before=self.sv); self._sync_lane()
        else: self.cb_frame.pack_forget()
        self.draw_all()

    def _sync_lane(self):
        if self.curve_param == "note" or not self.curve_open: self.ccv.pack_forget()
        else: self.ccv.pack(fill="x")

    def select_curve(self, k, name):
        self.curve_param = k
        for kk, b in self._tabw.items():
            b.configure(bg="#dcdcdc" if kk == k else CHIP, fg="#111111" if kk == k else DIM)
        self.l_curve.configure(text=name); self._sync_lane(); self.draw_all()

    def open_params(self):
        if self._params_win is not None:
            try: self._params_win.lift(); return
            except Exception: self._params_win = None
        w = tk.Toplevel(self); w.title("PARAMETERS"); w.configure(bg=BAR2); self._params_win = w
        for idx, (key, name, dflt, mx) in enumerate(self.PARAMS):
            f = tk.Frame(w, bg=BAR2); f.grid(row=idx // 5, column=idx % 5, padx=12, pady=8)
            s = VSlider(f, self.pv[key], 0, mx, length=110, command=lambda k=key: self.param_changed(k))
            s.pack(); s.bind("<Button-1>", lambda e: self.begin_gesture(), add="+")
            s.bind("<ButtonRelease-1>", lambda e: self.end_gesture(), add="+")
            s.bind("<Double-Button-1>", lambda e, k=key, d=dflt: self.reset_param(k, d))
            tk.Label(f, text=name, bg=BAR2, fg=DIM, font=F_SMALL).pack(pady=2)

    def refresh_voices(self):
        self._voice_map = {}
        for root in (os.path.join(os.getcwd(), "voices"), os.getcwd()):
            if not os.path.isdir(root): continue
            for d in sorted(os.listdir(root)):
                p = os.path.join(root, d)
                if os.path.isfile(os.path.join(p, "manifest.ini")) and d not in self._voice_map:
                    self._voice_map[d] = p

    def voice_menu(self):
        m = tk.Menu(self, tearoff=0, bg=BAR2, fg=FG, activebackground=ACC, activeforeground="#111111")
        for name in self._voice_map:
            m.add_command(label=name, command=lambda n=name: self._set_db(self._voice_map[n]))
        m.add_separator(); m.add_command(label="<open...>", command=self._open_voice)
        try: m.tk_popup(*self.winfo_pointerxy())
        finally: m.grab_release()

    def _open_voice(self):
        p = filedialog.askdirectory()
        if p: self._set_db(p)

    def _set_db(self, path):
        try: self.db = synth.DB(path)
        except Exception as e: messagebox.showerror("DB", str(e)); return
        cp = manifest.load_manifest(path)
        self._lang_code = cp["singer"]["language"]
        self.b_voice.configure(text=f"{os.path.basename(path)} - {cp['singer']['version']} - {cp['singer']['language']}")
        self.dirty = True; self.draw_all()

    def _xscroll(self, *a):
        self.hsb.set(*a)
        for c in (self.sv, self.rv, self.ccv): c.xview_moveto(a[0])
    def _yscroll(self, *a):
        self.vsb.set(*a); self.kv.yview_moveto(a[0])
    def _xview_m(self, v):
        for c in (self.cv, self.sv, self.rv, self.ccv): c.xview_moveto(v)
    def _yview_m(self, v):
        self.cv.yview_moveto(v); self.kv.yview_moveto(v)

    def beat_ms(self):
        try: return 60000. / max(1., float(self.e_bpm.get()))
        except ValueError: return 500.
    def sig(self):
        try:
            n, d = (int(x) for x in self.e_sig.get().split("/"))
            return max(1, n), max(1, d)
        except ValueError: return 4, 4
    def bar_ms(self):
        n, d = self.sig(); return self.beat_ms() * 4 * n / d
    def snap(self, v):
        s = self.beat_ms() / 4.; return round(v / s) * s
    def y_of(self, m): return (MIDI_TOP - m) * ROW_H
    def midi_at(self, y): return MIDI_TOP - int(y // ROW_H)
    def x_of(self, ms): return KEY_W + ms * SCALE
    def ms_at(self, x): return max(0., (x - KEY_W) / SCALE)

    def _state(self):
        return dict(
            notes=[dict(start=n.start, dur=n.dur, midi=n.midi, phonemes=list(n.phonemes),
                        onsets=list(n.onsets), chain=n.chain, vow=n.vow, rel=n.rel,
                        ov={k: list(v) for k, v in n.ov.items()}, pre=n.pre,
                        pt_ol=n.pt_ol, pt_or=n.pt_or, pt_dl=n.pt_dl, pt_dr=n.pt_dr,
                        pt_depl=n.pt_depl, pt_depr=n.pt_depr, lyric=n.lyric, locked=n.locked)
                   for n in sorted(self.notes, key=lambda n: n.start)],
            params={k: float(v.get()) for k, v in self.pv.items()},
            curves={k: [list(map(list, s)) for s in self.curves.get(k, [])] for k, _n in CURVE_PARAMS if k != "note"},
            vibratos=[dict(v) for v in self.vibratos])

    def begin_gesture(self):
        if self._pre is not None: self.end_gesture()
        self._pre = self._state()

    def end_gesture(self):
        pre, self._pre = self._pre, None
        if pre is None: return
        if pre != self._state():
            self._undo.append(pre)
            if len(self._undo) > 50: self._undo.pop(0)
            self._redo.clear()

    def _restore(self, st):
        self._restoring = True
        for k, v in (st.get("params") or {}).items():
            if k in self.pv: self.pv[k].set(v)
        self._restoring = False
        cd = st.get("curves")
        if cd is None: cd = {"pit": st.get("pitch", [])}
        for k, _n in CURVE_PARAMS:
            if k == "note": continue
            self.curves[k] = [list(map(list, s)) for s in cd.get(k, [])]
        self.vibratos = [dict(v) for v in st.get("vibratos", [])]
        notes = []
        for nd in st["notes"]:
            n = Note(nd["start"], nd["dur"], nd["midi"], list(nd["phonemes"]), list(nd["onsets"]))
            n.chain = nd.get("chain"); n.vow = nd.get("vow"); n.rel = nd.get("rel")
            n.ov = {k: list(v) for k, v in (nd.get("ov") or {}).items()}
            n.pre = nd.get("pre")
            n.pt_ol = nd.get("pt_ol", 0.); n.pt_or = nd.get("pt_or", 0.)
            n.pt_dl = nd.get("pt_dl", 120.); n.pt_dr = nd.get("pt_dr", 120.)
            n.pt_depl = nd.get("pt_depl", 0.); n.pt_depr = nd.get("pt_depr", 0.)
            n.lyric = nd.get("lyric"); n.locked = bool(nd.get("locked"))
            notes.append(n)
        self.stop_ph_edit(apply=False); self.notes = notes; self.sel = None
        self.dirty = True; self.draw_all()

    def undo(self):
        if not self._undo: return
        self._redo.append(self._state()); self._restore(self._undo.pop())

    def redo(self):
        if not self._redo: return
        self._undo.append(self._state()); self._restore(self._redo.pop())

    def new_seq(self):
        self.begin_gesture(); self.stop_ph_edit(apply=False)
        self.notes = []; self.sel = None; self.y = None; self._seq_path = None
        self.end_gesture(); self.draw_all()

    def reset_param(self, k, d):
        self.begin_gesture(); self.pv[k].set(d); self.end_gesture()

    def curve_y(self, k, v): return (MIDI_TOP - v + 0.5) * ROW_H
    def curve_val(self, k, y): return MIDI_TOP + 0.5 - y / ROW_H
    def lane_y(self, k, v):
        lo, hi = self.CURVE_RANGE.get(k, (0., 2.))
        return CCH * (1. - (max(lo, min(hi, v)) - lo) / (hi - lo))
    def lane_val(self, k, y):
        lo, hi = self.CURVE_RANGE.get(k, (0., 2.))
        return lo + (1. - y / CCH) * (hi - lo)

    def natural_curve(self):
        if not self.db: return []
        hz_of = lambda m: synth.midi_to_hz(m) * 2 ** (self.pitch() / 1200.)
        mfac = max(0., min(1., self.mod()))
        trs = getattr(self, "_pt_trans", None) or []
        segs = []; cur = []
        def push(ms, f0hz):
            nonlocal cur
            if f0hz > 20: cur.append((ms, 69 + 12 * np.log2(f0hz / 440.)))
            else:
                if len(cur) > 1: segs.append(cur)
                cur = []
        for r in (self._rows or []):
            pair, midi = r["pair"], r["midi"]
            dur = max(1., r["e"] - r["s"])
            hz = hz_of(midi); lh = np.log(max(hz, 30.))
            pm = r.get("pmidi")
            lh0 = np.log(max(hz_of(pm), 30.)) if pm is not None else lh
            sp = r.get("split", 0.)
            rin = min(150., 0.4 * dur) * (1. - mfac)
            rout = min(120., 0.3 * dur) * (1. - mfac)
            raw = []
            if " " in pair:
                try:
                    arr, meta, g = self.db.unit(pair, midi)
                    tr = hz / max(meta["rec_pitch"], 30.)
                    t = arr["t"]; f0 = arr["f0"] * tr
                    nn = len(t); step = max(1, nn // 48)
                    for i in range(0, nn, step):
                        raw.append((r["s"] + (t[i] / max(t[-1], 1e-6)) * dur, f0[i]))
                except Exception: raw = []
            else:
                try:
                    st, st_rec, i0, i1 = self.db.steady(pair, midi)
                    tr = hz / max(st_rec, 30.)
                    loop = st["f0"][i0:i1] * tr
                    step = max(1, len(loop) // 8)
                    for j in range(0, len(loop), step):
                        raw.append((r["s"] + (j / max(len(loop), 1)) * dur, loop[j]))
                except Exception: raw = []
            for ms, f0hz in raw:
                if mfac > 0. and f0hz > 20:
                    t = ms - r["s"]
                    tgt = lh0 if t < sp else lh
                    w = 1. if mfac >= 1. else max(0., min(1., min(t / max(rin, 1e-3), (dur - t) / max(rout, 1e-3)))) * mfac
                    if w > 0.:
                        lf = np.log(max(f0hz, 30.))
                        f0hz = float(np.exp(lf + (tgt - lf) * w))
                for t0, t1, p0, p1, dep in trs:
                    if t0 <= ms <= t1:
                        u = (ms - t0) / max(1e-3, t1 - t0)
                        s_ = u * u * (3 - 2 * u)
                        f0hz = hz_of(p0 + (p1 - p0) * (s_ + 2. * dep * s_ * (1. - s_)))
                        break
                push(ms, f0hz)
        if len(cur) > 1: segs.append(cur)
        return segs

    def effective_pitch(self):
        segs = []; strokes = self.curves["pit"]
        def sv(ms):
            for s in strokes:
                xs = [p[0] for p in s]
                if xs and xs[0] <= ms <= xs[-1]: return float(np.interp(ms, xs, [p[1] for p in s]))
            return None
        for seg in self.natural_curve():
            ms0, ms1 = seg[0][0], seg[-1][0]
            n = max(2, int((ms1 - ms0) / 20.))
            ts = [ms0 + (ms1 - ms0) * i / n for i in range(n + 1)]
            for s in strokes:
                for p in s:
                    if ms0 <= p[0] <= ms1: ts.append(p[0])
            ts.sort()
            xs_n = [p[0] for p in seg]; ys_n = [p[1] for p in seg]
            pts = []
            for t in ts:
                v = sv(t)
                if v is None: v = float(np.interp(t, xs_n, ys_n))
                pts.append((t, v))
            segs.append(pts)
        return segs

    def natural_forms(self, idx):
        if not self.db: return []
        segs = []
        for r in (self._rows or []):
            pair, midi = r["pair"], r["midi"]
            dur = max(1., r["e"] - r["s"])
            try:
                if " " in pair: arr, _meta, _g = self.db.unit(pair, midi)
                else:
                    arr, _rp, _i0, _i1 = self.db.steady(pair, midi)
                    if arr is None: continue
                t = arr["t"]; n = len(t); step = max(1, n // 48)
                pts = []
                for i in range(0, n, step):
                    vt = arr["vt"][i]
                    if idx < len(vt) and float(vt[idx][0]) > 0:
                        pts.append((r["s"] + (t[i] / max(t[-1], 1e-6)) * dur, float(vt[idx][0])))
                if len(pts) > 1: segs.append(pts)
            except Exception: continue
        return segs

    def base_pitch_at(self, ms, fallback):
        for seg in (self.curves["pit"] or []):
            xs = [p[0] for p in seg]
            if xs and xs[0] <= ms <= xs[-1]: return float(np.interp(ms, xs, [p[1] for p in seg]))
        for seg in self.natural_curve():
            if seg and seg[0][0] <= ms <= seg[-1][0]:
                return float(np.interp(ms, [p[0] for p in seg], [p[1] for p in seg]))
        return fallback

    def _trim_curve(self, key, stroke):
        a, b = stroke[0][0], stroke[-1][0]
        kept = []
        for seg in self.curves[key]:
            if seg[-1][0] <= a or seg[0][0] >= b: kept.append(seg); continue
            xs = [p[0] for p in seg]; ys = [p[1] for p in seg]
            left = [list(p) for p in seg if p[0] < a]
            if xs[0] < a < xs[-1]: left.append([a, float(np.interp(a, xs, ys))])
            right = []
            if xs[0] < b < xs[-1]: right.append([b, float(np.interp(b, xs, ys))])
            right += [list(p) for p in seg if p[0] > b]
            if len(left) > 1: kept.append(left)
            if len(right) > 1: kept.append(right)
        kept.append(stroke)
        self.curves[key] = sorted(kept, key=lambda s: s[0][0])

    def _erase_at(self, key, x, y, yfun, rad=8.):
        segs = self.curves.get(key)
        if not segs: return False
        out = []; changed = False
        for seg in segs:
            run = []
            for p in seg:
                if abs(self.x_of(p[0]) - x) <= rad and abs(yfun(p[1]) - y) <= rad:
                    if len(run) > 1: out.append(run)
                    run = []; changed = True
                else: run.append(list(p))
            if len(run) > 1: out.append(run)
            elif run: changed = True
        if changed: self.curves[key] = out
        return changed

    def _scrub(self, d, x, y, yfun):
        x0, y0 = d["ex"], d["ey"]
        steps = max(1, int(max(abs(x - x0), abs(y - y0)) / 4))
        ch = False
        for i in range(steps + 1):
            xi = x0 + (x - x0) * i / steps; yi = y0 + (y - y0) * i / steps
            ch |= self._erase_at(d["key"], xi, yi, yfun)
        d["ex"], d["ey"] = x, y
        if ch: self.dirty = True; self.update_light(); self.draw_all()

    def vib_at(self, x, y):
        if self.curve_param != "pit": return None, None
        for v in reversed(self.vibratos):
            x0, x1 = self.x_of(v["s"]), self.x_of(v["e"])
            yc = self.curve_y("pit", v["c"])
            half = max(4., v["amp"] / 100. * ROW_H)
            top, bot = yc - half, yc + half
            w = max(1., x1 - x0)
            xe = x0 + v["fin"] * w; xf = x1 - v["fout"] * w
            if abs(x - xe) < 7 and abs(y - (top - 8)) < 7: return v, "ease-in"
            if abs(x - xf) < 7 and abs(y - (top - 8)) < 7: return v, "ease-out"
            if abs(x - (x0 + x1) / 2) < 7 and abs(y - (bot + 8)) < 7: return v, "freq"
            if top - 4 <= y <= top + 4 and x0 <= x <= x1: return v, "amp"
            if bot - 4 <= y <= bot + 4 and x0 <= x <= x1: return v, "amp"
            if abs(x - x0) < 5 and top <= y <= bot: return v, "dur-l"
            if abs(x - x1) < 5 and top <= y <= bot: return v, "dur-r"
            if x0 <= x <= x1 and top - 12 <= y <= bot + 12: return v, "move"
        return None, None

    def cv_right(self, ev):
        if not self.curve_open or self.curve_param == "note": self.cv_menu(ev); return
        if self.curve_param != "pit": return
        x, y = self.cv.canvasx(ev.x), self.cv.canvasy(ev.y)
        v, _p = self.vib_at(x, y)
        if v is not None:
            self.begin_gesture(); self.vibratos.remove(v)
            self.dirty = True; self.update_light(); self.end_gesture(); self.draw_all(); return
        ms = self.ms_at(x)
        n = next((n for n in self.notes if n.start <= ms <= n.start + n.dur), None)
        if n is None: return
        self.begin_gesture()
        self.vibratos.append(dict(s=n.start + 0.15 * n.dur, e=n.start + 0.85 * n.dur,
                                  c=self.base_pitch_at(n.start + n.dur / 2, float(n.midi)),
                                  amp=50., freq=6., fin=0.25, fout=0.25))
        self.dirty = True; self.update_light(); self.end_gesture(); self.draw_all()

    def _pt_set(self, n, attr, v):
        setattr(n, attr, float(v) / 100. if attr in ("pt_depl", "pt_depr") else float(v))
        self.dirty = True; self.update_light(); self.draw_all()

    def _set_phonemes(self, n, toks):
        n.phonemes = toks
        n.onsets = [0.] + [n.dur * (j + 1) / len(toks) for j in range(len(toks) - 1)]
        n.chain = n.vow = n.rel = None; n.ov = {}; n.pre = None
        self.dirty = True

    def _g2p_pack(self):
        if getattr(self, "_g2p_reg", None) is None:
            from .g2p import G2pRegistry
            d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "g2p")
            self._g2p_reg = G2pRegistry([d])
        return self._g2p_reg.for_lang(getattr(self, "_lang_code", "ja"))

    def cv_menu(self, ev):
        x, y = self.cv.canvasx(ev.x), self.cv.canvasy(ev.y)
        n = self.note_at(x, y)
        if n is None: return
        self.begin_gesture()
        w = tk.Toplevel(self); w.title("note"); w.configure(bg=BG); w.transient(self)
        w.geometry(f"+{ev.x_root + 8}+{ev.y_root - 60}")
        def lab(t): tk.Label(w, text=t, bg=BG, fg=FG, font=F_BOLD, anchor="w").pack(fill="x", padx=6)
        def chip(parent, t): tk.Label(parent, text=t, bg=CHIP, fg="#666666", font=F_BOLD, padx=8, pady=3).pack(side="left", padx=3)
        def box(parent, width=16): tk.Label(parent, text="", bg="#242424", fg=DIM, font=F_BOLD, anchor="w", padx=6, pady=4, width=width).pack(side="left", fill="x", expand=True)
        def fader(parent, attr, lo, hi, init):
            vv = tk.DoubleVar(value=init)
            hs = HSlider(parent, vv, lo, hi, command=lambda: self._pt_set(n, attr, vv.get()))
            hs.pack(fill="x", expand=True)
            hs.bind("<Button-1>", lambda e: self.begin_gesture(), add="+")
            hs.bind("<ButtonRelease-1>", lambda e: (self._pt_set(n, attr, vv.get()), self.end_gesture()), add="+")
        lab("phonemes")
        pr = tk.Frame(w, bg=BG); pr.pack(fill="x", padx=6)
        e_ph = tk.Entry(pr, width=14, bg=BG, fg=FG, bd=0, insertbackground=FG, font=F_BOLD)
        e_ph.insert(0, " ".join(n.phonemes)); e_ph.pack(side="left")
        b_lock = tk.Label(pr, text="lock", font=F_BOLD, padx=8, pady=3, cursor="hand2")
        b_lock.pack(side="left", padx=4)
        def paint_lock(): b_lock.configure(bg=ACC if n.locked else CHIP, fg="#111111" if n.locked else "#666666")
        paint_lock()
        b_lock.bind("<Button-1>", lambda e: (setattr(n, "locked", not n.locked), paint_lock()))
        lab("lyrics")
        lr = tk.Frame(w, bg=BG); lr.pack(fill="x", padx=6)
        e_ly = tk.Entry(lr, width=16, bg="#242424", fg=FG, bd=0, insertbackground=FG, font=F_BOLD)
        e_ly.insert(0, n.lyric or ""); e_ly.pack(side="left")
        tk.Label(lr, text=f"lang: {getattr(self, '_lang_code', 'ja')}", bg=BG, fg=DIM, font=F_SMALL).pack(side="left", padx=6)
        lab("vocal style")
        bs = tk.Frame(w, bg=BG); bs.pack(fill="x", padx=6); box(bs)
        lab("pitch transition offset")
        fo = tk.Frame(w, bg=BG); fo.pack(fill="x", padx=6)
        for side, attr, init in (("left", "pt_ol", n.pt_ol), ("right", "pt_or", n.pt_or)):
            f = tk.Frame(fo, bg=BG); f.pack(side="left", expand=True, fill="x")
            fader(f, attr, -300, 300, init)
            tk.Label(f, text=side, bg=BG, fg=DIM, font=F_SMALL).pack()
        lab("transition duration")
        fd = tk.Frame(w, bg=BG); fd.pack(fill="x", padx=6)
        for side, attr, init in (("left", "pt_dl", n.pt_dl), ("right", "pt_dr", n.pt_dr)):
            f = tk.Frame(fd, bg=BG); f.pack(side="left", expand=True, fill="x")
            fader(f, attr, 20, 400, init)
            tk.Label(f, text=side, bg=BG, fg=DIM, font=F_SMALL).pack()
        lab("transition depth")
        fp = tk.Frame(w, bg=BG); fp.pack(fill="x", padx=6)
        for side, attr, init in (("left", "pt_depl", n.pt_depl), ("right", "pt_depr", n.pt_depr)):
            f = tk.Frame(fp, bg=BG); f.pack(side="left", expand=True, fill="x")
            fader(f, attr, -100, 100, init * 100)
            tk.Label(f, text=side, bg=BG, fg=DIM, font=F_SMALL).pack()
        lab("note presets")
        bp = tk.Frame(w, bg=BG); bp.pack(fill="x", padx=6)
        for t in ("attack", "body", "release"): chip(bp, t)
        tk.Label(w, text="save note part as preset", bg=CHIP, fg="#666666", font=F_BOLD, padx=8, pady=4).pack(fill="x", padx=6, pady=4)
        def commit_ph(e=None):
            try: toks = e_ph.get().split()
            except Exception: return
            if toks and (not self.db or not [t for t in toks if t not in self.db.lang.phonemes()]):
                if toks != list(n.phonemes):
                    self._set_phonemes(n, toks); n.locked = True; paint_lock()
                    self.update_light(); self.draw_all()
        def commit_ly(e=None):
            try: txt = e_ly.get().strip()
            except Exception: return
            n.lyric = txt
            if n.locked or not txt: return
            pack = self._g2p_pack()
            if pack is None: return
            phs = pack.word(txt)
            if not phs: return
            eng = pack.to_engine(phs) or phs
            if not self.db or not [t for t in eng if t not in self.db.lang.phonemes()]:
                self._set_phonemes(n, eng); self.update_light(); self.draw_all()
        e_ph.bind("<Return>", commit_ph); e_ly.bind("<Return>", commit_ly)
        w.protocol("WM_DELETE_WINDOW", lambda: (commit_ly(), commit_ph(), w.destroy()))
        def on_destroy(e):
            if e.widget is w:
                try: self.end_gesture()
                except Exception: pass
        w.bind("<Destroy>", on_destroy)
        try: w.grab_set()
        except Exception: pass

    def draw_all(self):
        for c in (self.cv, self.kv, self.sv, self.rv, self.ccv): c.delete("all")
        H = (MIDI_TOP - MIDI_BOT + 1) * ROW_H; W = self.x_of(60000.)
        self.rv.create_text(KEY_W + 6, 13, text="MEASURES", anchor="w", fill=DIM, font=F_BOLD)
        bar = self.bar_ms(); b = 0.; mn = 1
        while b < 60000:
            x = self.x_of(b); self.rv.create_line(x, 0, x, 26, fill=LINE)
            self.rv.create_text(x - 5, 13, text=str(mn), anchor="e", fill=DIM, font=F_BOLD)
            b += bar; mn += 1
        for m in range(MIDI_TOP, MIDI_BOT - 1, -1):
            y = self.y_of(m)
            if is_black(m): self.cv.create_rectangle(KEY_W, y, W, y + ROW_H, fill=ROLL_DK, outline="")
            self.kv.create_rectangle(0, y, KEY_W, y + ROW_H, fill=KEYB if is_black(m) else KEYW, outline="#8a8a8a")
            if m % 12 == 0: self.kv.create_text(KEY_W - 4, y + ROW_H / 2, text=f"C{m // 12 - 1}", anchor="e", fill="#333333", font=F_SMALL)
        q = self.beat_ms(); b = 0.
        while b < 60000:
            is_bar = bar and abs(b / bar - round(b / bar)) < 1e-6
            self.cv.create_line(self.x_of(b), 0, self.x_of(b), H, fill=LINE if is_bar else GRID)
            b += q
        if self.db:
            self._sn = sorted(self.notes, key=lambda n: n.start)
            try: self._rows, self._layout = plan(self.db, self._sn, self.beat_ms())
            except Exception as e: import traceback; traceback.print_exc(); self._rows, self._layout = None, None
        else: self._sn, self._rows, self._layout = None, None, None
        sn2 = self._sn or sorted(self.notes, key=lambda n: n.start)
        self._pt_trans = []
        for a, b2 in zip(sn2, sn2[1:]):
            c = b2.start + b2.pt_ol; d = max(20., b2.pt_dl)
            self._pt_trans.append((c - d / 2., c + d / 2., float(a.midi), float(b2.midi), b2.pt_depl))
            c = a.end + a.pt_or; d = max(20., a.pt_dr)
            self._pt_trans.append((c - d / 2., c + d / 2., float(a.midi), float(b2.midi), a.pt_depr))
        for n in sorted(self.notes, key=lambda n: n.start): self.draw_note_rect(n)
        self.draw_curves()
        for n in sorted(self.notes, key=lambda n: n.start): self.draw_note_text(n)
        self.draw_strip(); self.draw_curve_lane()
        tot = max([n.start + n.dur for n in self.notes], default=0.) / 1000.
        mm, ss, cc = int(tot // 60), int(tot % 60), int(tot * 100 % 100)
        self.l_time.configure(text=f"{mm:02d}:{ss:02d}:{cc:02d}")
        self.cv.configure(scrollregion=(0, 0, W, H))
        self.kv.configure(scrollregion=(0, 0, KEY_W, H))
        self.sv.configure(scrollregion=(0, 0, W, 66))
        self.rv.configure(scrollregion=(0, 0, W, 26))
        self.ccv.configure(scrollregion=(0, 0, W, CCH))
        if self._ph_edit is not None and self._ph_win is not None:
            n = self._ph_edit
            wy = (self.y_of(n.midi) - 6 if getattr(self, "_ph_kind", "ly") == "ph" else self.y_of(n.midi) + ROW_H / 2)
            self._ph_win = self.cv.create_window(self.x_of(n.start) + 2, wy, anchor="w", window=self.e_np)
        self.draw_playhead(); self.update_light()

    def draw_note_rect(self, n):
        x0, x1 = self.x_of(n.start), self.x_of(n.start + n.dur)
        y = self.y_of(n.midi); s = n is self.sel
        self.cv.create_rectangle(x0, y + 1, x1, y + ROW_H - 1, fill=ACC_HI if s else ACC, outline="#ffffff" if s else "")

    def draw_note_text(self, n):
        x0 = self.x_of(n.start); y = self.y_of(n.midi)
        # Top line: phonemes (always show, spaced)
        self.cv.create_text(x0 + 4, y - 4, text=" ".join(n.phonemes), anchor="w", fill=ACC, font=F_SMALL)
        # Main label: lyric if available, else phonemes spaced
        label = n.lyric if n.lyric else " ".join(n.phonemes)
        self.cv.create_text(x0 + 4, y + ROW_H / 2, text=label, anchor="w", fill="#111111", font=F_BOLD)

    def _is_vowel(self, ph):
        if ph in ("a", "i", "u", "e", "o"): return True
        try: return self.db is not None and self.db.lang.type(ph) == "vowel"
        except Exception: return False

    def draw_strip(self):
        cv = self.sv; cv.delete("all"); self._edges = []
        cv.create_rectangle(0, 0, KEY_W, 33, fill=LABBG, outline="")
        cv.create_text(KEY_W / 2, 16, text="PHONEMES", fill=LABFG, font=F_SMALL)
        cv.create_rectangle(0, 33, KEY_W, 66, fill=LABBG, outline="")
        cv.create_text(KEY_W / 2, 50, text="ARTICULATIONS", fill=LABFG, font=F_SMALL)
        subs = []
        for r in (self._rows or []):
            if " " in r["pair"]:
                src, tgt = r["pair"].split()
                pm = min(max(r.get("p2", 0.), 0.), r["e"] - r["s"])
                subs.append((src, r["s"], r["s"] + pm)); subs.append((tgt, r["s"] + pm, r["e"]))
            else: subs.append((r["pair"], r["s"], r["e"]))
        merged = []
        for lab, s, e in subs:
            if e - s <= 0: continue
            if merged and merged[-1][0] == lab: merged[-1][2] = e
            else: merged.append([lab, s, e])
        for lab, s, e in merged:
            x0, x1 = self.x_of(s), self.x_of(e)
            vow = self._is_vowel(lab)
            cv.create_rectangle(x0, 2, x1, 31, fill=ACC if vow else "#202020", outline="#3a3a3a")
            if x1 - x0 > 14: cv.create_text((x0 + x1) / 2, 16, text=lab, fill="#111111" if vow else ACC, font=F_BOLD)
        if self.sel is not None:
            cv.create_rectangle(self.x_of(self.sel.start), 1, self.x_of(self.sel.start + self.sel.dur), 32, outline=ACC, width=2)
        for r in (self._rows or []):
            x0, x1 = self.x_of(r["s"]), self.x_of(r["e"])
            if " " not in r["pair"]:
                cv.create_rectangle(x0, 36, x1, 63, fill="#262626", outline="#3a3a3a")
                if x1 - x0 > 30: cv.create_text((x0 + x1) / 2, 49, text=f"{r['pair']} {r['e'] - r['s']:.0f}", fill="#e0e0e0", font=F_SMALL)
            else:
                src, tgt = r["pair"].split()
                pm = min(max(r.get("p2", 0.), 0.), r["e"] - r["s"])
                xm = self.x_of(r["s"] + pm)
                cv.create_rectangle(x0, 36, xm, 63, fill="#262626", outline=ACC)
                cv.create_rectangle(xm, 36, x1, 63, fill="#262626", outline=ACC)
                if xm - x0 > 24: cv.create_text((x0 + xm) / 2, 49, text=src, fill=ACC, font=F_SMALL)
                if x1 - xm > 24: cv.create_text((xm + x1) / 2, 49, text=tgt, fill=ACC, font=F_SMALL)
                cv.create_line(xm, 36, xm, 63, fill=ACC)
                self._edges.append((r["s"] + pm, ("p2", r["ni"], r["rk"], r["s"], r["e"])))
            if r.get("lkey"): self._edges.append((r["s"], r["lkey"]))
            if r.get("lkey") and r["lkey"][0] in ("onset", "chain"): cv.create_line(x0, 38, x0, 60, fill="white")
            if r.get("rk") == "c0" and r.get("ni") == 0: self._edges.append((r["s"], ("pre", 0)))
            if r.get("resizable"): self._edges.append((r["e"], ("end", r["ni"], r["rk"], r["s"], r["e"])))

    def draw_curves(self):
        if not self.show_pitch.get(): return
        if self.curve_param == "pit" and self.curve_open:
            for seg in self.natural_curve():
                xy = []
                for ms, v in seg: xy += [self.x_of(ms), self.curve_y("pit", v)]
                if len(xy) >= 4: self.cv.create_line(*xy, fill="#8f8f8f", width=1)
            segs = list(self.curves["pit"])
            if self._curve_tmp is not None: segs = segs + [self._curve_tmp]
            for seg in segs:
                xy = []
                for ms, v in seg: xy += [self.x_of(ms), self.curve_y("pit", v)]
                if len(xy) >= 4: self.cv.create_line(*xy, fill=ACC, width=2)
            for v in self.vibratos: self.draw_vib(v)
        else:
            for seg in self.effective_pitch():
                xy = []
                for ms, v in seg: xy += [self.x_of(ms), self.curve_y("pit", v)]
                if len(xy) >= 4: self.cv.create_line(*xy, fill="#8f8f8f", width=1)

    def draw_vib(self, v):
        cv = self.cv
        x0, x1 = self.x_of(v["s"]), self.x_of(v["e"])
        yc = self.curve_y("pit", v["c"])
        half = max(4., v["amp"] / 100. * ROW_H)
        top, bot = yc - half, yc + half
        w = max(1., x1 - x0)
        cv.create_rectangle(x0, top, x1, bot, outline="#e0e0e0", dash=(3, 3))
        dur_s = max(1e-3, (v["e"] - v["s"]) / 1000.)
        fin = max(1e-3, v["fin"] * dur_s); fout = max(1e-3, v["fout"] * dur_s)
        xy = []
        for i in range(161):
            t = dur_s * i / 160
            env = max(0., min(1., t / fin, (dur_s - t) / fout))
            dev = v["amp"] / 100. * env * np.sin(2 * np.pi * v["freq"] * t)
            xy += [x0 + w * i / 160, self.curve_y("pit", v["c"] + dev)]
        cv.create_line(*xy, fill=ACC, width=2)
        xe = x0 + v["fin"] * w; xf = x1 - v["fout"] * w
        cv.create_line(x0, top - 8, xe, top - 8, fill="#777777")
        cv.create_line(xf, top - 8, x1, top - 8, fill="#777777")
        cv.create_polygon(xe - 5, top - 12, xe + 5, top - 12, xe, top - 3, fill="#ffffff")
        cv.create_polygon(xf - 5, top - 12, xf + 5, top - 12, xf, top - 3, fill="#ffffff")
        cv.create_line(x0, bot + 8, x1, bot + 8, fill="#777777")
        cv.create_oval((x0 + x1) / 2 - 4, bot + 4, (x0 + x1) / 2 + 4, bot + 12, fill="#ffffff", outline="#111111")

    def draw_curve_lane(self):
        cv = self.ccv; cv.delete("all")
        if self.curve_param == "note" or not self.curve_open: return
        k = self.curve_param; W = self.x_of(60000.)
        cv.create_rectangle(0, 0, W, CCH, outline=LINE)
        if k == "pit":
            for seg in self.natural_curve():
                xy = []
                for ms, v in seg: xy += [self.x_of(ms), self.lane_y(k, v)]
                if len(xy) >= 4: cv.create_line(*xy, fill="#8f8f8f", width=1)
        elif k in ("f1", "f2", "f3"):
            for seg in self.natural_forms(("f1", "f2", "f3").index(k)):
                xy = []
                for ms, v in seg: xy += [self.x_of(ms), self.lane_y(k, v)]
                if len(xy) >= 4: cv.create_line(*xy, fill="#8f8f8f", width=1)
        else:
            y = self.lane_y(k, self.CURVE_NEUTRAL.get(k, 1.0))
            cv.create_line(self.x_of(0), y, W, y, fill="#777777", width=1)
        segs = list(self.curves.get(k, []))
        if self._curve_tmp is not None: segs = segs + [self._curve_tmp]
        for seg in segs:
            xy = []
            for ms, v in seg: xy += [self.x_of(ms), self.lane_y(k, v)]
            if len(xy) >= 4: cv.create_line(*xy, fill=ACC, width=2)

    def draw_playhead(self):
        x = self.x_of(self.play_ms)
        for c, h in ((self.rv, 26), (self.cv, (MIDI_TOP - MIDI_BOT + 1) * ROW_H), (self.sv, 66)):
            c.delete("playhead"); c.create_line(x, 0, x, h, fill="#dcdcdc", tags="playhead")

    def follow_playhead(self):
        cv = self.cv; first, last = cv.xview(); span = last - first
        if span >= 0.999: return
        W = self.x_of(60000.); view = span * W; x = self.x_of(self.play_ms)
        cv.xview_moveto(max(0., min((x - view * 0.3) / W, 1. - span)))

    def note_at(self, x, y):
        for n in reversed(self.notes):
            if (self.x_of(n.start) <= x <= self.x_of(n.start + n.dur)
                    and self.y_of(n.midi) <= y <= self.y_of(n.midi) + ROW_H):
                return n
        return None

    def cv_down(self, ev):
        x, y = self.cv.canvasx(ev.x), self.cv.canvasy(ev.y)
        if not self.playing and abs(x - self.x_of(self.play_ms)) < 6:
            self.drag = dict(kind="playhead"); return
        if self.tool.get() == "select":
            v, part = self.vib_at(x, y)
            if v is not None:
                self.begin_gesture()
                self.drag = dict(kind="vib", v=v, part=part, x0=x, y0=y, s0=v["s"], e0=v["e"], c0=v["c"])
                return
        t = self._eff_tool()
        if t == "pencil":
            if self.curve_param == "pit":
                self.begin_gesture()
                self._curve_tmp = [[self.ms_at(x), self.curve_val("pit", y)]]
                self.drag = dict(kind="pencil")
            return
        hit = self.note_at(x, y)
        if t == "cerase":
            self.begin_gesture()
            self.drag = dict(kind="erase", key="pit", ex=x, ey=y)
            self._scrub(self.drag, x, y, lambda v: self.curve_y("pit", v)); return
        if t == "erase":
            if hit:
                self.begin_gesture()
                if hit is self._ph_edit: self.stop_ph_edit(apply=False)
                self.notes.remove(hit)
                if self.sel is hit: self.sel = None
                self.dirty = True; self.end_gesture(); self.draw_all()
            return
        if t == "draw":
            self.begin_gesture()
            n = Note(self.snap(self.ms_at(x)), self.beat_ms(), self.midi_at(y))
            self.notes.append(n); self.sel = n
            self.dirty = True
            self.drag = dict(kind="new", note=n)
            self.start_ph_edit(n, "ly")
            return
        if hit:
            self.sel = hit
            kind = "resize" if abs(x - self.x_of(hit.start + hit.dur)) < 7 else "move"
            self.drag = dict(kind=kind, note=hit, dx=x - self.x_of(hit.start), dy=y - self.y_of(hit.midi))
            self.begin_gesture()
            self.start_ph_edit(hit, "ly")
        else:
            self.stop_ph_edit(apply=True)
            self.sel = None; self.drag = None
            if not self.playing: self.play_ms = self.ms_at(x)
            self.draw_all()

    def cv_dbl(self, ev):
        x, y = self.cv.canvasx(ev.x), self.cv.canvasy(ev.y)
        n = self.note_at(x, y)
        if n is None:
            for m in reversed(self.notes):
                x0, x1 = self.x_of(m.start), self.x_of(m.start + m.dur)
                yt = self.y_of(m.midi)
                if x0 <= x <= x1 and yt - 12 <= y <= yt: n = m; break
        if n is None: return
        yt = self.y_of(n.midi)
        if yt - 12 <= y <= yt: self.start_ph_edit(n, "ph")
        else: self.start_ph_edit(n, "ly")

    def start_ph_edit(self, n, kind="ly"):
        self.stop_ph_edit(apply=False)
        if self._pre is None: self.begin_gesture()
        self._ph_edit = n; self._ph_kind = kind
        self.e_np = tk.Entry(self.cv, width=12, bg="#111111", fg=FG, insertbackground=FG, highlightthickness=1, highlightcolor=ACC)
        self.e_np.insert(0, " ".join(n.phonemes) if kind == "ph" else (getattr(n, "lyric", None) or ""))
        wy = self.y_of(n.midi) - 6 if kind == "ph" else self.y_of(n.midi) + ROW_H / 2
        self._ph_win = self.cv.create_window(self.x_of(n.start) + 2, wy, anchor="w", window=self.e_np)
        self.e_np.selection_range(0, "end"); self.e_np.focus_set()
        self.e_np.bind("<Return>", lambda e: self.stop_ph_edit(apply=True))
        self.e_np.bind("<Escape>", lambda e: self.stop_ph_edit(apply=False))
        self.e_np.bind("<FocusOut>", lambda e: self.stop_ph_edit(apply=True))

    def stop_ph_edit(self, apply=True):
        n = self._ph_edit
        if n is None: return
        self._ph_edit = None; kind = getattr(self, "_ph_kind", "ly")
        if apply:
            try: txt = self.e_np.get().strip()
            except Exception: txt = ""
            toks = txt.split()
            if kind == "ph":
                if toks and (not self.db or not [t for t in toks if t not in self.db.lang.phonemes()]):
                    if toks != list(n.phonemes):
                        self._set_phonemes(n, toks); n.locked = True; self.dirty = True
            else:
                n.lyric = txt
                self.dirty = True                  # canvas must redraw to show the new lyric
                if toks and not getattr(n, "locked", False):
                    out = []; pack = self._g2p_pack()
                    if pack is None: print("[lyrics] no g2p pack found in svs/g2p/")
                    else:
                        for w in toks:
                            ps = pack.word(w)
                            if ps: out.extend(pack.to_engine(ps) or ps)
                            else: print(f"[lyrics] no reading for {w!r} (pack {pack.id})")
                    if out and self.db:
                        missing = [t for t in out if t not in self.db.lang.phonemes()]
                        if missing:
                            print(f"[lyrics] rejected {txt!r}: generated {' '.join(out)}, missing from lang.ini: {' '.join(missing)}")
                        else:
                            self._set_phonemes(n, out); self.dirty = True
                            print(f"[lyrics] {txt!r} -> {' '.join(out)}")
                    elif out and not self.db:
                        self._set_phonemes(n, out); self.dirty = True
                        print(f"[lyrics] {txt!r} -> {' '.join(out)}")
                    else:
                        print(f"[lyrics] rejected {txt!r}: no phonemes generated")
                    if not out and self.db and not [t for t in toks if t not in self.db.lang.phonemes()]:
                        out = toks
                    if out and (not self.db or not [t for t in out if t not in self.db.lang.phonemes()]):
                        self._set_phonemes(n, out); self.dirty = True
                        print(f"[lyrics] {txt!r} -> {' '.join(out)}")
                    else:
                        print(f"[lyrics] rejected {txt!r}: phonemes not in the voice's lang.ini")
        if self._ph_win is not None: self.cv.delete(self._ph_win); self._ph_win = None
        self.e_np.destroy(); self.focus_set(); self.end_gesture(); self.draw_all()

    def cv_move(self, ev):
        if not self.drag: return
        x, y = self.cv.canvasx(ev.x), self.cv.canvasy(ev.y)
        d = self.drag
        if d["kind"] == "vib":
            v, part = d["v"], d["part"]
            dxms = self.ms_at(x) - self.ms_at(d["x0"])
            if part == "move":
                s = max(0., d["s0"] + dxms); e = s + (d["e0"] - d["s0"])
                cms = (s + e) / 2
                for n in self.notes:
                    nc = n.start + n.dur / 2
                    if abs(cms - nc) < 50.: s += nc - cms; e += nc - cms; break
                v["s"], v["e"] = s, e; v["c"] = d["c0"] + (d["y0"] - y) / ROW_H
            elif part == "dur-l": v["s"] = min(max(0., d["s0"] + dxms), v["e"] - 100.)
            elif part == "dur-r": v["e"] = max(d["e0"] + dxms, v["s"] + 100.)
            elif part == "amp":
                yc = self.curve_y("pit", v["c"]); v["amp"] = max(10., min(300., abs(yc - y) * 100. / ROW_H))
            elif part == "ease-in":
                x0, x1 = self.x_of(v["s"]), self.x_of(v["e"]); v["fin"] = max(0.02, min(0.5, (x - x0) / max(1., x1 - x0)))
            elif part == "ease-out":
                x0, x1 = self.x_of(v["s"]), self.x_of(v["e"]); v["fout"] = max(0.02, min(0.5, (x1 - x) / max(1., x1 - x0)))
            elif part == "freq": v["freq"] = max(2., min(12., v["freq"] + (x - d["x0"]) * 0.02)); d["x0"] = x
            self.dirty = True; self.update_light(); self.draw_all(); return
        if d["kind"] == "erase":
            self._scrub(d, x, y, lambda v: self.curve_y(d["key"], v)); return
        if d["kind"] == "pencil":
            ms, v = self.ms_at(x), self.curve_val("pit", y)
            if ms - self._curve_tmp[-1][0] >= 2.: self._curve_tmp.append([ms, v])
            else: self._curve_tmp[-1] = [ms, v]
            self.draw_all(); return
        if d["kind"] == "playhead":
            self.play_ms = max(0., self.ms_at(x)); self.draw_playhead(); return
        n = d["note"]
        if d["kind"] in ("new", "resize"): n.dur = max(self.beat_ms() / 2, self.snap(self.ms_at(x) - n.start))
        else:
            n.start = max(0., self.snap(self.ms_at(x) - d["dx"]))
            n.midi = min(MIDI_TOP, max(MIDI_BOT, self.midi_at(y - d["dy"])))
        n.end = n.start + n.dur; self.dirty = True; self.draw_all()

    def ccv_down(self, ev):
        if self.curve_param == "note": return
        x, y = self.ccv.canvasx(ev.x), self.ccv.canvasy(ev.y); k = self.curve_param
        if self.tool.get() == "erase":
            self.begin_gesture(); self.drag = dict(kind="erase", key=k, ex=x, ey=y)
            self._scrub(self.drag, x, y, lambda v: self.lane_y(k, v)); return
        if self.tool.get() != "draw": return
        if k not in self.CURVE_READY: return
        self.begin_gesture(); self._curve_tmp = [[self.ms_at(x), self.lane_val(k, y)]]
        self.drag = dict(kind="pencil")

    def ccv_move(self, ev):
        if not self.drag or self.drag["kind"] not in ("pencil", "erase"): return
        if self.curve_param == "note": return
        x, y = self.ccv.canvasx(ev.x), self.ccv.canvasy(ev.y)
        if self.drag["kind"] == "erase":
            k = self.drag["key"]; self._scrub(self.drag, x, y, lambda v: self.lane_y(k, v)); return
        ms, v = self.ms_at(x), self.lane_val(self.curve_param, y)
        if ms - self._curve_tmp[-1][0] >= 2.: self._curve_tmp.append([ms, v])
        else: self._curve_tmp[-1] = [ms, v]
        self.draw_all()

    def end_drag(self):
        if self.drag and self.drag["kind"] == "pencil" and self._curve_tmp is not None:
            if len(self._curve_tmp) > 1:
                self.curves.setdefault(self.curve_param, [])
                self._trim_curve(self.curve_param, self._curve_tmp)
                self.dirty = True; self.update_light()
            self._curve_tmp = None
        self.drag = None; self.end_gesture(); self.draw_all()

    def rv_down(self, ev):
        if self.playing: return
        self.play_ms = max(0., self.ms_at(self.rv.canvasx(ev.x))); self.draw_playhead()

    def sv_down(self, ev):
        x = self.sv.canvasx(ev.x); best, bd = None, 8
        for ms, k in (self._edges or []):
            d = abs(x - self.x_of(ms))
            if d < bd: best, bd = k, d
        self.drag_s = best
        if best: self.begin_gesture(); self._snap = (best[3], best[4]) if len(best) > 4 else None
        else: self._snap = None

    def sv_move(self, ev):
        if not self.drag_s: return
        k = self.drag_s; ms = self.ms_at(self.sv.canvasx(ev.x))
        if k[0] in ("chain", "vow", "rel", "onset", "pre"): n = self._sn[k[1]]
        if k[0] == "chain": n.chain = min(max(ms - n.start, -2000.), n.dur - 40.)
        elif k[0] == "vow":
            rk, s_cv = k[2], k[3]; ov = getattr(n, "ov", None)
            if ov is None: ov = n.ov = {}
            cur = list(ov.get(rk, [None, None])); cur[1] = max(60., ms - s_cv); ov[rk] = cur
        elif k[0] == "rel": n.rel = min(n.dur + 2000., max(40., ms - n.start))
        elif k[0] == "pre": n.pre = min(max(ms - n.start, -2000.), n.dur - 40.)
        elif k[0] == "onset":
            j, lead = k[2], k[3]
            while len(n.onsets) <= j: n.onsets.append(n.dur)
            hi = n.dur - 40.
            if j + 1 < len(n.onsets): hi = min(hi, n.onsets[j + 1] - 40.)
            lo = min((n.onsets[j - 1] + 40.) if j > 0 else 40., hi)
            n.onsets[j] = min(max(ms - n.start + lead, lo), hi)
        elif k[0] in ("p2", "end"):
            n = self._sn[k[1]]; ov = getattr(n, "ov", None)
            if ov is None: ov = n.ov = {}
            cur = list(ov.get(k[2], [None, None])); s, e = k[3], k[4]
            s0, e0 = getattr(self, "_snap", None) or (s, e)
            if k[0] == "p2": cur[0] = min(max(ms - s0, 20.), (e0 - s0) - 20.); cur[1] = e0 - s0
            else: cur[1] = max(40., ms - s0)
            ov[k[2]] = cur
        self.dirty = True; self.draw_all()

    def vol(self): return max(0., self.pv["vol"].get() / 100.)
    def gender(self): return 2 ** ((self.pv["gen"].get() - 50) / 50 * 0.5)
    def gshift(self): return max(0., min(1., self.pv["gsh"].get() / 100.))
    def pitch(self): return (self.pv["pit"].get() - 50) * 2.
    def voi(self): return max(0., min(1., self.pv["voi"].get() / 100.))
    def bre(self): return max(0., self.pv["bre"].get() / 50.)
    def bri(self): return (self.pv["bri"].get() - 50) / 50 * 18.
    def ten(self): return (self.pv["ten"].get() - 50) / 50 * 18.
    def mod(self): return max(0., min(1., self.pv["mod"].get() / 100.))

    def param_changed(self, k):
        if self._restoring: return
        if k in ("pit", "mod"): self.draw_all()
        if k != "vol": self.dirty = True; self.update_light()

    def update_light(self):
        on = self.y is not None and not self.dirty
        self.l_cache.configure(fg=ACC if on else "#555555")

    def _on_space(self, ev):
        w = self.focus_get()
        if w is not None and w.winfo_class() in ("Entry", "Text", "TEntry"): return
        self.toggle_play(); return "break"

    def render(self, autoplay=False):
        if not self.db: messagebox.showerror("Render", "choose a voice first"); return
        if not self.notes: return
        self.stop_play()
        self.db.cfg.formant_shift = self.gshift(); self.db.cfg.gender = self.gender()
        self.db.cfg.pitch_cents = self.pitch(); self.db.cfg.pitch_curve = self.curves["pit"]
        self.db.cfg.vol_curve = self.curves["vol"]
        self.db.cfg.gender_curve = [[[ms, 2 ** ((v - 1.) * 0.5)] for ms, v in s] for s in self.curves["gen"]]
        self.db.cfg.voicing_curve = self.curves["voi"]; self.db.cfg.bre_curve = self.curves["bre"]
        self.db.cfg.bri_curve = self.curves["bri"]; self.db.cfg.ten_curve = self.curves["ten"]
        self.db.cfg.f1_curve = self.curves.get("f1", []); self.db.cfg.f2_curve = self.curves.get("f2", [])
        self.db.cfg.f3_curve = self.curves.get("f3", []); self.db.cfg.vibratos = self.vibratos
        self.db.cfg.modulation = self.mod(); self.db.cfg.pt_trans = self._pt_trans
        self.db.cfg.voicing = self.voi(); self.db.cfg.breath = self.bre()
        self.db.cfg.bright = self.bri(); self.db.cfg.tension = self.ten()
        self.db.cfg.exc_template = self.set_exc.get(); self.db.cfg.use_spp = bool(self.set_spp.get())
        rws, _l = plan(self.db, self.notes, self.beat_ms())
        self.l_time.configure(text="rendering"); self.update_idletasks()
        def work():
            try:
                y = synth.render_rows(self.db, rws, log=print)
                self.y = y; self.dirty = False
                def done():
                    self.update_light()
                    if autoplay: self._start_play()
                self.after(0, done)
            except Exception as e:
                msg = str(e); self.after(0, lambda: messagebox.showerror("Render", msg))
        threading.Thread(target=work, daemon=True).start()

    def _paint_transport(self): self.b_play.configure(text="❚❚" if self.playing else "▶")

    def toggle_play(self):
        if self.playing: self.stop(); return
        if self.y is not None and not self.dirty: self._start_play()
        else: self.render(autoplay=True)

    def stop(self): self.stop_play()

    def rewind(self): self.stop_play(); self.play_ms = 0.; self.draw_playhead()

    def stop_play(self):
        if self.player is not None and self.player.poll() is None: self.player.terminate()
        self.player = None; self.playing = False; self._paint_transport()

    def _start_play(self):
        if self.y is None: return
        from scipy.io import wavfile
        sr = self.db.cfg.sample_rate; tot_ms = len(self.y) / sr * 1000.
        off_ms = min(max(self.play_ms, 0.), tot_ms); off = int(off_ms / 1000. * sr)
        y = self.y[off:] * self.vol()
        if not len(y): return
        p = os.path.join(tempfile.gettempdir(), "svs_roll.wav")
        wavfile.write(p, sr, (y * 32767).astype(np.int16))
        try: self.player = subprocess.Popen(["afplay", p])
        except Exception:
            try: os.startfile(p); self.player = None
            except Exception: return
        self.play_off = off / sr; self.play_t0 = time.time()
        self.playing = True; self._paint_transport(); self.follow_playhead(); self._tick()

    def _tick(self):
        if not self.playing: return
        pos = self.play_off + (time.time() - self.play_t0)
        tot = len(self.y) / self.db.cfg.sample_rate if self.y is not None else 0.
        if pos >= tot: self.stop_play(); self.play_ms = 0.; self.draw_playhead(); return
        self.play_ms = pos * 1000.; self.draw_playhead(); self.follow_playhead(); self.after(40, self._tick)

    def do_export(self):
        if self.y is None: messagebox.showerror("Export", "render first"); return
        from scipy.io import wavfile
        p = filedialog.asksaveasfilename(defaultextension=".wav", initialfile="take.wav")
        if p: wavfile.write(p, self.db.cfg.sample_rate, (self.y * self.vol() * 32767).astype(np.int16))

    def _wheel(self, ev):
        if ev.num == 4: self.cv.yview_scroll(-3, "units"); return "break"
        if ev.num == 5: self.cv.yview_scroll(3, "units"); return "break"
        if ev.num == 6: self.cv.xview_scroll(-3, "units"); return "break"
        if ev.num == 7: self.cv.xview_scroll(3, "units"); return "break"
        u = int(-ev.delta) if abs(ev.delta) < 120 else int(-ev.delta / 120) * 3
        if not u: u = -1 if ev.delta > 0 else 1
        if ev.state & 0x1: self.cv.xview_scroll(-u, "units")
        else: self.cv.yview_scroll(u, "units")
        return "break"

    def save_seq(self, ask=False):
        p = self._seq_path
        if ask or not p:
            p = filedialog.asksaveasfilename(defaultextension=".json", initialfile="sequence.json",
                                             filetypes=[("sequence", "*.json"), ("all", "*.*")])
            if not p: return
            self._seq_path = p
        data = dict(format="svs-sequence", version=4, bpm=float(self.e_bpm.get()), sig=self.e_sig.get(),
                    params={k: v.get() for k, v in self.pv.items()},
                    curves={k: [list(map(list, s)) for s in self.curves.get(k, [])] for k, _n in CURVE_PARAMS if k != "note"},
                    vibratos=[dict(v) for v in self.vibratos],
                    notes=[dict(start=n.start, dur=n.dur, midi=n.midi, phonemes=n.phonemes, onsets=n.onsets,
                                chain=n.chain, vow=n.vow, rel=n.rel, ov=n.ov, pre=n.pre,
                                pt_ol=n.pt_ol, pt_or=n.pt_or, pt_dl=n.pt_dl, pt_dr=n.pt_dr,
                                pt_depl=n.pt_depl, pt_depr=n.pt_depr, lyric=n.lyric, locked=n.locked)
                           for n in sorted(self.notes, key=lambda n: n.start)])
        with open(p, "w", encoding="utf-8") as f: json.dump(data, f, indent=1)

    def load_seq(self):
        p = filedialog.askopenfilename(filetypes=[("sequence", "*.json"), ("all", "*.*")])
        if not p: return
        try:
            with open(p, encoding="utf-8") as f: data = json.load(f)
            self._undo.append(self._state())
            if len(self._undo) > 50: self._undo.pop(0)
            self._redo.clear(); self._seq_path = p
            cd = data.get("curves")
            if cd is None: cd = {"pit": data.get("pitch", [])}
            for k, _n in CURVE_PARAMS:
                if k == "note": continue
                self.curves[k] = [list(map(list, s)) for s in cd.get(k, [])]
            self.vibratos = [dict(v) for v in data.get("vibratos", [])]
            notes = []
            for nd in data.get("notes", []):
                ph = [str(x) for x in nd.get("phonemes", ["a"])]
                ons = [float(x) for x in nd.get("onsets", [0.0])]
                while len(ons) < len(ph): ons.append(float(nd.get("dur", 500.)))
                n = Note(float(nd["start"]), float(nd["dur"]), int(nd["midi"]), ph, ons)
                n.chain = nd.get("chain"); n.vow = nd.get("vow"); n.rel = nd.get("rel")
                n.ov = nd.get("ov") or {}; n.pre = nd.get("pre")
                n.pt_ol = nd.get("pt_ol", 0.); n.pt_or = nd.get("pt_or", 0.)
                n.pt_dl = nd.get("pt_dl", 120.); n.pt_dr = nd.get("pt_dr", 120.)
                n.pt_depl = nd.get("pt_depl", 0.); n.pt_depr = nd.get("pt_depr", 0.)
                n.lyric = nd.get("lyric"); n.locked = bool(nd.get("locked"))
                notes.append(n)
            self.notes = notes; self.sel = None; self.y = None
            if "bpm" in data: self.e_bpm.delete(0, "end"); self.e_bpm.insert(0, str(data["bpm"]))
            if "sig" in data: self.e_sig.delete(0, "end"); self.e_sig.insert(0, str(data["sig"]))
            for k, v in (data.get("params") or {}).items():
                if k in self.pv: self.pv[k].set(v)
            self.dirty = True; self.draw_all()
        except Exception as e: messagebox.showerror("Load", str(e))

def main():
    Roll2App().mainloop()

if __name__ == "__main__":
    main()
