# =============================================================================
# vr.py — Modeled Voiced Residual (ICMC-01 §3.1 / Fig 3).
#
# The voiced residual excitation is obtained from the SMS-style residual of a
# recorded steady-state vowel (recording - harmonic EpR synthesis), inverse-
# filtered by its short-time average spectral shape to an approximately flat
# excitation, band-limited to delay transposition aliasing, and stored with:
#   flat      : time-domain flat residual loop
#   rec_pitch : median F0 of the source sustain (for transposition rate)
#   vr_diff   : residual filter offset vs the average EpR envelope (dB)
#   centers   : band centers of vr_diff
# =============================================================================
import numpy as np
from scipy.signal import get_window

def _band_env(db_mag, freqs, edges):
    """Max-dB band envelope of a magnitude spectrum."""
    return np.array([db_mag[(freqs >= a) & (freqs < b)].max()
                     if ((freqs >= a) & (freqs < b)).any() else -100.
                     for a, b in zip(edges[:-1], edges[1:])], np.float32)

def model_vr(x_seg, frames, cfg):
    """`frames` are ANALYSIS frames (from analyze()); they are converted to EpR
    model frames internally so synth/_env can consume them."""
    from .synth import synth_frames, _env
    from .analysis import stft
    from .epr import model_frame

    fs = cfg.sample_rate
    N = cfg.fft_size; hop = int(cfg.hop_s * fs)
    n_dss = len(np.arange(0, min(fs / 2, cfg.dss_fmax), cfg.dss_step))

    # ---- analysis frames -> EpR model frames (uv zeroed = harmonic-only) ----
    mfr = []
    for f in frames:
        if f["voiced"] and len(f["hf"]) >= 3:
            m = model_frame(f["hf"][:, 0], f["hf"][:, 1], f["f0"], cfg, fs)
            mfr.append(dict(voiced=True, f0=f["f0"],
                            src=np.array([m["gain"], m["slope"], m["sdepth"]], np.float32),
                            res=[tuple(m["src_res"])] + [tuple(v) for v in m["vt"]],
                            dss=m["dss"],
                            uv=np.zeros(cfg.uv_bands, np.float32)))
        else:
            mfr.append(dict(voiced=False, f0=0.0, src=np.zeros(3, np.float32), res=[],
                            dss=np.zeros(n_dss, np.float32),
                            uv=np.zeros(cfg.uv_bands, np.float32)))

    # ---- residual = recording - harmonic synthesis ----
    h = synth_frames(mfr, cfg)
    n = min(len(h), len(x_seg))
    r = x_seg[:n] - h[:n]

    freqs = np.fft.rfftfreq(N, 1 / fs)
    bands = 64
    edges = np.linspace(0, fs / 2, bands + 1)
    cent = (edges[:-1] + edges[1:]) / 2

    # ---- short-time average residual spectral shape ----
    shapes = []
    for _t, spec in stft(r, cfg):
        shapes.append(_band_env(20 * np.log10(np.abs(spec) + 1e-12), freqs, edges))
    S = np.median(np.array(shapes), axis=0)

    # ---- inverse-filter (flatten) with OLA ----
    win = get_window(cfg.window, N)
    out = np.zeros(n + N); ws = np.zeros(n + N)
    s = 0
    while s + N <= n:
        X = np.fft.rfft(r[s:s + N] * win)
        lin = 10 ** (np.maximum(np.interp(freqs, cent, S), -80.) / 20.)
        y = np.fft.irfft(X / np.maximum(lin, 1e-4), N)
        out[s:s + N] += y * win; ws[s:s + N] += win * win
        s += hop
    ws[ws < 1e-6] = 1e-6
    flat = (out / ws)[:n]

    # ---- band-limit so transposition aliasing starts only beyond rho ~1.8 ----
    F = np.fft.rfft(flat)
    frq = np.fft.rfftfreq(len(flat), 1 / fs)
    F[frq > 12000.] = 0.
    flat = np.fft.irfft(F, len(flat))

    # ---- residual filter offset vs average EpR envelope ----
    es = [_env(f, cent, cfg) for f in mfr if f["voiced"]]
    E = np.median(np.array(es), axis=0) if es else np.zeros(bands)
    f0s = [f["f0"] for f in frames if f["voiced"] and f["f0"] > 0]
    return dict(flat=flat.astype(np.float32),
                rec_pitch=float(np.median(f0s)) if f0s else 220.,
                vr_diff=(S - E).astype(np.float32),
                centers=cent.astype(np.float32))