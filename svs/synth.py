# =============================================================================
# synth.py — Concatenative EpR engine with SPP rendering, modeled voiced
# residual, and global + curve + baked per-unit expression parameters.
#
# Per-frame priority: baked unit arrays (f0r/gain/voi/bre/gen/bri/ten/form,
# f1..f3 warps) > drawn pencil curves > global cfg scalars. Portamento
# transitions (cfg.pt_trans) reshape the base f0 first (applied before the
# pencil so strokes/vibrato layer on top); vibratos multiply last.
# MODULATION flattens row steady regions in row_frames; at 1.0 the whole row
# (diphones included) locks to the exact note pitch. Missing units fall back
# to the nearest pitch group; units missing in ALL groups render timed
# silence so the song keeps its timing. Fast passages time-compress units
# with SPP phase rebasing; recorded-f0 outliers are median-clamped per row so
# the transposition ratio can't spike at transitions (and ratio is clamped to
# +-1 octave as a safety net).
# =============================================================================
import json, os
import numpy as np

from . import langcfg, manifest
from .config import AnalysisConfig
from .epr import epr_ideal_db

DEFAULT_OPTS = dict(trans_frames=8, ss_intp=1.0, phase_align=True, xfade_ms=15.0)

def note_to_midi(s):
    s = s.strip()
    if s.isdigit(): return int(s)
    names = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    n, i, acc = names[s[0].upper()], 1, 0
    while i < len(s) and s[i] in "#b":
        acc += 1 if s[i] == "#" else -1; i += 1
    return 12 * (int(s[i:]) + 1) + n + acc

def midi_to_hz(m): return 440.0 * 2 ** ((m - 69) / 12.0)

class DB:
    def __init__(self, path):
        self.path = path; self.cfg = AnalysisConfig()
        self.lang = langcfg.lang_for_db(path)
        cp = manifest.load_manifest(path)
        self.groups = sorted((g.strip() for g in cp["pitchgroups.base"]["groups"].split(",")),
                             key=note_to_midi)
        self._idx = {}
        for g in self.groups:
            with open(os.path.join(path, "base", g, "index.json")) as f:
                self._idx[g] = json.load(f)
        self._cache = {}
        self._vrc = {}

    def vr_for(self, midi):
        """Per-group voiced residual model, nearest-group fallback (keeps rho~1)."""
        g = self.group_for(midi)
        if g not in self._vrc:
            self._vrc[g] = None
            for gg in sorted(self.groups, key=lambda x: abs(note_to_midi(x) - midi)):
                p = os.path.join(self.path, "base", gg, "vr.npz")
                if os.path.exists(p):
                    try:
                        z = np.load(p)
                        self._vrc[g] = dict(flat=z["flat"], rec_pitch=float(z["rec_pitch"]),
                                            vr_diff=z["vr_diff"], centers=z["centers"])
                    except Exception:
                        pass
                    break
        return self._vrc[g]

    def ptype(self, ph):
        return self.lang.type(ph)

    def group_for(self, midi):
        """Floor rule: highest group not above the target pitch."""
        sel = self.groups[0]
        for g in self.groups:
            if note_to_midi(g) <= midi: sel = g
        return sel

    def _load(self, g, rel):
        key = (g, rel)
        if key not in self._cache:
            self._cache[key] = np.load(os.path.join(self.path, "base", g, rel))
        return self._cache[key]

    def unit(self, pair, midi):
        """Diphone arrays; falls back to the nearest pitch group that has it."""
        g = self.group_for(midi); meta = self._idx[g]["units"].get(pair)
        if meta is None:
            best = None
            for gg in self.groups:
                m2 = self._idx[gg]["units"].get(pair)
                if m2 is not None:
                    d = abs(note_to_midi(gg) - midi)
                    if best is None or d < best[0]: best = (d, gg, m2)
            if best is None: raise KeyError(f"diphone '{pair}' not in any group")
            g, meta = best[1], best[2]
        return self._load(g, meta["file"]), meta, g

    def steady(self, ph, midi):
        """(arrays, rec_pitch, loop_i0, loop_i1); loop = P1..TRANS."""
        g = self.group_for(midi)
        meta = self._idx[g]["steady"].get(ph)
        if meta is None:                      # fallback: nearest group that has it
            best = None
            for gg in self.groups:
                m2 = self._idx[gg]["steady"].get(ph)
                if m2 is not None:
                    d = abs(note_to_midi(gg) - midi)
                    if best is None or d < best[0]: best = (d, gg, m2)
            if best is None: return None, None, 0, 1
            g, meta = best[1], best[2]
        arr = self._load(g, meta["file"]); t = arr["t"]
        mk = meta.get("markers")
        if mk:
            i0 = int(np.searchsorted(t, mk["p1"] / 1000.))
            i1 = int(np.searchsorted(t, mk["trans"] / 1000.))
        else:
            i0, i1 = 0, len(t)
        i1 = max(i1, i0 + 1)
        f0s = arr["f0"][arr["f0"] > 0]
        return arr, (float(np.median(f0s)) if len(f0s) else 220.0), i0, i1

