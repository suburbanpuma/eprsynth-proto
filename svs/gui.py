# =============================================================================
# gui.py — SVS Developer Tool.
# Tabs:
#   Database     : create/open DBs (pitch groups + vocal styles), manifest view.
#   Import       : wav+labels import (threaded, logged).
#   Units        : inventory tree + visual unit editor fused:
#                  model-rendered waveform preview, draggable p1/p2/trans/end
#                  markers (Apply timing), Re-model from wav+lab, Space=play.
#   Label writer : load a wav, view waveform, create/drag lab entries
#                  (articulation/sustain), save .lab, model straight into DB.
# =============================================================================
import json
import os, subprocess, tempfile, threading, traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
from . import core, langcfg, synth
from .analysis import analyze
from .config import AnalysisConfig
from .labels import Label, parse_batchlab, parse_labels
from .unit import build_steady, build_unit, save_unit, wave_env

# label-writer marker keys: (attr, label, color)
MARKS = [("start", "START", "black"), ("m_p1", "P1", "blue"), ("m_p2", "P2", "green"),
         ("m_trans", "TRANS", "orange"), ("end", "END", "red")]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SVS Developer Tool")
        self.geometry("1080x720")
        self.db = self.info = None
        self.nb = ttk.Notebook(self); self.nb.pack(fill="both", expand=True)
        self._tab_db(); self._tab_import(); self._tab_units(); self._tab_lab()
        self.bind("<space>", lambda e: self.play_unit())

    # ================= Database =================
    def _tab_db(self):
        f = ttk.Frame(self.nb); self.nb.add(f, text="Database")
        g = ttk.LabelFrame(f, text="New database"); g.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        self.e_dbname = ttk.Entry(g, width=24); self.e_dbname.insert(0, "Aurora")
        self.e_dbdev = ttk.Entry(g, width=24); self.e_dbdev.insert(0, "Studio X")
        self.e_dbver = ttk.Entry(g, width=8); self.e_dbver.insert(0, "1.0.0")
        self.e_groups = ttk.Entry(g, width=24); self.e_groups.insert(0, "C2, A3, G4")
        self.e_styles = ttk.Entry(g, width=24); self.e_styles.insert(0, "base")
        for r, (w, e) in enumerate([("Name", self.e_dbname), ("Developer", self.e_dbdev),
                                    ("Version", self.e_dbver), ("", None),
                                    ("Pitch groups", self.e_groups)]):
            if e:
                ttk.Label(g, text=w).grid(row=r, column=0, sticky="w", padx=4)
                e.grid(row=r, column=1, sticky="w", padx=4)
        ttk.Label(g, text="Styles").grid(row=5, column=0, sticky="w", padx=4)
        self.e_styles.grid(row=5, column=1, sticky="w", padx=4)
        ttk.Label(g, text="Language").grid(row=3, column=0, sticky="w", padx=4)
        self.cb_lang = ttk.Combobox(g, values=langcfg.list_templates(), width=8, state="readonly")
        self.cb_lang.set("ja"); self.cb_lang.grid(row=3, column=1, sticky="w", padx=4)
        ttk.Button(g, text="Create...", command=self.create_db).grid(row=7, column=1,
                                                                     sticky="w", padx=4, pady=4)
        ttk.Button(f, text="Open DB...", command=self.open_db).grid(row=1, column=0, sticky="w", padx=8)
        self.t_man = tk.Text(f, height=10)
        self.t_man.grid(row=2, column=0, sticky="nsew", padx=8, pady=6)
        f.rowconfigure(2, weight=1); f.columnconfigure(0, weight=1)

    def create_db(self):
        path = filedialog.askdirectory(title="Database folder")
        if not path: return
        groups = [s.strip() for s in self.e_groups.get().split(",") if s.strip()]
        if not groups: messagebox.showerror("DB", "need at least one pitch group"); return
        styles = [s.strip() for s in self.e_styles.get().split(",") if s.strip()]
        if not styles: styles = ["base"]
        if "base" not in styles: styles = ["base"] + styles   # engine primary first
        try:
            core.create_db(path, self.e_dbname.get(), self.e_dbdev.get(),
                           self.e_dbver.get(), self.cb_lang.get(), groups)
        except Exception as e:
            messagebox.showerror("DB", str(e)); return
        for st in styles[1:]:                                 # extra styles share layout
            for g in groups:
                d = os.path.join(path, st, g)
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, "index.json"), "w") as f:
                    json.dump({"units": {}, "steady": {}}, f)
        self._write_manifest_styles(path, styles, groups)
        self._set_db(path)

    def _write_manifest_styles(self, path, styles, groups):
        """Safely update manifest using configparser to avoid DuplicateOptionError."""
        import configparser
        mp = os.path.join(path, "manifest.ini")
        cp = configparser.ConfigParser()
        cp.read(mp, encoding="utf-8")
        if not cp.has_section("singer"):
            cp.add_section("singer")
        cp.set("singer", "styles", ",".join(styles))
        # Clear ALL pitchgroups to prevent duplicates and ensure clean state
        for sec in list(cp.sections()):
            if sec.startswith("pitchgroups."):
                cp.remove_section(sec)
        # Add pitchgroups for ALL styles (including base)
        for st in styles:
            sec = f"pitchgroups.{st}"
            if not cp.has_section(sec):
                cp.add_section(sec)
            cp.set(sec, "groups", ", ".join(groups))
        with open(mp, "w", encoding="utf-8") as f:
            cp.write(f)

    def open_db(self):
        p = filedialog.askopenfilename(filetypes=[("manifest", "manifest.ini"), ("all", "*.*")])
        if p: self._set_db(os.path.dirname(p))

    def _set_db(self, path):
        self.db = path; self.info = core.open_db(path)
        self.t_man.delete("1.0", "end")
        self.t_man.insert("end", f"path: {path}\n" +
                          "\n".join(f"{k}: {v}" for k, v in self.info.items()))
        for cb in (self.cb_group, self.cb_ugroup, self.cb_lgroup):
            cb["values"] = self.info["groups"]; cb.set(self.info["groups"][0])
        self.reload_units()

    # ================= Import =================
    def _tab_import(self):
        f = ttk.Frame(self.nb); self.nb.add(f, text="Import")
        r = ttk.Frame(f); r.pack(fill="x", padx=8, pady=4)
        ttk.Label(r, text="Group").pack(side="left")
        self.cb_group = ttk.Combobox(r, width=8, state="readonly"); self.cb_group.pack(side="left", padx=4)
        self.e_wav = ttk.Entry(r, width=38); self.e_wav.pack(side="left", padx=4)
        ttk.Button(r, text="wav...", command=lambda: self._browse(self.e_wav, True)).pack(side="left")
        self.e_lab = ttk.Entry(r, width=28); self.e_lab.pack(side="left", padx=4)
        ttk.Button(r, text="labels...", command=lambda: self._browse(self.e_lab, False)).pack(side="left")
        ttk.Button(r, text="Import", command=self.do_import).pack(side="left", padx=8)
        self.pb = ttk.Progressbar(f, mode="indeterminate"); self.pb.pack(fill="x", padx=8)
        self.t_log = tk.Text(f, height=22); self.t_log.pack(fill="both", expand=True, padx=8, pady=6)

    def _browse(self, entry, wav):
        p = filedialog.askopenfilename(
            filetypes=[("wav", "*.wav")] if wav else [("labels", "*.lab *.txt *.batchlab"), ("all", "*.*")])
        if p: entry.delete(0, "end"); entry.insert(0, p)

    def _log(self, msg):
        self.after(0, lambda: (self.t_log.insert("end", msg + "\n"), self.t_log.see("end")))

    def do_import(self):
        if not self.db: messagebox.showerror("Import", "open a database first"); return
        wav, lab, grp = self.e_wav.get(), self.e_lab.get(), self.cb_group.get()
        if not (wav and lab and grp):
            messagebox.showerror("Import", "wav, labels and group required"); return
        self.pb.start()
        def work():
            try:
                core.import_recording(self.db, grp, wav, lab, log=self._log)
                self._log("import finished.")
                self.after(0, self.reload_units)
            except Exception:
                self._log(traceback.format_exc())
            finally:
                self.after(0, self.pb.stop)
        threading.Thread(target=work, daemon=True).start()

    # ================= Units (inventory + visual editor) =================
    UMARKS = [("p1", "blue"), ("p2", "green"), ("trans", "orange"), ("end", "red")]

    def _tab_units(self):
        f = ttk.Frame(self.nb); self.nb.add(f, text="Units")
        top = ttk.Frame(f); top.pack(fill="x", padx=8, pady=4)
        ttk.Label(top, text="group").pack(side="left")
        self.cb_ugroup = ttk.Combobox(top, width=8, state="readonly")
        self.cb_ugroup.pack(side="left", padx=4)
        self.cb_ugroup.bind("<<ComboboxSelected>>", lambda e: self.reload_units())
        ttk.Button(top, text="Refresh", command=self.reload_units).pack(side="left", padx=6)
        self.l_miss = ttk.Label(top, text=""); self.l_miss.pack(side="left", padx=12)
        ttk.Label(top, text="space = play model", foreground="gray60").pack(side="right")
        body = ttk.Frame(f); body.pack(fill="both", expand=True, padx=8, pady=4)
        self.tree = ttk.Treeview(body, columns=("unit", "f0", "details"), show="headings", height=16)
        for c, w in (("unit", 150), ("f0", 60), ("details", 260)):
            self.tree.heading(c, text=c); self.tree.column(c, width=w)
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.fill_unit())
        right = ttk.Frame(body); right.pack(side="left", fill="both", expand=True, padx=8)
        self.cv_u = tk.Canvas(right, height=180, bg="white")
        self.cv_u.pack(fill="x", pady=4)
        self.cv_u.bind("<Button-1>", self.u_drag_pick)
        self.cv_u.bind("<B1-Motion>", self.u_drag_move)
        self.cv_u.bind("<ButtonRelease-1>", lambda e: self.u_draw())
        self.l_uread = ttk.Label(right, text=""); self.l_uread.pack(anchor="w")
        bb = ttk.Frame(right); bb.pack(fill="x", pady=4)
        ttk.Button(bb, text="Apply timing", command=self.apply_timing).pack(side="left")
        ttk.Button(bb, text="Re-model from wav+lab...", command=self.remodel).pack(side="left", padx=6)
        self.l_ust = ttk.Label(bb, text=""); self.l_ust.pack(side="left", padx=8)
        self._units = []; self._usel = None
        self._uwave = None; self._umk = None; self._ums = 1.; self._udrag = None

    def reload_units(self):
        """Fill the inventory tree (diphones then sustains) + missing-steady banner."""
        self.tree.delete(*self.tree.get_children()); self._units = []; self._usel = None
        if not self.db: return
        g = self.cb_ugroup.get()
        with open(os.path.join(self.db, "base", g, "index.json")) as fh:
            idx = json.load(fh)
        for pair, m in sorted(idx["units"].items()):
            self._units.append(("diph", pair, m))
            self.tree.insert("", "end", values=(pair, f"{m['rec_pitch']:.1f}",
                                                 [round(v) for v in m["formants"]]))
        for ph, m in sorted(idx.get("steady", {}).items()):
            mk = m.get("markers", {})
            self._units.append(("sus", ph, m))
            self.tree.insert("", "end", values=(
                f"~{ph} [sustain]", f"{m.get('rec_pitch', 0):.1f}",
                f"loop {mk.get('p1', 0):.0f}..{mk.get('trans', 0):.0f} ms, "
                f"{m.get('frames', '?')} frames"))
        lang = langcfg.lang_for_db(self.db)
        missing = [p for p in sorted(lang.phonemes())
                   if lang.steady(p) and p not in idx["steady"]]
        self.l_miss.configure(text=("missing steady: " + ", ".join(missing)) if missing
                              else "all steady-capable phonemes have sustains")

    def fill_unit(self):
        """Load the unit and render its MODEL waveform for the preview."""
        s = self.tree.selection()
        if not s: return
        self._usel = self._units[int(self.tree.index(s[0]))]
        kind, key, m = self._usel
        arr = np.load(os.path.join(self.db, "base", self.cb_ugroup.get(), m["file"]))
        self._umk = dict(m.get("markers", {}))
        if len(arr["t"]):
            cfg = AnalysisConfig()
            frames = [synth._frame(arr, i, 1.0) for i in range(len(arr["t"]))]
            y = synth.synth_frames(frames, cfg)          # model-generated envelope
            self._uwave = wave_env(y, 128)
            self._ums = len(y) / cfg.sample_rate * 1000.
        else:
            self._uwave = None
            self._ums = self._umk.get("end", 1.)
        self.u_draw()

    def u_draw(self):
        cv = self.cv_u; cv.delete("all")
        w = max(cv.winfo_width(), 100); h = 180
        if self._uwave is not None and len(self._uwave):
            ww = self._uwave; mx = ww.max() or 1.; n = len(ww)
            for px in range(w):
                i0 = int(n * px / w); i1 = max(i0 + 1, int(n * (px + 1) / w))
                v = ww[i0:i1].max() / mx
                cv.create_line(px, h / 2 - v * (h / 2 - 6), px, h / 2 + v * (h / 2 - 6),
                               fill="gray50")
        else:
            cv.create_text(w / 2, h / 2, text="(empty unit)", fill="gray60")
        if self._umk:
            cv.create_line(0, 0, 0, h, fill="black", width=2)
            for k, col in self.UMARKS:
                if k in self._umk:
                    x = self._umk[k] / self._ums * w
                    cv.create_line(x, 0, x, h, fill=col, width=2)
                    cv.create_text(x + 2, 8, text=k, fill=col, anchor="w")
            self.l_uread.configure(text="   ".join(
                f"{k}={self._umk[k]:.0f}" for k, _c in self.UMARKS if k in self._umk))

    def u_drag_pick(self, ev):
        if not self._umk: return
        w = max(self.cv_u.winfo_width(), 100)
        best, bd = None, 8
        for k, _c in self.UMARKS:
            if k in self._umk:
                d = abs(ev.x - self._umk[k] / self._ums * w)
                if d < bd: best, bd = k, d
        self._udrag = best

    def u_drag_move(self, ev):
        if not self._udrag: return
        w = max(self.cv_u.winfo_width(), 100)
        ms = ev.x / w * self._ums
        order = [k for k, _c in self.UMARKS if k in self._umk]
        i = order.index(self._udrag)
        lo = self._umk[order[i - 1]] if i else 0.
        hi = self._umk[order[i + 1]] if i < len(order) - 1 else self._ums
        self._umk[self._udrag] = min(max(ms, lo), hi)
        self.u_draw()

    def apply_timing(self):
        """Write the dragged markers back to the group index."""
        if not self._usel or not self._umk: return
        kind, key, m = self._usel
        m["markers"] = {**m.get("markers", {}), **self._umk}
        self._write_index(self.cb_ugroup.get(), kind, key, m)
        self._usel = (kind, key, m)
        self.l_ust.configure(text="timing saved")

    def _write_index(self, g, kind, key, meta):
        p = os.path.join(self.db, "base", g, "index.json")
        with open(p) as f: idx = json.load(f)
        (idx["units"] if kind == "diph" else idx["steady"])[key] = meta
        with open(p, "w") as f: json.dump(idx, f, indent=1)

    def remodel(self):
        """Rebuild the EpR model of the selected unit from its original wav+lab,
        using the currently edited (relative) markers."""
        if not self._usel: return
        kind, key, m = self._usel
        wav = filedialog.askopenfilename(filetypes=[("wav", "*.wav")])
        if not wav: return
        lab = filedialog.askopenfilename(filetypes=[("labels", "*.lab *.txt *.batchlab")])
        if not lab: return
        try:
            cfg = AnalysisConfig()
            lang = langcfg.lang_for_db(self.db)
            x = core.read_wav(wav, cfg)
            sr = cfg.sample_rate
            dur_ms = len(x) / sr * 1000.
            entries = list(parse_batchlab(lab, lang.phonemes())) if lab.endswith(".batchlab") \
                else [(None, lb) for lb in parse_labels(lab, lang.phonemes(), dur_ms)]
            tok = key.split() if kind == "diph" else [key]
            match = None
            for fn, lb in entries:
                if kind == "diph" and not lb.sustain and lb.p1 == tok[0] and lb.p2 == tok[1]:
                    match = lb; break
                if kind == "sus" and lb.sustain and lb.p1 == tok[0]:
                    match = lb; break
            if match is None:
                messagebox.showerror("Re-model", "no matching label line found"); return
            mk = m.get("markers", {})
            frames = analyze(x, cfg)
            if kind == "diph":
                lb2 = Label(match.p1, match.p2, match.start, match.start + mk["p1"],
                            match.start + mk["p2"], match.start + mk["trans"],
                            match.start + mk["end"])
                arrays, meta = build_unit(frames, lb2.sec(), cfg, sr)
                meta["markers"] = {k: v * 1000. for k, v in meta["markers"].items()}
            else:
                lb2 = Label(match.p1, None, match.start, match.start + mk["p1"], None,
                            match.start + mk["trans"], match.start + mk["end"])
                arrays, meta = build_steady(frames, lb2, cfg, sr)
            arrays["wave"] = wave_env(x[int(match.start / 1000 * sr):int(match.end / 1000 * sr)])
            g = self.cb_ugroup.get()
            save_unit(os.path.join(self.db, "base", g, m["file"]), arrays)
            m2 = dict(m); m2.update(markers=meta["markers"], rec_pitch=meta["rec_pitch"],
                                    formants=meta.get("formants", m.get("formants", [])),
                                    frames=len(arrays["t"]))
            self._write_index(g, kind, key, m2)
            self._usel = (kind, key, m2)
            self.l_ust.configure(text="model rebuilt")
            self.fill_unit()
            self.reload_units()
        except Exception:
            messagebox.showerror("Re-model", traceback.format_exc())

    def play_unit(self):
        """Space: audition the stored model (diphone full; sustain looped 0.6s)."""
        w = self.focus_get()
        if w is not None and w.winfo_class() in ("Entry", "Text", "Button"): return
        if not self._usel or not self.db: return
        kind, key, m = self._usel
        cfg = AnalysisConfig()
        arr = np.load(os.path.join(self.db, "base", self.cb_ugroup.get(), m["file"]))
        if kind == "diph":
            frames = [synth._frame(arr, i, 1.0) for i in range(len(arr["t"]))]
        else:
            mk = m.get("markers", {})
            t = arr["t"]
            i0 = int(np.searchsorted(t, mk.get("p1", 0.) / 1000.))
            i1 = max(int(np.searchsorted(t, mk.get("trans", t[-1] * 1000.) / 1000.)), i0 + 1)
            req = int(0.6 / cfg.hop_s)
            frames = [synth._frame(arr, i0 + (i % (i1 - i0)), 1.0) for i in range(req)]
        y = synth.synth_frames(frames, cfg)
        y = y * 0.8 / (np.abs(y).max() or 1.)
        p = os.path.join(tempfile.gettempdir(), "svs_unit.wav")
        from scipy.io import wavfile
        wavfile.write(p, cfg.sample_rate, (y * 32767).astype(np.int16))
        try: subprocess.Popen(["afplay", p])
        except Exception:
            try: os.startfile(p)
            except Exception: pass

    # ================= Label writer =================
    def _tab_lab(self):
        f = ttk.Frame(self.nb); self.nb.add(f, text="Label writer")
        r0 = ttk.Frame(f); r0.pack(fill="x", padx=8, pady=4)
        self.e_lwav = ttk.Entry(r0, width=36); self.e_lwav.pack(side="left")
        ttk.Button(r0, text="wav...", command=self.l_load_wav).pack(side="left", padx=4)
        ttk.Label(r0, text="group").pack(side="left", padx=(8, 0))
        self.cb_lgroup = ttk.Combobox(r0, width=8, state="readonly"); self.cb_lgroup.pack(side="left")
        ttk.Label(r0, text="view ms").pack(side="left", padx=(8, 0))
        self.e_lva = ttk.Entry(r0, width=8); self.e_lva.insert(0, "0"); self.e_lva.pack(side="left")
        self.e_lvb = ttk.Entry(r0, width=8); self.e_lvb.pack(side="left")
        ttk.Button(r0, text="Zoom", command=self.l_draw).pack(side="left", padx=2)
        r1 = ttk.Frame(f); r1.pack(fill="x", padx=8)
        ttk.Button(r1, text="+ articulation", command=lambda: self.l_add(False)).pack(side="left")
        ttk.Button(r1, text="+ sustain", command=lambda: self.l_add(True)).pack(side="left", padx=4)
        ttk.Button(r1, text="Delete", command=self.l_del).pack(side="left")
        ttk.Button(r1, text="Save lab", command=self.l_save).pack(side="left", padx=8)
        ttk.Button(r1, text="Model into DB", command=self.l_model).pack(side="left")
        self.l_lst = ttk.Label(r1, text=""); self.l_lst.pack(side="left", padx=8)
        self.cv_l = tk.Canvas(f, height=200, bg="white")
        self.cv_l.pack(fill="x", padx=8, pady=4)
        self.cv_l.bind("<Button-1>", self.l_down)
        self.cv_l.bind("<B1-Motion>", self.l_move)
        self.cv_l.bind("<ButtonRelease-1>", lambda e: (setattr(self, "_ldrag", None), self.l_sync()))
        r2 = ttk.Frame(f); r2.pack(fill="both", expand=True, padx=8, pady=4)
        self.lb_l = tk.Listbox(r2, height=8); self.lb_l.pack(side="left", fill="both", expand=True)
        self.lb_l.bind("<<ListboxSelect>>", lambda e: (self.l_sel(), self.l_draw()))
        ed = ttk.Frame(r2); ed.pack(side="left", padx=8)
        self.le_p1 = ttk.Entry(ed, width=6); self.le_p2 = ttk.Entry(ed, width=6)
        ttk.Label(ed, text="P1").grid(row=0, column=0); self.le_p1.grid(row=0, column=1)
        ttk.Label(ed, text="P2").grid(row=0, column=2); self.le_p2.grid(row=0, column=3)
        self.lme = {}
        for i, (key, txt) in enumerate([("start", "START"), ("m_p1", "P1"), ("m_p2", "P2"),
                                        ("m_trans", "TRANS"), ("end", "END")]):
            ttk.Label(ed, text=txt).grid(row=1 + i, column=0)
            e = ttk.Entry(ed, width=10); e.grid(row=1 + i, column=1, columnspan=2)
            self.lme[key] = e
        ttk.Button(ed, text="Apply", command=self.l_apply).grid(row=7, column=0, columnspan=3, pady=4)
        self._lx = None; self._lwave = None; self._llabels = []; self._lsel = -1; self._ldrag = None

    def l_load_wav(self):
        p = filedialog.askopenfilename(filetypes=[("wav", "*.wav")])
        if not p: return
        cfg = AnalysisConfig()
        self._lx = core.read_wav(p, cfg)
        self._lsr = cfg.sample_rate
        self._lwave = wave_env(self._lx, 256)              # coarse preview envelope
        self.e_lwav.delete(0, "end"); self.e_lwav.insert(0, p)
        dur = len(self._lx) / self._lsr * 1000.
        self.e_lva.delete(0, "end"); self.e_lva.insert(0, "0")
        self.e_lvb.delete(0, "end"); self.e_lvb.insert(0, f"{dur:.0f}")
        self.l_draw()

    def l_add(self, sus):
        """Drop a new label spanning the current view (defaults to drag afterwards)."""
        a = float(self.e_lva.get() or 0); b = float(self.e_lvb.get() or a + 1000)
        if sus:
            q = (b - a) / 4.
            self._llabels.append(Label("a", None, a, a + q, None, a + 2 * q, a + 3 * q))
        else:
            q = (b - a) / 6.
            self._llabels.append(Label("a", "a", a, a + q, a + 2 * q, a + 3 * q, a + 4 * q))
        self._lsel = len(self._llabels) - 1
        self.l_sync(); self.l_draw()

    def l_del(self):
        if 0 <= self._lsel < len(self._llabels):
            self._llabels.pop(self._lsel)
            self._lsel = min(self._lsel, len(self._llabels) - 1)
            self.l_sync(); self.l_draw()

    def l_sync(self):
        self.lb_l.delete(0, "end")
        for l in self._llabels: self.lb_l.insert("end", l.line())
        if 0 <= self._lsel < len(self._llabels):
            self.lb_l.selection_set(self._lsel); self.l_fill(self._llabels[self._lsel])

    def l_sel(self):
        s = self.lb_l.curselection()
        if s: self._lsel = s[0]; self.l_fill(self._llabels[self._lsel])

    def l_fill(self, l):
        self.le_p1.delete(0, "end"); self.le_p1.insert(0, l.p1)
        self.le_p2.configure(state="normal"); self.le_p2.delete(0, "end")
        if l.sustain: self.le_p2.configure(state="disabled")
        else: self.le_p2.insert(0, l.p2)
        for key, _t, _c in MARKS:
            e = self.lme[key]; e.configure(state="normal")
            v = getattr(l, key)
            e.delete(0, "end")
            if v is None: e.configure(state="disabled")
            else: e.insert(0, f"{v:.1f}")

    def l_apply(self):
        """Commit phoneme/marker edits of the selected label (validated, monotonic)."""
        if self._lsel < 0: return
        lang = langcfg.lang_for_db(self.db) if self.db else None
        ph = lang.phonemes() if lang else None
        p1 = self.le_p1.get().strip()
        if ph and p1 not in ph: messagebox.showerror("Labels", "unknown phoneme"); return
        cur = self._llabels[self._lsel]
        t = [float(self.lme[k].get()) for k in ("start", "m_p1", "m_trans", "end")]
        if cur.sustain:
            if not (t[0] <= t[1] <= t[2] <= t[3]):
                messagebox.showerror("Labels", "markers must be monotonic (ms)"); return
            self._llabels[self._lsel] = Label(p1, None, t[0], t[1], None, t[2], t[3])
        else:
            p2 = self.le_p2.get().strip()
            if ph and p2 not in ph: messagebox.showerror("Labels", "unknown phoneme"); return
            t.insert(2, float(self.lme["m_p2"].get()))
            if not (t[0] <= t[1] <= t[2] <= t[3] <= t[4]):
                messagebox.showerror("Labels", "markers must be monotonic (ms)"); return
            self._llabels[self._lsel] = Label(p1, p2, *t)
        self.l_sync(); self.l_draw()

    def l_draw(self):
        """Waveform of the view window + marker lines of the selected label."""
        cv = self.cv_l; cv.delete("all")
        if self._lwave is None: return
        w = max(cv.winfo_width(), 100); h = 200
        a = float(self.e_lva.get() or 0); b = float(self.e_lvb.get() or 1.)
        if b <= a: return
        ms_per_pt = 256 / self._lsr * 1000.
        ia, ib = int(a / ms_per_pt), int(b / ms_per_pt) + 1
        seg = self._lwave[max(0, ia):min(len(self._lwave), ib)]
        mx = seg.max() or 1.; n = max(1, len(seg))
        for px in range(w):
            i0 = int(n * px / w); i1 = max(i0 + 1, int(n * (px + 1) / w))
            v = seg[i0:i1].max() / mx
            cv.create_line(px, h / 2 - v * (h / 2 - 6), px, h / 2 + v * (h / 2 - 6), fill="gray50")
        if 0 <= self._lsel < len(self._llabels):
            l = self._llabels[self._lsel]
            for key, txt, col in MARKS:
                ms = getattr(l, key)
                if ms is None: continue
                if a <= ms <= b:
                    x = (ms - a) / (b - a) * w
                    cv.create_line(x, 0, x, h, fill=col, width=2)
                    cv.create_text(x + 2, 8, text=txt, fill=col, anchor="w")

    def l_down(self, ev):
        if self._lsel < 0 or self._lwave is None: return
        w = max(self.cv_l.winfo_width(), 100)
        a = float(self.e_lva.get() or 0); b = float(self.e_lvb.get() or 1.)
        l = self._llabels[self._lsel]; best, bd = None, 8
        for key, _t, _c in MARKS:
            ms = getattr(l, key)
            if ms is None or not (a <= ms <= b): continue
            d = abs(ev.x - (ms - a) / (b - a) * w)
            if d < bd: best, bd = key, d
        self._ldrag = best

    def l_move(self, ev):
        if not self._ldrag: return
        w = max(self.cv_l.winfo_width(), 100)
        a = float(self.e_lva.get() or 0); b = float(self.e_lvb.get() or 1.)
        ms = a + ev.x / w * (b - a)
        l = self._llabels[self._lsel]
        order = [k for k, _t, _c in MARKS if not (k == "m_p2" and l.sustain)]
        i = order.index(self._ldrag)
        lo = getattr(l, order[i - 1]) if i else 0.
        hi = getattr(l, order[i + 1]) if i < len(order) - 1 else len(self._lx) / self._lsr * 1000.
        setattr(l, self._ldrag, max(lo, min(hi, ms)))
        self.lme[self._ldrag].delete(0, "end")
        self.lme[self._ldrag].insert(0, f"{getattr(l, self._ldrag):.1f}")
        self.l_draw()

    def l_save(self):
        if not self._llabels: return
        p = filedialog.asksaveasfilename(defaultextension=".lab", initialfile="take.lab")
        if p:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("\n".join(l.line() for l in self._llabels) + "\n")
            self.l_lst.configure(text=f"saved {os.path.basename(p)}")

    def l_model(self):
        """Write a temp .lab and run the normal import pipeline into the group."""
        if not self.db or self._lx is None or not self._llabels:
            messagebox.showerror("Model", "need DB, wav and labels"); return
        grp = self.cb_lgroup.get()
        if not grp: messagebox.showerror("Model", "group required"); return
        wav = self.e_lwav.get()
        tmp = os.path.join(tempfile.gettempdir(), "svs_writer.lab")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(l.line() for l in self._llabels) + "\n")
        self.l_lst.configure(text="modeling..."); self.update_idletasks()
        def work():
            try:
                core.import_recording(self.db, grp, wav, tmp, log=print)
                self.after(0, lambda: self.l_lst.configure(text="modeled into DB"))
                self.after(0, self.reload_units)
            except Exception:
                self.after(0, lambda: (self.l_lst.configure(text="error"),
                                       messagebox.showerror("Model", traceback.format_exc())))
        threading.Thread(target=work, daemon=True).start()


def main():
    App().mainloop()

if __name__ == "__main__":
    main()
