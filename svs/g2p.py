# =============================================================================
# g2p.py — OpenUtau g2p reader for unzipped packs.
#
# Pack folder (svs/g2p/<pack-name>/) contains:
#   dict.txt    : Sphinx dictionary "WORD PH1 PH2 ...", ";;;" comments
#   phones.txt  : phoneme symbols in model order (first token of each line)
#   *.onnx      : graph (any name). Two shapes supported:
#                 * merged loop graph: input "src" only -> full decode
#                 * prefix decoder: inputs src/tgt/t -> autoregressive loop
# optionally:
#   graphemes.txt : grapheme symbols in model order (overrides the default)
#   convert.txt   : g2p -> engine phoneme map (one conversion per line)
#
# Default grapheme table = <pad> <unk> <bos> <eos> ' - a..z (repo convention,
# 32 rows); input words are lowercased, unknown chars -> <unk>.
# Policy same as OpenUtau: dictionary first, model only out-of-dictionary.
# Stress/accent digits are culled from all phoneme symbols.
# =============================================================================
import os, re
import numpy as np

SPECIALS = ["<pad>", "<unk>", "<bos>", "<eos>"]
PAD, UNK, BOS, EOS = 0, 1, 2, 3

def _read_list(path):
    try:
        toks = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip().strip("'\"")
                if line and not line.startswith("#"):
                    toks.extend(line.split() if " " in line else [line])
        return toks or None
    except Exception:
        return None