def _frame(arr, i, transp):
    """Extract one synthesis frame from a unit array at index i, transposed.
    Baked per-unit tweak arrays (from the dev GUI's BAKE) override defaults."""
    v = bool(arr["voiced"][i])
    res = [tuple(arr["src_res"][i])] + [tuple(x) for x in arr["vt"][i] if x[0] > 0]
    # baked formant edits -> spectral warp (moves the DSS with the formants)
    L = [float(r[0]) for r in res[1:4]]
    R = [float(arr[kk][i]) if kk in arr.files else L[j]
         for j, kk in enumerate(("f1", "f2", "f3")) if j < len(L)]
    warp = None
    if len(L) >= 2 and any(abs(a - b) > 1. for a, b in zip(L, R)):
        Lpts = np.array([0.] + L + [6000.])
        Rpts = np.array([0.] + R + [6000.])
        for j in range(1, len(Rpts)):
            Rpts[j] = max(Rpts[j], Rpts[j - 1] + 50.)   # keep monotonic
        warp = (1.0, (Lpts, Rpts, Lpts, np.zeros_like(Lpts)))
    fr = dict(voiced=v, f0=float(arr["f0"][i]) * transp if v else 0.0,
              f0r=float(arr["f0"][i]),                # recorded f0 -> ratio ref
              src=arr["src"][i], res=res, dss=arr["dss"][i], uv=arr["uv"][i])
    if warp is not None: fr["warp"] = warp
    if "f0r" in arr.files: fr["f0r"] = float(arr["f0r"][i])   # baked pitch keeps ratio
    for kk in ("gain", "voi", "bre", "gen", "bri", "ten", "form"):
        if kk in arr.files:
            fr[kk] = float(arr[kk][i])
    try:
        o = arr["spp_off"]                            # SPP hi-fi layer
        fr["spp"] = arr["spp_data"][o[i]:o[i + 1]]
    except KeyError:
        fr["spp"] = None
    return fr

def _phase_model(fh, res):
    """Each resonance adds a linear pi shift across its bandwidth (ICMC §3.2)."""
    th = np.zeros_like(fh)
    for F, Bw, A in res:
        th += np.pi * np.clip((fh - (F - Bw)) / (2 * Bw), 0, 1)
    return th

def _env(fr, f, cfg, vt_scale=1.0):
    """EpR envelope (dB). vt_scale scales only the VOCAL-TRACT part (VT
    resonances + DSS frequency axis) = true formant shift (GENDER x G-SHIFT);
    the source curve and source resonance stay put. 1.0 = neutral."""
    res = fr["res"]
    if vt_scale != 1.0:
        res = [res[0]] + [(F * vt_scale, Bw, A) for F, Bw, A in res[1:]]
    m = epr_ideal_db(f, fr["src"][0], fr["src"][1], fr["src"][2], res, cfg.sample_rate)
    return m + np.interp(f / vt_scale,
                         np.arange(len(fr["dss"])) * cfg.dss_step, fr["dss"])

def _anchors(fr):
    """EpR anchor points (F0,F1,F2,F3) for spectral morphing (SMAC-03 §6.2)."""
    pts = [fr["f0"]] + [float(F) for F, Bw, A in fr["res"][1:] if F > 0][:3]
    pts = [p for p in pts if p > 0] or [300.]
    while len(pts) < 4: pts.append(pts[-1] + 600.)
    out = [pts[0]]
    for p in pts[1:]: out.append(max(p, out[-1] + 100.))
    return np.array(out)

def glottal_template(fs, dur_s=0.004):
    """Rosenberg-like glottal pulse (all-pass phase shaper for the comb)."""
    n = max(8, int(dur_s * fs))
    t = np.arange(n) / (n - 1.)
    tp, tn = 0.45, 0.35
    g = np.zeros(n)
    a = t < tp
    g[a] = 0.5 * (1 - np.cos(np.pi * t[a] / tp))
    b = (t >= tp) & (t < tp + tn)
    g[b] = 0.5 * (1 + np.cos(np.pi * (t[b] - tp) / tn))
    return g / (g.max() or 1.)

