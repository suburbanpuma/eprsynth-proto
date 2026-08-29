# =============================================================================
# unit.py — EpR unit construction & storage.
#
# Turns analyzed frames (analysis.analyze) into the compact per-frame arrays
# stored in the DB (.npz):
#   t        : frame times RELATIVE to unit start (s)
#   voiced   : voiced flag
#   f0       : fundamental (Hz, recorded)
#   src      : source curve (gain, slope, slopedepth)          [ICMC-01 eq.9]
#   src_res  : source resonance (F, Bw, Amp)
#   vt       : vocal-tract resonances (n_vt x 3)              [Klatt, eq.3]
#   dss      : differential spectral shape (dB)               [eq.1/4]
#   uv       : unvoiced / voiced-residual noise-floor envelope (bands)
#   spp_*    : SPP hi-fi layer: harmonic peaks (k, f, dB, phase), flat+offsets
#
# Markers: build_unit returns them in SECONDS relative to the unit start
# (core multiplies by 1000 for the index); build_steady returns them in
# MILLISECONDS relative to the sustain start, matching the relative t axis and
# the stored waveform preview (the sustain-loop fix).
# =============================================================================
import numpy as np

from .epr import model_frame

def _formants(arr):
    """Median frequencies of the first 3 VT resonances (inventory display)."""
    vt = arr["vt"][arr["voiced"]]
    out = []
    for k in range(min(3, vt.shape[1])):
        fk = vt[:, k, 0]
        fk = fk[fk > 0]
        out.append(float(np.median(fk)) if len(fk) else 0.)
    return out

def _arrays_from(sel, cfg, fs, t0):
    """Pack selected analysis frames into rectangular DB arrays."""
    n = len(sel)
    n_dss = len(np.arange(0, min(fs / 2, cfg.dss_fmax), cfg.dss_step))
    # fit EpR models first so array widths follow the model output
    # (no cfg.resonances dependency; n_vt derived from the fit)
    models = []
    for f in sel:
        if f["voiced"] and len(f["hf"]) >= 3:
            models.append(model_frame(f["hf"][:, 0], f["hf"][:, 1], f["f0"], cfg, fs))
        else:
            models.append(None)
    n_vt = max((len(m["vt"]) for m in models if m is not None), default=4)

    T = np.array([f["t"] - t0 for f in sel], np.float32)      # relative time (s)
    V = np.array([f["voiced"] for f in sel], bool)
    F0 = np.array([f["f0"] for f in sel], np.float32)
    SRC = np.zeros((n, 3), np.float32)
    SR = np.zeros((n, 3), np.float32)
    VT = np.zeros((n, n_vt, 3), np.float32)
    DSS = np.zeros((n, n_dss), np.float32)
    UV = np.zeros((n, cfg.uv_bands), np.float32)
    for i, (f, m) in enumerate(zip(sel, models)):
        if m is not None:
            SRC[i] = (m["gain"], m["slope"], m["sdepth"])
            SR[i] = m["src_res"]
            VT[i, :len(m["vt"])] = m["vt"]
            DSS[i] = m["dss"]
        if f["uv"] is not None:
            UV[i] = f["uv"]
    # ---- SPP hi-fi layer: (k, freq, dB, phase) peaks, flat + per-frame offsets
    spp_off = np.zeros(n + 1, np.int32)
    for i, f in enumerate(sel):
        spp_off[i + 1] = spp_off[i] + len(f["spp"])
    spp_data = (np.concatenate([f["spp"] for f in sel]).astype(np.float32)
                if spp_off[-1] else np.zeros((0, 4), np.float32))
    return dict(t=T, voiced=V, f0=F0, src=SRC, src_res=SR, vt=VT, dss=DSS, uv=UV,
                spp_data=spp_data, spp_off=spp_off)

def build_unit(frames, lb, cfg, fs):
    """Articulation unit from frames + label (SECONDS, from Label.sec()).
    Returns (arrays, meta) with markers relative to unit start (s)."""
    a, b = lb.start, lb.end
    sel = [f for f in frames if a <= f["t"] < b]
    if len(sel) < 4: raise ValueError("unit too short")
    arr = _arrays_from(sel, cfg, fs, t0=a)
    mk = dict(p1=lb.m_p1 - a, p2=lb.m_p2 - a, trans=lb.m_trans - a, end=b - a)
    f0s = arr["f0"][arr["voiced"]]
    return arr, dict(markers=mk,
                     rec_pitch=float(np.median(f0s)) if len(f0s) else 0.,
                     formants=_formants(arr))

def build_steady(frames, lb, cfg, fs):
    """Sustain unit from frames + label (MILLISECONDS).
    Markers stored RELATIVE to unit start (ms) so db.steady's loop indices
    (searchsorted on relative t) and the editor waveform stay consistent."""
    a, b = lb.start / 1000., lb.end / 1000.
    sel = [f for f in frames if a <= f["t"] < b]
    if len(sel) < 4: raise ValueError("sustain too short")
    arr = _arrays_from(sel, cfg, fs, t0=a)
    mk = dict(p1=lb.m_p1 - lb.start,
              trans=lb.m_trans - lb.start,
              end=lb.end - lb.start)
    f0s = arr["f0"][arr["voiced"]]
    return arr, dict(markers=mk,
                     rec_pitch=float(np.median(f0s)) if len(f0s) else 0.)

def save_unit(path, arrays):
    np.savez(path, **arrays)

def wave_env(x, step=128):
    """Peak envelope for waveform previews (~2.9 ms/point at 44.1k)."""
    n = len(x)
    if n < step: return np.abs(x).astype(np.float32)
    x = x[: n // step * step]
    return np.abs(x.reshape(-1, step)).max(axis=1).astype(np.float32)