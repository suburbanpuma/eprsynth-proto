import os, subprocess, tempfile, threading, time, traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
from scipy.io import wavfile

from . import core, langcfg
from .analysis import stft, detect_peaks, estimate_pitch, noise_floor_env
from .config import AnalysisConfig
from .epr import model_frame
from .synth import synth_frames

SILENCE_SET = {"sil", "pau", "sp", "br"}
NOISE_TYPES = ("fricative", "aspirate", "plosive")

def read_labels(path):
    segs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"): continue
            tok = line.split()
            if len(tok) != 3: continue
            a, b, ph = float(tok[0]), float(tok[1]), tok[2]
            if b > 1000.:                      # 100 ns ticks (HTK style)
                a /= 1e7; b /= 1e7
            segs.append((a, b, ph))
    return segs

def ph_at(segs, t):
    for a, b, ph in segs:
        if a <= t < b: return ph
    return segs[-1][2] if segs else "sil"

def env_bands(mag_db, freqs, bands):
    edges = np.linspace(0, freqs[-1], bands + 1)
    return np.array([mag_db[(freqs >= a) & (freqs < b)].max()
                     if ((freqs >= a) & (freqs < b)).any() else -100.0
                     for a, b in zip(edges[:-1], edges[1:])], np.float32)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("EpR Workbench")
        self.geometry("520x300")
        self.cfg = AnalysisConfig()
        self.frames = None; self.y = None

        r = ttk.Frame(self); r.pack(fill="x", padx=8, pady=4)
        self.e_wav = ttk.Entry(r, width=36); self.e_wav.pack(side="left")
        ttk.Button(r, text="wav ...", command=self.pick).pack(side="left", padx=4)

        r2 = ttk.Frame(self); r2.pack(fill="x", padx=8, pady=4)
        self.e_lab = ttk.Entry(r2, width=36); self.e_lab.pack(side="left")
        ttk.Button(r2, text="labels ...", command=self.pick_lab).pack(side="left", padx=4)
        ttk.Label(r2, text="lang").pack(side="left", padx=(8, 0))
        self.cb_lang = ttk.Combobox(r2, values=langcfg.list_templates(), width=6,
                                    state="readonly")
        self.cb_lang.set("ja"); self.cb_lang.pack(side="left")

        b = ttk.Frame(self); b.pack(fill="x", padx=8, pady=4)
        ttk.Button(b, text="Model", command=self.model).pack(side="left")
        self.b_play = ttk.Button(b, text="Play", command=self.play, state="disabled")
        self.b_play.pack(side="left", padx=6)
        self.b_exp = ttk.Button(b, text="Export ...", command=self.export, state="disabled")
        self.b_exp.pack(side="left")
        self.l_st = ttk.Label(b, text=""); self.l_st.pack(side="left", padx=8)

        self.t_log = tk.Text(self, height=10); self.t_log.pack(fill="both", expand=True, padx=8, pady=6)

    def log(self, msg):
        self.t_log.insert("end", msg + "\n"); self.t_log.see("end")

    def pick(self):
        p = filedialog.askopenfilename(filetypes=[("wav", "*.wav"), ("all", "*.*")])
        if not p: return
        self.e_wav.delete(0, "end"); self.e_wav.insert(0, p)
        self.frames = None; self.y = None
        self.b_play.configure(state="disabled"); self.b_exp.configure(state="disabled")

    def pick_lab(self):
        p = filedialog.askopenfilename(filetypes=[("labels", "*.lab *.txt"), ("all", "*.*")])
        if p:
            self.e_lab.delete(0, "end"); self.e_lab.insert(0, p)

    # ---------------- [model] ----------------
    def model(self):
        p = self.e_wav.get()
        if not p or not os.path.exists(p):
            messagebox.showerror("Model", "pick a wav first"); return
        p_lab = self.e_lab.get()
        segs = read_labels(p_lab) if p_lab and os.path.exists(p_lab) else None
        lang = langcfg.load_lang(langcfg.template_path(self.cb_lang.get() or "ja"))
        self.l_st.configure(text="modeling..."); self.update_idletasks()
        def work():
            try:
                t0 = time.time()
                x = core.read_wav(p, self.cfg)
                fs = self.cfg.sample_rate
                freqs = np.fft.rfftfreq(self.cfg.fft_size, 1 / fs)
                n_dss = len(np.arange(0, min(fs / 2, self.cfg.dss_fmax), self.cfg.dss_step))
                frames, nv, cats = [], 0, {}
                for t_c, spec in stft(x, self.cfg):
                    t = t_c / fs
                    mag_db = 20 * np.log10(np.abs(spec) + 1e-12)
                    # ---- category-driven analysis parameters ----
                    if segs:
                        ph = ph_at(segs, t)
                        known = ph in lang.phonemes()
                        cat = lang.type(ph) if known else \
                              ("silence" if ph in SILENCE_SET else None)
                        sil = cat == "silence"
                        if sil:
                            ratio_min, bands = 1.1, 8            # never voiced, coarse floor
                        elif cat in NOISE_TYPES and not lang.voiced(ph):
                            ratio_min, bands = 1.1, 32           # forced unvoiced, fine noise
                        elif known and lang.voiced(ph):
                            ratio_min, bands = 0.4, self.cfg.uv_bands   # lenient voicing
                        else:
                            ratio_min, bands = self.cfg.voiced_ratio_min, self.cfg.uv_bands
                        cats[cat or "unknown"] = cats.get(cat or "unknown", 0) + 1
                    else:
                        ratio_min, bands = self.cfg.voiced_ratio_min, self.cfg.uv_bands
                    peaks = detect_peaks(spec, freqs, self.cfg)
                    f0, ratio, mask = estimate_pitch(peaks, freqs, self.cfg)
                    voiced = bool(f0 > 0 and ratio >= ratio_min)
                    if voiced and len(peaks) >= 3:
                        pf = np.array([q[0] for q in peaks])
                        pdb = np.array([q[1] for q in peaks])
                        # ---- authentic pitch: no quantization / candidate sticking ----
                        # f0 = weighted average of normalized harmonic frequencies
                        # (AES-111 eq. 6): tracks vibrato & portamento exactly
                        ks_r = np.round(pf[mask] / f0)
                        good = ks_r >= 1
                        if good.any():
                            w = 10 ** (pdb[mask][good] / 20.)
                            f0 = float(np.sum((pf[mask][good] / ks_r[good]) * w) / np.sum(w))
                        hf = np.column_stack([pf[mask], pdb[mask]])
                    else:
                        voiced, hf = False, np.zeros((0, 2))
                    if voiced and len(hf) >= 3:
                        m = model_frame(hf[:, 0], hf[:, 1], f0, self.cfg, fs)
                        frames.append(dict(voiced=True, f0=f0,
                                           src=np.array([m["gain"], m["slope"], m["sdepth"]], np.float32),
                                           res=[tuple(m["src_res"])] + [tuple(v) for v in m["vt"]],
                                           dss=m["dss"],
                                           uv=noise_floor_env(spec, freqs, f0, self.cfg)))
                    else:
                        frames.append(dict(voiced=False, f0=0.0,
                                           src=np.zeros(3, np.float32), res=[],
                                           dss=np.zeros(n_dss, np.float32),
                                           uv=env_bands(mag_db, freqs, bands)))
                self.frames = frames; self.y = None
                dt = time.time() - t0
                msg = f"modeled {len(frames)} frames ({nv} voiced) in {dt:.1f}s"
                if segs:
                    msg += " | categories: " + ", ".join(f"{k}={v}" for k, v in sorted(cats.items()))
                self.after(0, lambda: (self.log(msg),
                                       self.l_st.configure(text="modeled"),
                                       self.b_play.configure(state="normal"),
                                       self.b_exp.configure(state="normal")))
            except Exception:
                self.after(0, lambda: (self.log(traceback.format_exc()),
                                       self.l_st.configure(text="error")))
        threading.Thread(target=work, daemon=True).start()

    # ---------------- render / [play] / [export] ----------------
    def render(self):
        if self.frames is None:
            messagebox.showerror("Render", "model first"); return None
        t0 = time.time()
        y = synth_frames(self.frames, self.cfg)
        y = y * 0.8 / (np.abs(y).max() or 1.)
        self.log(f"rendered {len(y)/self.cfg.sample_rate:.2f}s in {time.time()-t0:.1f}s")
        return y

    def play(self):
        if self.y is None: self.y = self.render()
        if self.y is None: return
        p = os.path.join(tempfile.gettempdir(), "epr_test.wav")
        wavfile.write(p, self.cfg.sample_rate, (self.y * 32767).astype(np.int16))
        try: subprocess.Popen(["afplay", p])
        except Exception:
            try: os.startfile(p)
            except Exception: pass

    def export(self):
        if self.y is None: self.y = self.render()
        if self.y is None: return
        p = filedialog.asksaveasfilename(defaultextension=".wav", initialfile="epr_model.wav")
        if p:
            wavfile.write(p, self.cfg.sample_rate, (self.y * 32767).astype(np.int16))
            self.log(f"exported {os.path.basename(p)}")

def main():
    App().mainloop()

if __name__ == "__main__":
    main()