def synth_frames(frames, cfg):
    fs = cfg.sample_rate; N = cfg.fft_size; hop = int(cfg.hop_s * fs)
    win = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N) / N)
    margin = N
    total = margin + len(frames) * hop + N + hop
    out = np.zeros(total); winsum = np.zeros(total)
    bins = np.fft.rfftfreq(N, 1 / fs)
    # ---- global scalars (curves and baked per-frame values override) ----
    breath0 = getattr(cfg, "breath", 1.0)
    vr_base = getattr(cfg, "vr_gain", 1.0)
    bri0 = getattr(cfg, "bright", 0.0); ten0 = getattr(cfg, "tension", 0.0)
    pulse = 0.0                                   # glottal phase carried across frames
    vr_ptr = 0.0                                  # residual loop read pointer
    spp_acc = {}                                  # eq.2 accumulated phase per harmonic
    tmpl_ph = None
    if getattr(cfg, "exc_template", "delta") == "glottal":
        tmpl_ph = np.angle(np.fft.rfft(glottal_template(fs), N))
    i = np.arange(N)
    # ---- drawn pencil curves (ms, value) per parameter ----
    def _prep(cur):
        return [([p[0] for p in s], [p[1] for p in s]) for s in (cur or []) if len(s) > 1]
    pc  = _prep(getattr(cfg, "pitch_curve", None))
    vc  = _prep(getattr(cfg, "vol_curve", None))
    gc  = _prep(getattr(cfg, "gender_curve", None))
    wc  = _prep(getattr(cfg, "voicing_curve", None))
    bc  = _prep(getattr(cfg, "bre_curve", None))
    bcq = _prep(getattr(cfg, "bri_curve", None))
    tcq = _prep(getattr(cfg, "ten_curve", None))
    fc1 = _prep(getattr(cfg, "f1_curve", None))
    fc2 = _prep(getattr(cfg, "f2_curve", None))
    fc3 = _prep(getattr(cfg, "f3_curve", None))
    vib = getattr(cfg, "vibratos", None) or []
    ptl = getattr(cfg, "pt_trans", None) or []    # shaped portamento transitions
    # ---- EQ shape bases: ALWAYS defined (baked per-frame bri/ten may appear
    #      even when no global scalar/curve is set) ----
    eq_grid = np.linspace(60., 20000., 32)
    lq = np.log2(eq_grid)
    hs = 1. / (1. + np.exp(-(lq - np.log2(4000.)) / 0.6))   # high shelf @4k
    mb = np.exp(-0.5 * ((lq - np.log2(1500.)) / 1.0) ** 2)  # mid bell @1.5k
    for m, fr in enumerate(frames):
        s = margin + m * hop + int(fr.get("dtoff", 0))
        g = fr.get("gain", 1.)
        gv = 1.; gf_c = None; voi_c = None
        breath_f = breath0; bri_f = bri0; ten_f = ten0
        if pc or vc or gc or wc or vib or bc or bcq or tcq or fc1 or fc2 or fc3 or ptl:
            t_ms = (m * hop + int(fr.get("dtoff", 0))) / fs * 1000.
            # ---- shaped portamento transitions replace f0 inside their window
            #      (applied first so pencil strokes / vibrato can layer on top)
            if ptl and fr["voiced"]:
                for t0, t1, p0, p1, dep in ptl:
                    if t0 <= t_ms <= t1:
                        u = (t_ms - t0) / max(1e-3, t1 - t0)
                        s_ = u * u * (3 - 2 * u)              # smoothstep S-curve
                        val = p0 + (p1 - p0) * (s_ + 2. * dep * s_ * (1. - s_))
                        fr = dict(fr, f0=midi_to_hz(val) *
                                  2 ** (getattr(cfg, "pitch_cents", 0.) / 1200.))
                        break
            # ---- pitch pencil overrides the base f0 where drawn ----
            if pc and fr["voiced"]:
                for xs, ys in pc:
                    if xs[0] <= t_ms <= xs[-1]:
                        fr = dict(fr, f0=midi_to_hz(float(np.interp(t_ms, xs, ys))))
                        break
            if vc:
                for xs, ys in vc:
                    if xs[0] <= t_ms <= xs[-1]:
                        gv = float(np.interp(t_ms, xs, ys)); break
            if gc:
                for xs, ys in gc:
                    if xs[0] <= t_ms <= xs[-1]:
                        gf_c = float(np.interp(t_ms, xs, ys)); break
            if wc:
                for xs, ys in wc:
                    if xs[0] <= t_ms <= xs[-1]:
                        voi_c = float(np.interp(t_ms, xs, ys)); break
            if bc:
                for xs, ys in bc:
                    if xs[0] <= t_ms <= xs[-1]:
                        breath_f = float(np.interp(t_ms, xs, ys)); break
            if bcq:
                for xs, ys in bcq:
                    if xs[0] <= t_ms <= xs[-1]:
                        bri_f = float(np.interp(t_ms, xs, ys)); break
            if tcq:
                for xs, ys in tcq:
                    if xs[0] <= t_ms <= xs[-1]:
                        ten_f = float(np.interp(t_ms, xs, ys)); break
            # ---- vibrato: enveloped sine (cents) multiplied onto f0 ----
            if vib and fr["voiced"]:
                dev = 0.
                for vv in vib:
                    if vv["s"] <= t_ms <= vv["e"]:
                        durs = max(1e-3, (vv["e"] - vv["s"]) / 1000.)
                        t = (t_ms - vv["s"]) / 1000.
                        fin = max(1e-3, vv.get("fin", 0.25) * durs)
                        fout = max(1e-3, vv.get("fout", 0.25) * durs)
                        venv = min(1., t / fin, (durs - t) / fout)
                        dev += vv["amp"] * max(0., venv) * \
                            np.sin(2 * np.pi * vv["freq"] * t)
                if dev:
                    fr = dict(fr, f0=fr["f0"] * 2 ** (dev / 1200.))
        # ---- baked per-frame values outrank curves/scalars ----
        if "gen" in fr: gf_c = fr["gen"]
        if "voi" in fr: voi_c = fr["voi"]
        if "bre" in fr: breath_f = fr["bre"]
        if "bri" in fr: bri_f = fr["bri"]
        if "ten" in fr: ten_f = fr["ten"]
        # ---- per-frame breath/EQ amounts ----
        vr_gain = vr_base * min(breath_f, 1.)          # recorded air only
        air = max(0., breath_f - 1.)                   # synthesized aspiration
        # ---- formant pencil curves -> spectral warp (moves DSS with formants);
        #      baked warps (set in _frame) win over curve warps ----
        if (fc1 or fc2 or fc3) and fr["voiced"] and "warp" not in fr:
            L = [float(r[0]) for r in fr["res"][1:4]]
            if len(L) >= 2:
                eds = []
                for cur in (fc1, fc2, fc3):
                    v = None
                    for xs, ys in cur:
                        if xs[0] <= t_ms <= xs[-1]:
                            v = float(np.interp(t_ms, xs, ys)); break
                    eds.append(v)
                R = [eds[j] if eds[j] is not None else L[j] for j in range(len(L))]
                if any(abs(a - b) > 1. for a, b in zip(L, R)):
                    Lpts = np.array([0.] + L + [6000.])
                    Rpts = np.array([0.] + R + [6000.])
                    for j in range(1, len(Rpts)):
                        Rpts[j] = max(Rpts[j], Rpts[j - 1] + 50.)
                    fr = dict(fr, warp=(1.0, (Lpts, Rpts, Lpts, np.zeros_like(Lpts))))
        if fr["voiced"] and fr["f0"] > 20:
            f0 = fr["f0"]; P = fs / f0
            ratio = f0 / max(fr.get("f0r", f0), 30.)
            ratio = min(max(ratio, 0.5), 2.0)   # never more than an octave of stretch
            # ---- formant control: GENDER (constant/curve) x G-SHIFT (ratio drift)
            sig_f = getattr(cfg, "formant_shift", 0.10)
            gf = gf_c if gf_c is not None else getattr(cfg, "gender", 1.0)
            vt_scale = gf * (ratio ** sig_f)
            if "form" in fr: vt_scale *= fr["form"]
            voi = voi_c if voi_c is not None else getattr(cfg, "voicing", 1.0)
            # ---- EpR envelope on bins (residual/whisper), formant-scaled ----
            w = fr.get("warp"); bl = fr.get("blend")
            if w:                                   # fig.7 differential envelope
                sw, (Lpts, Rpts, gg, dv) = w
                fmap = (1 - sw) * bins + sw * np.interp(bins, Lpts, Rpts)
                env = (_env(fr, fmap, cfg, vt_scale) +
                       sw * np.interp(np.interp(bins, Lpts, Rpts), gg, dv))
            elif bl:                                # param-domain crossfade
                sb, other = bl
                env = (1 - sb) * _env(fr, bins, cfg, vt_scale) + sb * _env(other, bins, cfg)
            else:
                env = _env(fr, bins, cfg, vt_scale)
            # ---- BREATH: high-tilted aspiration mask (0 <~1k -> 1 >~4k)
            tilt = 1. / (1. + np.exp(-np.log2(np.maximum(bins, 1.) / 2000.) / 0.5))

            spp = fr.get("spp")
            use_spp = getattr(cfg, "use_spp", True) and spp is not None \
                and len(spp) and bl is None
            if use_spp:
                # ---- SPP render (SMAC-03 §5).
                #      Harmonic numbers are RE-DERIVED from the peak frequencies
                #      against the row-sanitized recorded f0: at consonant
                #      onsets the analysis f0 can lock an octave wrong, and the
                #      STORED k then carries that error into fp = k*f0 as an
                #      octave jump. Re-deriving k makes consonant frames pitch
                #      exactly like vowel frames (your external editor's hikes).
                f = spp[:, 1]
                f0r = max(fr.get("f0r", f0), 30.)
                kmax = int((fs / 2) / max(f0, 30.)) + 1      # no aliasing harmonics
                k = np.clip(np.round(f / f0r), 1, kmax).astype(int)
                fp = k * f0                        # commanded pitch, clean k
                fe = fp
                if w:                               # warp moves ONLY the envelope
                    sw, (Lpts, Rpts, gg, dv) = w
                    fe = (1 - sw) * fp + sw * np.interp(fp, Lpts, Rpts)
                mdb = _env(fr, fe, cfg, vt_scale)   # amps: DSS + resonances at fe
                if w:
                    mdb = mdb + sw * np.interp(fe, gg, dv)
                if bri_f or ten_f:                  # BRIGHT/TENSION (any source)
                    mdb = mdb + np.interp(fp, eq_grid, bri_f * hs + ten_f * mb)
                eq = fr.get("eq")                   # §5.2 per-note eq hook stacks
                if eq is not None:
                    mdb = mdb + np.interp(fp, eq[0], eq[1])
                if air > 0.:                        # leaky glottis: thin top harmonics
                    mdb = mdb - 4. * air * np.interp(fp, bins, tilt)
                ph = spp[:, 3] + np.fromiter((spp_acc.get(kk, 0.) for kk in k), float)
                a = 10 ** (mdb / 20.)
                sig_h = (a[:, None] * np.cos(2 * np.pi * fp[:, None] * i[None, :] / fs
                                             + ph[:, None])).sum(0)
                # phase continuity: recorded->target correction per frame
                dph = 2 * np.pi * (fp - f) * hop / fs
                for kk, dd in zip(k, dph):
                    spp_acc[kk] = spp_acc.get(kk, 0.) + dd
            else:
                # ---- EpR comb fallback (blend frames / legacy) ----
                fmax = min(fs / 2, cfg.dss_fmax)
                ks = np.arange(1, int(fmax / f0) + 1)
                fh = ks * f0
                if w:
                    sw, (Lpts, Rpts, gg, dv) = w
                    fmap = (1 - sw) * fh + sw * np.interp(fh, Lpts, Rpts)
                    env_h = (_env(fr, fmap, cfg, vt_scale) +
                             sw * np.interp(np.interp(fh, Lpts, Rpts), gg, dv))
                elif bl:
                    sb, other = bl
                    env_h = (1 - sb) * _env(fr, fh, cfg, vt_scale) + sb * _env(other, fh, cfg)
                else:
                    env_h = _env(fr, fh, cfg, vt_scale)
                if bri_f or ten_f:
                    env_h = env_h + np.interp(fh, eq_grid, bri_f * hs + ten_f * mb)
                if air > 0.:
                    env_h = env_h - 4. * air * np.interp(fh, bins, tilt)
                a = 10 ** (env_h / 20.)
                ph0 = 2 * np.pi * ks * pulse
                if tmpl_ph is not None:
                    ph0 = ph0 + np.interp(fh, bins, tmpl_ph)
                th = _phase_model(fh, fr["res"])
                sig_h = (a[:, None] * np.cos(2 * np.pi * fh[:, None] * i[None, :] / fs
                                             + ph0[:, None] + th[:, None])).sum(0)
                pulse = (pulse + hop / P) % 1.0
            # ---- VOICING fades the harmonic part (gradual devoicing) ----
            sig = voi * sig_h
            # ---- voiced residual excitation (ICMC-01 §3.1), alias-safe ----
            vr = fr.get("vr")
            w_vr = 0.
            if vr is not None:
                rho = f0 / max(vr["rec_pitch"], 30.)
                # full weight near rho=1, fading to 0 as transposition grows
                w_vr = min(max(1. - (abs(np.log2(max(rho, 1e-3))) - 0.6) / 0.6, 0.), 1.)
                w_vr *= voi                         # VOICING gates the air
                if w_vr > 0.:
                    vflat = vr["flat"]; vlen = len(vflat)
                    pos = vr_ptr + np.arange(N) * rho
                    ip = np.floor(pos).astype(int); fp_ = pos - ip
                    # Catmull-Rom cubic read (cleaner than linear for rho>1)
                    a0 = vflat[(ip - 1) % vlen]; b0 = vflat[ip % vlen]
                    c0 = vflat[(ip + 1) % vlen]; d0 = vflat[(ip + 2) % vlen]
                    seg = 0.5 * (2 * b0 + (c0 - a0) * fp_ +
                                 (2*a0 - 5*b0 + 4*c0 - d0) * fp_**2 +
                                 (3 * (b0 - c0) + d0 - a0) * fp_**3)
                    R = np.fft.rfft(seg)
                    m0 = np.abs(R).mean() or 1.
                    vd = np.interp(bins, vr["centers"], vr["vr_diff"])
                    sig = sig + vr_gain * w_vr * \
                        np.fft.irfft(R / m0 * 10 ** ((env + vd) / 20.), N)
                    vr_ptr = (vr_ptr + hop * rho) % vlen
            if (1. - w_vr) > 0. and fr["uv"] is not None and not np.all(fr["uv"] == 0.):
                # alias-free noise floor takes over as transposition grows
                edges = np.linspace(0, fs / 2, len(fr["uv"]) + 1)
                cent = (edges[:-1] + edges[1:]) / 2
                lin = 10 ** (np.interp(bins[1:-1], cent, fr["uv"]) / 20.)
                phn = np.random.uniform(-np.pi, np.pi, len(lin))
                Xn = np.zeros(N // 2 + 1, complex); Xn[1:-1] = lin * np.exp(1j * phn)
                sig = sig + vr_gain * (1. - w_vr) * np.fft.irfft(Xn, N)
            # ---- VOICING whisper component, RMS-matched to the un-faded comb ----
            if (1. - voi) > 1e-3:
                lin = 10 ** (np.clip(env, -120., 60.) / 20.)
                phn = np.random.uniform(-np.pi, np.pi, len(bins))
                Xn = np.zeros(len(bins), complex)
                Xn[1:] = lin[1:] * np.exp(1j * phn[1:])
                wn = np.fft.irfft(Xn, N)
                sc = np.sqrt(np.mean(sig_h ** 2)) / (np.sqrt(np.mean(wn ** 2)) + 1e-9)
                sig = sig + (1. - voi) * sc * wn
            # ---- BREATH > 1: VT-shaped aspiration noise (the breathy sound) ----
            if air > 0. and voi > 0.:
                lin = 10 ** (np.clip(env, -120., 60.) / 20.) * tilt
                phn = np.random.uniform(-np.pi, np.pi, len(bins))
                Xn = np.zeros(len(bins), complex)
                Xn[1:] = lin[1:] * np.exp(1j * phn[1:])
                wn = np.fft.irfft(Xn, N)
                sc = np.sqrt(np.mean(sig_h ** 2)) / (np.sqrt(np.mean(wn ** 2)) + 1e-9)
                sig = sig + voi * 0.6 * air * sc * wn
        else:
            # ---- UNVOICED ----
            pulse = 0.0
            edges = np.linspace(0, fs / 2, len(fr["uv"]) + 1)
            cent = (edges[:-1] + edges[1:]) / 2
            lin = 10 ** (np.interp(bins[1:-1], cent, fr["uv"]) / 20.)
            ph = np.random.uniform(-np.pi, np.pi, len(lin))
            X = np.zeros(N // 2 + 1, complex); X[1:-1] = lin * np.exp(1j * ph)
            sig = np.fft.irfft(X, N)
        out[s:s + N] += g * gv * win * sig; winsum[s:s + N] += g * win
    winsum[winsum < 1e-3] = 1e-3
    return (out / winsum)[margin:]

def _join(L, R, opts, cfg):
    """Boundary corrections between concatenated rows; returns sample offset."""
    fs = cfg.sample_rate; hop = int(cfg.hop_s * fs)
    lf = next((f for f in reversed(L) if f["voiced"]), None)
    rf = next((f for f in R if f["voiced"]), None)
    if lf is not None and rf is not None:
        K, w = int(opts["trans_frames"]), float(opts["ss_intp"])
        if K > 0 and w > 0:                         # fig.7: stretch + diff envelope
            Lpts, Rpts = _anchors(lf), _anchors(rf)
            gg = np.arange(0, min(fs / 2, cfg.dss_fmax), 50.)
            dv = _env(rf, gg, cfg) - _env(lf, np.interp(gg, Rpts, Lpts), cfg)
            md = (Lpts, Rpts, gg, dv)
            for j, fr in enumerate(L[-K:]):
                if fr["voiced"]: fr["warp"] = (w * (j + 1) / K, md)
        if opts["phase_align"]:                     # eq.4: align glottal pulses
            thL = _phase_model(np.array([lf["f0"]]), lf["res"])[0]
            thR = _phase_model(np.array([rf["f0"]]), rf["res"])[0]
            dt = int(round(-(thR - thL) / (2 * np.pi * rf["f0"]) * fs))
            dt = ((dt + hop // 2) % hop) - hop // 2
        else:
            dt = 0
        return dt
    X = int(opts["xfade_ms"] / 1000 * fs)           # unvoiced joint: gain crossfade
    if X > 0:
        r_ = np.linspace(0., 1., X)
        for j, fr in enumerate(L[-X:]): fr["gain"] = fr.get("gain", 1.) * (1 - r_[j])
        for j, fr in enumerate(R[:X]): fr["gain"] = fr.get("gain", 1.) * r_[j]
    return -X

def row_frames(db, pair, dur_ms, midi, log=None, pmidi=None, split=0.):
    """Assemble the frame sequence of one row (diphone or sustain).
    Missing units: db.unit/db.steady fall back to the nearest pitch group;
    a row missing in ALL groups renders as timed silence so the song keeps
    its timing and synthesis continues."""
    cfg = db.cfg; fs = cfg.sample_rate
    tok = pair.split()
    # global PITCH parameter: master-tune the whole synthesis (+-1 st)
    hz = midi_to_hz(midi) * 2 ** (getattr(cfg, "pitch_cents", 0.) / 1200.)

    def tag_vr(frames_list):
        """Attach the group's voiced-residual model (nearest-group aware)."""
        v = db.vr_for(midi)
        if v is not None:
            for f in frames_list: f["vr"] = v
        return frames_list

    def silence(req):
        """Timed silent frames: keep the row's duration, sing nothing."""
        return [dict(voiced=False, f0=0., f0r=30., src=np.zeros(3, np.float32),
                     res=[], dss=np.zeros(1, np.float32),
                     uv=np.full(8, -120., np.float32), spp=None) for _ in range(req)]

    def finish(frames_list, dur):
        """Clamp recorded-f0 outliers (octave errors at consonants) so the
        transposition ratio can't spike, then flatten + tag."""
        vals = [f["f0r"] for f in frames_list if f["voiced"] and f.get("f0r", 0.) > 20.]
        if vals:
            med = float(np.median(vals))
            lo, hi = med * 0.75, med * 1.33
            for f in frames_list:
                if f["voiced"] and f.get("f0r", 0.) > 20.:
                    f["f0r"] = min(max(f["f0r"], lo), hi)
        return tag_vr(flatten(frames_list, dur))

    # global MODULATION: 0 = as recorded, 1 = steady regions flattened to the
    # exact note pitch everywhere (diphones included); at partial values the
    # edge protection shrinks so the recorded glide bleeds back in at borders
    def flatten(frames_list, dur):
        mfac = getattr(cfg, "modulation", 0.)
        if mfac <= 0.: return frames_list
        hop_ms = cfg.hop_s * 1000.
        dur = max(1., dur if dur > 0 else len(frames_list) * hop_ms)
        full = mfac >= 1.
        rin = min(150., 0.4 * dur) * (1. - mfac)
        rout = min(120., 0.3 * dur) * (1. - mfac)
        cents = 2 ** (getattr(cfg, "pitch_cents", 0.) / 1200.)
        lh = np.log(max(hz, 30.))
        lh0 = np.log(max(midi_to_hz(pmidi) * cents, 30.)) \
            if pmidi is not None else lh
        for i, fr in enumerate(frames_list):
            if not fr["voiced"] or fr["f0"] <= 20: continue
            t = i * hop_ms
            tgt = lh0 if t < split else lh      # prev pitch before the onset,
            w = 1. if full else max(0., min(1., min(t / max(rin, 1e-3),   # note pitch after
                                    (dur - t) / max(rout, 1e-3)))) * mfac
            if w > 0.:
                lf = np.log(max(fr["f0"], 30.))
                fr["f0"] = float(np.exp(lf + (tgt - lf) * w))
        return frames_list

    # ---------------- sustain row (single phoneme) ----------------
    if len(tok) == 1:
        ph = tok[0]
        st, st_rec, i0, i1 = db.steady(ph, midi)
        if st is None:                             # missing in every group
            if log: log(f"  {ph} @ {midi}: no sustain in any group -> silenced")
            return silence(max(1, int(round(dur_ms / 1000 / cfg.hop_s))))
        req = max(1, int(round(dur_ms / 1000 / cfg.hop_s)))
        nloop = i1 - i0                            # P1..TRANS loop region
        stransp = hz / max(st_rec, 30.)
        fr = [_frame(st, i0 + (i % nloop), stransp) for i in range(req)]
        if log: log(f"  {ph} @ {midi}: sustain row (loop {nloop} fr, {req} fr)")
        return finish(fr, dur_ms)

    # ---------------- diphone row ----------------
    try:
        arr, meta, g = db.unit(pair, midi)         # nearest-group fallback inside
    except KeyError:
        if log: log(f"  {pair} @ {midi}: missing in all groups -> silenced")
        return silence(max(1, int(round(dur_ms / 1000 / cfg.hop_s))))
    mk = {k: v / 1000. for k, v in meta["markers"].items()}
    transp = hz / max(meta["rec_pitch"], 30.)
    n = len(arr["t"]); it = int(np.searchsorted(arr["t"], mk["trans"]))
    fin = [_frame(arr, i, transp) for i in range(it)]          # START..TRANS
    fout = [_frame(arr, i, transp) for i in range(it, n)]      # TRANS..END
    req = int(round(dur_ms / 1000 / cfg.hop_s)) if dur_ms > 0 else 0
    st, st_rec, i0, i1 = db.steady(pair.split()[1], midi)
    if st is not None and req > len(fin) + 4:
        # long note: crossfade TRANS..END into the target vowel's steady loop
        nloop = i1 - i0
        stransp = hz / max(st_rec, 30.)
        nf = min(len(fout), max(0, req - len(fin)))
        head = [_frame(st, i0 + (i % nloop), stransp) for i in range(nf)]
        tail = [_frame(st, i0 + (i % nloop), stransp)
                for i in range(max(0, req - len(fin) - nf))]
        for i in range(nf):                         # TRANS..END -> steady blend
            fout[i]["blend"] = ((i + 1) / max(1, nf), head[i])
        frames = fin + fout[:nf] + tail
        if log: log(f"  {pair} @ {midi}: group {g}, sustain '{pair.split()[1]}' "
                    f"(loop {nloop} fr, filled {req - len(fin)})")
    else:
        seq = fin + fout
        if req > len(seq):
            if log: log(f"  {pair} @ {midi}: group {g}, NO sustain for "
                        f"'{pair.split()[1]}' -> holding last frame")
            hold = []
            last = seq[-1]
            prev = last.get("spp")
            prev = np.array(prev, copy=True) if (prev is not None and len(prev)) else None
            for _ in range(req - len(seq)):
                fr = dict(last)
                if prev is not None:
                    spp = np.array(prev)
                    spp[:, 3] += 2 * np.pi * spp[:, 1] * cfg.hop_s   # pitch phase keeps advancing
                    fr["spp"] = spp
                    prev = spp
                hold.append(fr)
            seq = seq + hold
        elif req > 0 and req < len(seq):
            # fast passage: time-compress the unit to the requested length
            if log: log(f"  {pair} @ {midi}: sped up x{len(seq) / req:.2f} to fit")
            nfull = len(seq)
            seq = [dict(seq[int(k * nfull / req)]) for k in range(req)]
            prev = None
            for fr in seq:
                spp = fr.get("spp")
                if spp is None or not len(spp):
                    prev = None; continue
                spp = np.array(spp, copy=True)
                if prev is not None and len(prev) == len(spp):
                    # rebase: skipped source frames must not leak into the phase
                    spp[:, 3] = prev + 2 * np.pi * spp[:, 1] * cfg.hop_s
                fr["spp"] = spp
                prev = spp[:, 3]
        frames = seq                                # req == 0 -> as recorded
    return finish(frames, dur_ms)

def render_rows(db, rows, opts=None, log=None):
    """Render a MicroScore row list into a normalized waveform."""
    opts = dict(DEFAULT_OPTS, **(opts or {}))
    cfg = db.cfg
    if log:
        log(f"  globals: pitch={getattr(cfg, 'pitch_cents', 0.):+.0f}c "
            f"gender={getattr(cfg, 'gender', 1.):.2f} gshift={getattr(cfg, 'formant_shift', .1):.2f} "
            f"voi={getattr(cfg, 'voicing', 1.):.2f} breath={getattr(cfg, 'breath', 1.):.2f} "
            f"bright={getattr(cfg, 'bright', 0.):+.1f}dB tension={getattr(cfg, 'tension', 0.):+.1f}dB "
            f"mod={getattr(cfg, 'modulation', 0.):.2f} "
            f"pt={len(getattr(cfg, 'pt_trans', None) or [])} "
            f"pencil={len(getattr(cfg, 'pitch_curve', None) or [])} segs")
    G, cum = [], 0
    for r in rows:
        fr = row_frames(db, r["pair"], r["dur"], r["midi"], log,
                        pmidi=r.get("pmidi"), split=r.get("split", 0.))
        if G:
            cum += _join(G, fr, opts, cfg)
        for f in fr:
            f["dtoff"] = f.get("dtoff", 0) + cum
        G.extend(fr)
    y = synth_frames(G, cfg)
    peak = np.abs(y).max() or 1.
    return y * 0.8 / peak