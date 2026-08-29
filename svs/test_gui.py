import os, subprocess, tempfile, threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import traceback
import numpy as np
from scipy.io import wavfile

from . import synth

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AURORA Core Concatenator")
        self.geometry("560x560")
        self.db = None; self.y = None; self.tmp = None
        r = ttk.Frame(self); r.pack(fill="x", padx=8, pady=6)
        ttk.Button(r, text="Open DB ...", command=self.open_db).pack(side="left")
        self.l_db = ttk.Label(r, text="(no database)"); self.l_db.pack(side="left", padx=8)
        ttk.Button(r, text="+ row", command=self.add_row).pack(side="right")

        t = ttk.LabelFrame(self, text="transitions"); t.pack(fill="x", padx=8, pady=4)
        ttk.Label(t, text="frames K").grid(row=0, column=0, padx=4)
        self.e_k = ttk.Entry(t, width=4); self.e_k.insert(0, "8"); self.e_k.grid(row=0, column=1)
        ttk.Label(t, text="SSIntp").grid(row=0, column=2, padx=4)
        self.e_ss = ttk.Entry(t, width=4); self.e_ss.insert(0, "1.0"); self.e_ss.grid(row=0, column=3)
        ttk.Label(t, text="xfade ms").grid(row=0, column=4, padx=4)
        self.e_xf = ttk.Entry(t, width=5); self.e_xf.insert(0, "15"); self.e_xf.grid(row=0, column=5)
        self.v_pa = tk.BooleanVar(value=True)
        ttk.Checkbutton(t, text="phase align", variable=self.v_pa).grid(row=0, column=6, padx=6)

        self.canvas = tk.Canvas(self)
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side="right", fill="y"); self.canvas.pack(fill="both", expand=True)
        self.body = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.rows = []

        b = ttk.Frame(self); b.pack(fill="x", padx=8, pady=6)
        ttk.Button(b, text="Render", command=self.render).pack(side="left")
        self.b_play = ttk.Button(b, text="Play", command=self.do_play, state="disabled")
        self.b_play.pack(side="left", padx=4)
        self.b_save = ttk.Button(b, text="Save ...", command=self.do_save, state="disabled")
        self.b_save.pack(side="left")
        self.l_st = ttk.Label(b, text=""); self.l_st.pack(side="left", padx=8)
        for _ in range(3): self.add_row()

    def open_db(self):
        p = filedialog.askdirectory()
        if not p: return
        try: self.db = synth.DB(p)
        except Exception as e:
            messagebox.showerror("DB", str(e)); return
        self.l_db.configure(text=os.path.basename(p) +
                            "  groups: " + ", ".join(self.db.groups))

    def add_row(self):
        f = ttk.Frame(self.body); f.pack(fill="x", padx=4, pady=2)
        e_pair = ttk.Entry(f, width=10); e_pair.insert(0, "k a")
        e_dur = ttk.Entry(f, width=8); e_dur.insert(0, "600")
        e_pit = ttk.Entry(f, width=6); e_pit.insert(0, "A3")
        e_pair.pack(side="left"); e_dur.pack(side="left", padx=4); e_pit.pack(side="left")
        ttk.Label(f, text="phoneme(s) / ms / pitch").pack(side="left", padx=4)
        ttk.Button(f, text="x", command=lambda: (self.rows.remove(w), f.destroy())).pack(side="right")
        w = dict(pair=e_pair, dur=e_dur, pit=e_pit)
        self.rows.append(w)

    def _opts(self):
        return dict(trans_frames=int(self.e_k.get()), ss_intp=float(self.e_ss.get()),
                    xfade_ms=float(self.e_xf.get()), phase_align=self.v_pa.get())

    def render(self):
        if not self.db: messagebox.showerror("Render", "open a database first"); return
        rows = []
        for w in self.rows:
            tok = w["pair"].get().split()
            if len(tok) not in (1, 2): continue
            rows.append(dict(pair=" ".join(tok), dur=float(w["dur"].get()),
                             midi=synth.note_to_midi(w["pit"].get())))
        if not rows: return
        self.l_st.configure(text="rendering..."); self.update_idletasks()
        def work():
            try:
                y = synth.render_rows(self.db, rows, opts=self._opts(), log=print)
                self.y = y
                self.after(0, lambda: (self.l_st.configure(
                    text=f"rendered {len(y)/self.db.cfg.sample_rate:.2f}s"),
                    self.b_play.configure(state="normal"),
                    self.b_save.configure(state="normal")))
            except Exception:
                msg = traceback.format_exc()      # capture NOW, before except exits
                print(msg)
                self.after(0, lambda: (self.l_st.configure(text="error"),
                                       messagebox.showerror("Render", msg)))
        threading.Thread(target=work, daemon=True).start()

    def _write_tmp(self):
        self.tmp = os.path.join(tempfile.gettempdir(), "svs_test.wav")
        wavfile.write(self.tmp, self.db.cfg.sample_rate, (self.y * 32767).astype(np.int16))
        return self.tmp

    def do_play(self):
        if self.y is None: return
        p = self._write_tmp()
        try: subprocess.Popen(["afplay", p])
        except Exception:
            try: os.startfile(p)
            except Exception: pass

    def do_save(self):
        if self.y is None: return
        p = filedialog.asksaveasfilename(defaultextension=".wav", initialfile="test.wav")
        if p:
            wavfile.write(p, self.db.cfg.sample_rate, (self.y * 32767).astype(np.int16))
            self.l_st.configure(text=f"saved {os.path.basename(p)}")

def main():
    App().mainloop()

if __name__ == "__main__":
    main()