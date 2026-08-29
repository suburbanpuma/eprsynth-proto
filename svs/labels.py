from dataclasses import dataclass

@dataclass
class Label:
    """Articulation (p2 set, 7 fields) or sustain (p2 None, 5 fields). Times in ms."""
    p1: str
    p2: object                      # str | None
    start: float; m_p1: float; m_p2: object; m_trans: float; end: float

    @property
    def sustain(self):
        return self.p2 is None

    def offsets_ms(self):
        d = dict(p1=self.m_p1 - self.start, trans=self.m_trans - self.start,
                 end=self.end - self.start)
        if not self.sustain:
            d["p2"] = self.m_p2 - self.start
        return d

    def offsets(self):                              # seconds (for build_unit)
        return {k: v / 1000. for k, v in self.offsets_ms().items()}

    def sec(self):
        return Label(self.p1, self.p2, self.start / 1000., self.m_p1 / 1000.,
                     self.m_p2 / 1000. if self.m_p2 is not None else None,
                     self.m_trans / 1000., self.end / 1000.)

    def line(self):
        if self.sustain:
            return (f"{self.p1} {self.start:.1f} {self.m_p1:.1f} "
                    f"{self.m_trans:.1f} {self.end:.1f}")
        return (f"{self.p1} {self.p2} {self.start:.1f} {self.m_p1:.1f} "
                f"{self.m_p2:.1f} {self.m_trans:.1f} {self.end:.1f}")

def parse_labels(path, phonemes, duration_ms):
    labels = []
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.split("#")[0].strip()
            if not line:
                continue
            tok = line.split()
            if len(tok) not in (5, 7):
                raise ValueError(f"label line {ln}: expected 7 (articulation) "
                                 f"or 5 (sustain) fields")
            p1 = tok[0]
            p2 = tok[1] if len(tok) == 7 else None
            for p in (p1, p2):
                if p is not None and p not in phonemes:
                    raise ValueError(f"label line {ln}: unknown phoneme '{p}'")
            t = [float(x) for x in (tok[2:] if p2 is not None else tok[1:])]
            if t[0] < 0.:
                raise ValueError(f"label line {ln}: negative start ({t[0]:.1f} ms)")
            inv = next((i for i in range(1, len(t)) if t[i] < t[i - 1]), None)
            if inv is not None:
                raise ValueError(f"label line {ln}: markers not monotonic "
                                 f"({t[inv - 1]:.1f} -> {t[inv]:.1f} ms)")
            if t[0] >= duration_ms - 1e-6:
                continue                        # label entirely past the take
            if t[-1] > duration_ms + 1e-6:
                t = [min(x, duration_ms) for x in t]   # END beyond wav: clamp
            if p2 is None:
                labels.append(Label(p1, None, t[0], t[1], None, t[2], t[3]))
            else:
                labels.append(Label(p1, p2, *t))
    return labels

def parse_batchlab(path, phonemes):
    """batchlab: <file> p1 p2 START P1 P2 TRANS END  or  <file> p1 START P1 TRANS END (ms)."""
    out = []
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.split("#")[0].strip()
            if not line:
                continue
            tok = line.split()
            if len(tok) not in (6, 8):
                raise ValueError(f"batchlab line {ln}: expected 8 (articulation) "
                                 f"or 6 (sustain) fields")
            fn = tok[0]
            if len(tok) == 8:
                p1, p2, raw = tok[1], tok[2], tok[3:]
                if p1 not in phonemes or p2 not in phonemes:
                    raise ValueError(f"batchlab line {ln}: unknown phoneme")
                t = [float(x) for x in raw]
                if not (t[0] >= 0 and all(a <= b for a, b in zip(t, t[1:]))):
                    raise ValueError(f"batchlab line {ln}: ms markers not monotonic")
                out.append((fn, Label(p1, p2, *t)))
            else:
                p1, raw = tok[1], tok[2:]
                if p1 not in phonemes:
                    raise ValueError(f"batchlab line {ln}: unknown phoneme")
                t = [float(x) for x in raw]
                if not (t[0] >= 0 and all(a <= b for a, b in zip(t, t[1:]))):
                    raise ValueError(f"batchlab line {ln}: ms markers not monotonic")
                out.append((fn, Label(p1, None, t[0], t[1], None, t[2], t[3])))
    return out