class G2pPack:
    def __init__(self, path):
        self.path = path
        self.id = os.path.basename(path)
        self.version = ""
        self.sess = None
        self.onnx_name = None
        self.load_note = ""
        self.last_error = ""

        # ---- phonemes: model order, specials prepended ----
        toks = []
        with open(os.path.join(path, "phones.txt"), encoding="utf-8") as f:
            rows = []
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                rows.append(line.split())
        if len(rows) == 1:
            toks = rows[0]
        else:
            toks = [r[0] for r in rows if r]
        toks = [t.strip("'\"") for t in toks if t.strip("'\"") not in SPECIALS]
        self.phonemes = SPECIALS + toks
        self.p2i = {p: i for i, p in enumerate(self.phonemes)}

        # ---- dictionary (stress digits dropped) ----
        self.dict = {}
        with open(os.path.join(path, "dict.txt"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith((";;;", "#")): continue
                parts = line.split()
                if len(parts) < 2: continue
                out = [self._sym(p) for p in parts[1:]]
                ded = [p for i, p in enumerate(out) if i == 0 or p != out[i - 1]]
                if ded: self.dict[parts[0]] = ded

        # ---- graphemes: optional file, else repo convention (' and - ALWAYS
        #      occupy slots 4/5, or the trained letter indices shift by 2 and
        #      the model reads garbage)
        gl = None
        for cand in ("graphemes.txt", "graphemes", "letters.txt", "letters"):
            p = os.path.join(path, cand)
            if os.path.exists(p):
                gl = _read_list(p)
                if gl: break
        if gl is None:
            gl = ["'", "-"] + [chr(c) for c in range(97, 123)]
        self.graphemes = SPECIALS + [c for c in gl if c not in SPECIALS]
        self.g2i = {c: i for i, c in enumerate(self.graphemes)}

        # ---- optional g2p -> engine phoneme map (convert.txt) ----
        self.convert = {}
        cvp = os.path.join(path, "convert.txt")
        if os.path.exists(cvp):
            with open(cvp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"): continue
                    parts = line.split()
                    if len(parts) >= 2:
                        self.convert[parts[0]] = " ".join(parts[1:])

        # ---- model: any .onnx in the folder ----
        cands = sorted(f for f in os.listdir(path) if f.endswith(".onnx"))
        onnx_path = os.path.join(path, cands[0]) if cands else None
        if onnx_path:
            try:
                import onnxruntime as ort
                self.sess = ort.InferenceSession(
                    onnx_path, providers=["CPUExecutionProvider"])
                self.inputs = {i.name: i for i in self.sess.get_inputs()}
                self.out_name = self.sess.get_outputs()[0].name
                self.onnx_name = cands[0]
                self.load_note = ("model ok" if set(self.inputs) == {"src"}
                                  else "model ok (prefix decoder)")
            except ImportError as e:
                self.sess = None
                self.load_note = f"onnxruntime import failed: {e}"
            except Exception as e:
                self.sess = None
                self.load_note = f"onnx load failed: {e}"
        else:
            self.load_note = "no .onnx file in folder"

    def _sym(self, p):
        """Engine is stressless: cull trailing accent/stress digits."""
        return re.sub(r"\d+$", "", p)

    def _conv(self, s, mode):
        if mode == "to_lower": return s.lower()
        if mode == "to_upper": return s.upper()
        return s

    def _out(self, p):
        p = self._conv(p, self.cg_out)
        if self.rm_stress: p = re.sub(r"\d+$", "", p)
        return p

    def encode(self, word):
        w = word.lower()
        return np.array([[self.g2i.get(ch, UNK) for ch in w]], np.int32)

    def _phs_of(self, idxs):
        return [self._sym(self.phonemes[i]) for i in idxs if 4 <= i < len(self.phonemes)]

    def _step(self, src, tgt_list, t_val):
        feed = {"src": src, "tgt": np.array([tgt_list], np.int32),
                "t": np.array([t_val], np.int32)}
        return np.asarray(self.sess.run([self.out_name], feed)[0])

    def _next_of(self, pred):
        a = np.asarray(pred)
        if a.size and a.shape[-1] >= 4:
            return int(np.argmax(a.reshape(-1, a.shape[-1])[-1]))
        return int(a.reshape(-1)[-1])

    def _greedy(self, src, mode):
        BOS, EOS = 2, 3
        out = []
        tgt = [BOS]
        if mode == "rnnt":
            T = src.shape[1]
            t = 0; same = 0; guard = 0
            while t < T and guard < 16 * T + 64:
                guard += 1
                nxt = self._next_of(self._step(src, tgt, t))
                if nxt == EOS: break
                if nxt == BOS:
                    t += 1; same = 0; continue
                out.append(nxt); tgt.append(nxt)
                same += 1
                if same > 4:
                    t += 1; same = 0
        else:
            for t in range(64):
                nxt = self._next_of(self._step(src, tgt, t))
                if nxt == EOS: break
                if nxt >= 4:
                    out.append(nxt); tgt.append(nxt)
        return self._phs_of(out)

    def infer(self, word):
        if self.sess is None: return None
        try:
            src = self.encode(word)
            if set(self.inputs) == {"src"}:
                out = np.asarray(self.sess.run([self.out_name], {"src": src})[0])
                phs = self._phs_of(out[0])
            else:
                modes = ["rnnt", "pos"]
                if getattr(self, "_g2p_mode", None) in modes:
                    modes.insert(0, self._g2p_mode)
                phs = []
                for m in modes:
                    phs = self._greedy(src, m)
                    if phs:
                        self._g2p_mode = m
                        break
            if phs:
                self.last_error = ""
                return phs
            self.last_error = "model produced no phonemes"
            return None
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            print(f"[G2P] infer failed for {word!r}: {self.last_error}")
            return None

    def word(self, word):
        hit = self.dict.get(word) or self.dict.get(word.lower())
        if hit: return list(hit)
        return self.infer(word)

    def lyrics(self, text):
        out = []
        for w in text.split():
            phs = self.word(w)
            if phs:
                src = "dict" if (w in self.dict or w.lower() in self.dict) else "model"
            else:
                src = f"model: {self.last_error}" if self.last_error else \
                      (self.load_note or "no model")
            out.append((w, phs, src))
        return out

    def to_engine(self, phs):
        if not self.convert: return None
        out = []
        for p in phs:
            out.extend(self.convert.get(p, p).split())
        return out

    def info(self):
        return dict(id=self.id, graphemes=len(self.graphemes),
                    phonemes=len(self.phonemes), dict_size=len(self.dict),
                    has_model=self.sess is not None, onnx_name=self.onnx_name,
                    load_note=self.load_note)

class G2pRegistry:
    def __init__(self, dirs):
        self.packs = []
        for d in dirs:
            if not os.path.isdir(d): continue
            for f in sorted(os.listdir(d)):
                sub = os.path.join(d, f)
                if os.path.isdir(sub) and \
                        os.path.exists(os.path.join(sub, "dict.txt")):
                    try:
                        self.packs.append(G2pPack(sub))
                    except Exception as e:
                        print(f"failed to load pack '{f}': {e}")

    def for_lang(self, code):
        """Select pack by language code.
        1. Exact match (case-sensitive) on the full code (e.g. 'en-arpa' -> 'g2p-en-arpa').
        2. Exact match (case-insensitive).
        3. Prefix match on the first segment (e.g. 'en')."""
        if not code:
            return self.packs[0] if self.packs else None
            
        # 1. Exact case-sensitive match
        for p in self.packs:
            if p.id.endswith(code) or p.id == code:
                return p
                
        # 2. Exact case-insensitive match
        target = code.lower()
        for p in self.packs:
            if p.id.lower().endswith(target) or p.id.lower() == target:
                return p
                
        # 3. Prefix match (first segment)
        pre = target.split("-")[0]
        for p in self.packs:
            if p.id.lower().startswith(pre) or pre in p.id.lower():
                return p
                
        return self.packs[0] if self.packs else None

    def list(self):
        return list(self.packs)