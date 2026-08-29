# =============================================================================
# g2p_gui.py — Simple GUI for testing OpenUtau g2p packs and exporting phonemes.
#
# Features:
#   * Auto-scans svs/g2p/ for unzipped pack folders
#   * Multi-line word entry
#   * Shows dict vs model results (green / orange / red)
#   * With convert.txt: three tab-separated columns (word | g2p | engine)
#   * Export space-separated phoneme lists (engine format when convert.txt
#     is present, g2p format otherwise)
# =============================================================================
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .g2p import G2pRegistry
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

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("G2P Tester")
        self.geometry("860x620")
        self.configure(bg="#2b2b2b")

        # Scan for packs
        g2p_dir = os.path.join(_base_path(), "g2p")
        os.makedirs(g2p_dir, exist_ok=True)
        self.registry = G2pRegistry([g2p_dir])
        self.packs = self.registry.list()

        if not self.packs:
            messagebox.showwarning(
                "No Packs",
                f"No unzipped G2P folders found in:\n{g2p_dir}\n\n"
                "Place unzipped OpenUtau g2p packs there (e.g. g2p-en-us/) "
                "and restart.")
            self.g2p = None
        else:
            self.g2p = self.packs[0]

        self._build_ui()
        self._update_info()

    def _build_ui(self):
        # ---- Top bar: pack selector + info ----
        top = tk.Frame(self, bg="#2b2b2b")
        top.pack(fill="x", padx=10, pady=8)

        tk.Label(top, text="Pack:", bg="#2b2b2b", fg="white",
                 font=("Helvetica", 10, "bold")).pack(side="left")

        self.cb_pack = ttk.Combobox(top, state="readonly", width=40)
        self.cb_pack["values"] = [f"{p.id} v{p.version}" for p in self.packs]
        if self.packs:
            self.cb_pack.current(0)
        self.cb_pack.pack(side="left", padx=8)
        self.cb_pack.bind("<<ComboboxSelected>>", self._on_pack_change)

        self.l_info = tk.Label(top, text="", bg="#2b2b2b", fg="#cccccc",
                               font=("Helvetica", 9), anchor="w")
        self.l_info.pack(side="left", padx=12, fill="x", expand=True)

        # ---- Middle: word entry + results ----
        mid = tk.Frame(self, bg="#2b2b2b")
        mid.pack(fill="both", expand=True, padx=10, pady=4)

        left = tk.Frame(mid, bg="#2b2b2b")
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        tk.Label(left, text="Words (one per line or space-separated):",
                 bg="#2b2b2b", fg="white", font=("Helvetica", 10, "bold"),
                 anchor="w").pack(fill="x")

        self.t_input = tk.Text(left, height=12, bg="#1b1b1b", fg="#f2f2f2",
                               insertbackground="white", font=("Courier", 11),
                               highlightthickness=1, highlightbackground="#4a4a4a")
        self.t_input.pack(fill="both", expand=True, pady=4)

        right = tk.Frame(mid, bg="#2b2b2b")
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        tk.Label(right, text="Results:", bg="#2b2b2b", fg="white",
                 font=("Helvetica", 10, "bold"), anchor="w").pack(fill="x")

        self.t_output = tk.Text(right, height=12, bg="#1b1b1b", fg="#f2f2f2",
                                font=("Courier", 11), state="disabled",
                                highlightthickness=1, highlightbackground="#4a4a4a")
        self.t_output.pack(fill="both", expand=True, pady=4)

        # ---- Bottom: actions ----
        bot = tk.Frame(self, bg="#2b2b2b")
        bot.pack(fill="x", padx=10, pady=8)

        tk.Button(bot, text="Convert", command=self.convert,
                  bg="#f59a23", fg="#111111", font=("Helvetica", 10, "bold"),
                  padx=20, pady=6).pack(side="left")

        tk.Button(bot, text="Export Phonemes", command=self.export,
                  bg="#2a2a2a", fg="#f2f2f2", font=("Helvetica", 10, "bold"),
                  padx=20, pady=6).pack(side="left", padx=12)

        tk.Button(bot, text="Clear", command=self.clear,
                  bg="#2a2a2a", fg="#f2f2f2", font=("Helvetica", 10, "bold"),
                  padx=20, pady=6).pack(side="left")

        self.l_status = tk.Label(bot, text="", bg="#2b2b2b", fg="#9a9a9a",
                                 font=("Helvetica", 9))
        self.l_status.pack(side="right")

    def _on_pack_change(self, ev=None):
        idx = self.cb_pack.current()
        if idx >= 0:
            self.g2p = self.packs[idx]
            self._update_info()

    def _update_info(self):
        if self.g2p is None:
            self.l_info.configure(text="(no pack loaded)")
            return
        info = self.g2p.info()
        model_str = (f"ONNX ({info['onnx_name']})" if info["has_model"]
                     else f"dict-only ({info['load_note']})")
        conv = "convert.txt" if self.g2p.convert else "no convert"
        self.l_info.configure(
            text=f"{info['dict_size']} words, {info['phonemes']} phonemes | "
                 f"{model_str} | {conv}")

    def convert(self):
        if self.g2p is None:
            messagebox.showerror("Error", "No G2P pack loaded")
            return
        text = self.t_input.get("1.0", "end").strip()
        if not text:
            return
        results = self.g2p.lyrics(" ".join(text.split()))
        self.t_output.configure(state="normal")
        self.t_output.delete("1.0", "end")
        for word, phs, source in results:
            if phs is None:
                self.t_output.insert("end", f"✗ {word}\t{source}\n")
                tname = "fail"
            else:
                tag = "✓" if source == "dict" else "⚠"
                eng = self.g2p.to_engine(phs)
                if eng is not None:
                    # three tab-separated entries: word | g2p | engine
                    self.t_output.insert(
                        "end", f"{tag} {word}\t{' '.join(phs)}\t{' '.join(eng)}\n")
                else:
                    # no convert.txt: word + g2p output only, as before
                    self.t_output.insert("end", f"{tag} {word} → {' '.join(phs)}\n")
                tname = source
            ln = int(self.t_output.index("end-1c").split(".")[0])
            self.t_output.tag_add(tname, f"{ln}.0", f"{ln}.end")
        self.t_output.tag_configure("dict", foreground="#4caf50")
        self.t_output.tag_configure("model", foreground="#ff9800")
        self.t_output.tag_configure("fail", foreground="#ff5252")
        self.t_output.configure(state="disabled")
        n_ok = sum(1 for _w, p, _s in results if p)
        self.l_status.configure(text=f"{n_ok}/{len(results)} converted")

    def export(self):
        if self.g2p is None:
            messagebox.showerror("Error", "No G2P pack loaded")
            return
        text = self.t_input.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Export", "Enter some words first")
            return
        results = [r for r in self.g2p.lyrics(" ".join(text.split())) if r[1]]
        if not results:
            messagebox.showwarning("Export", "No valid conversions")
            return
        p = filedialog.asksaveasfilename(
            defaultextension=".txt", initialfile="phonemes.txt",
            filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not p:
            return
        with open(p, "w", encoding="utf-8") as f:
            for word, phs, source in results:
                eng = self.g2p.to_engine(phs)
                f.write((" ".join(eng) if eng is not None else " ".join(phs)) + "\n")
        self.l_status.configure(text=f"Exported to {os.path.basename(p)}")
        messagebox.showinfo("Export", f"Exported {len(results)} word(s) to:\n{p}")

    def clear(self):
        self.t_input.delete("1.0", "end")
        self.t_output.configure(state="normal")
        self.t_output.delete("1.0", "end")
        self.t_output.configure(state="disabled")
        self.l_status.configure(text="")

def main():
    App().mainloop()

if __name__ == "__main__":
    main()
