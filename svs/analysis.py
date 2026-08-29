# =============================================================================
# analysis.py — SMS/SPP analysis front-end.
#
# Implements the frame-based spectral analysis shared by the dev tools and the
# DB import pipeline:
#   * STFT (analysis window per config)
#   * spectral peak detection with parabolic interpolation AND complex phase
#     (SPP requirement, SMAC-03 §3.2 / Fig.3)
#   * fundamental-frequency estimation with octave-down rejection
#     (score = energy ratio x harmonic coverage x peak count)
#   * voiced/unvoiced envelopes:
#       - unvoiced      : full band envelope of the frame
#       - voiced        : noise floor between harmonics (voiced residual shape)
#   * per-frame SPP table (k, freq, dB, phase) for the region-based transforms
# =============================================================================
import numpy as np
from scipy.signal import get_window

def stft(x, cfg):
    """Yield (center_sample, complex_spectrum) frames at cfg.hop_s spacing."""
    n = cfg.fft_size
    hop = int(cfg.hop_s * cfg.sample_rate)
    win = get_window(cfg.window, n)
    frames = []
    for s in range(0, max(1, len(x) - n), hop):
        frames.append((s + n / 2, np.fft.rfft(x[s:s + n] * win)))
    return frames

def detect_peaks(spec, freqs, cfg):
    """Spectral peaks as (freq, dB, phase) triples.
    freq/dB refined by parabolic interpolation; phase = bin phase (SPP)."""
    db = 20 * np.log10(np.abs(spec) + 1e-12)
    thr = db.max() + cfg.peak_floor_db
    peaks = []
    for i in range(1, len(db) - 1):
        if db[i] > db[i - 1] and db[i] >= db[i + 1] and db[i] > thr:
            den = db[i - 1] - 2 * db[i] + db[i + 1]
            p = 0.5 * (db[i - 1] - db[i + 1]) / den if den else 0.0
            p = min(max(p, -0.5), 0.5)
            peaks.append((freqs[i] + p * (freqs[1] - freqs[0]),
                          db[i] - 0.25 * (db[i - 1] - db[i + 1]) * p,
                          np.angle(spec[i])))
    return peaks

def estimate_pitch(peaks, freqs, cfg):
    """(f0, harmonic_energy_ratio, mask_of_matched_peaks).
    Candidates = peak/k; scored by ratio * coverage * count, which rejects
    sub-harmonic (octave-down) ties that pure ratio scoring allowed.
    A final octave-up collapse rejects locking onto the 2nd/4th harmonic
    (the spike source at consonant onsets)."""
    if len(peaks) < 3:
        return 0.0, 0.0, np.zeros(len(peaks), bool)
    pf = np.array([p[0] for p in peaks])
    pl = np.array([10 ** (p[1] / 20) for p in peaks])
    total = np.sum(pl ** 2)
    cands = {round(f / k, 1) for f in pf for k in range(1, 7)
             if cfg.f0_min <= f / k <= cfg.f0_max}
    best = (0.0, -1.0, np.zeros(len(peaks), bool))
    for f0 in cands:
        # harmonics only up to the highest detected peak -> coverage meaningful
        harm = f0 * np.arange(1, int(pf[-1] / f0) + 1)
        idx = np.searchsorted(pf, harm)
        mask = np.zeros(len(pf), bool)
        for h, i in zip(harm, idx):
            for j in (i - 1, i):
                if 0 <= j < len(pf) and abs(pf[j] - h) <= cfg.harmonic_tol * f0:
                    mask[j] = True
                    break
        ok = mask.sum()
        if ok < 3:
            continue
        ratio = np.sum(pl[mask] ** 2) / total
        coverage = ok / len(harm)
        score = ratio * coverage * ok
        if score > best[1]:
            best = (f0, score, mask)
    f0, _, _ = best
    if f0 <= 0:
        return 0.0, 0.0, np.zeros(len(peaks), bool)
    # ---- octave-up collapse: a real peak at f0/2 means the scorer locked the
    #      2nd harmonic; keep halving while the lower fundamental is present
    while f0 / 2 >= cfg.f0_min and \
            np.any(np.abs(pf - f0 / 2) <= cfg.harmonic_tol * f0):
        f0 /= 2.
    # rebuild the harmonic mask against the corrected fundamental
    harm = f0 * np.arange(1, int(pf[-1] / f0) + 1)
    idx = np.searchsorted(pf, harm)
    mask = np.zeros(len(pf), bool)
    for h, i in zip(harm, idx):
        for j in (i - 1, i):
            if 0 <= j < len(pf) and abs(pf[j] - h) <= cfg.harmonic_tol * f0:
                mask[j] = True
                break
    ratio = np.sum(pl[mask] ** 2) / total if mask.sum() else 0.0
    return f0, ratio, mask

def unvoiced_env(mag_db, freqs, cfg):
    """Max-dB band envelope of an unvoiced frame (uv_bands line segments)."""
    edges = np.linspace(0, freqs[-1], cfg.uv_bands + 1)
    return np.array([mag_db[(freqs >= a) & (freqs < b)].max()
                     if ((freqs >= a) & (freqs < b)).any() else -100.0
                     for a, b in zip(edges[:-1], edges[1:])], np.float32)

def noise_floor_env(spec, freqs, f0, cfg, bands=None):
    """Band envelope of the NON-harmonic part of a voiced frame = voiced
    residual shape (breathiness/glottal noise), stored pre-shaped."""
    bands = bands or cfg.uv_bands
    db = 20 * np.log10(np.abs(spec) + 1e-12)
    if f0 > 20:
        k = np.round(freqs / f0)
        keep = np.abs(freqs - k * f0) > 0.4 * f0      # bins away from any harmonic
        keep[0] = False
    else:
        keep = np.ones(len(db), bool)
    edges = np.linspace(0, freqs[-1], bands + 1)
    return np.array([db[keep & (freqs >= a) & (freqs < b)].max()
                     if (keep & (freqs >= a) & (freqs < b)).any() else -100.0
                     for a, b in zip(edges[:-1], edges[1:])], np.float32)

def region_bounds(peak_freqs, fmax):
    """SPP region boundaries: midpoints between adjacent harmonic peaks
    (each region = one peak + its surroundings, SMAC-03 §3.2)."""
    if not len(peak_freqs): return np.array([0., fmax])
    b = (peak_freqs[:-1] + peak_freqs[1:]) / 2
    return np.concatenate([[0.], b, [fmax]])

def analyze(x, cfg):
    """Full per-frame analysis. Frame dict keys:
       t      : center time (s)
       voiced : bool
       f0     : fundamental (Hz)
       hf     : (n,2) harmonic peaks (freq, dB) for the EpR fit
       uv     : band envelope (noise floor for voiced, full env for unvoiced)
       spp    : (n,4) SPP table (k, freq, dB, phase); k = harmonic index"""
    freqs = np.fft.rfftfreq(cfg.fft_size, 1 / cfg.sample_rate)
    out = []
    for t_c, spec in stft(x, cfg):
        mag_db = 20 * np.log10(np.abs(spec) + 1e-12)
        peaks = detect_peaks(spec, freqs, cfg)
        f0, ratio, mask = estimate_pitch(peaks, freqs, cfg)
        voiced = bool(f0 > 0 and ratio >= cfg.voiced_ratio_min)
        pf = np.array([p[0] for p in peaks]) if peaks else np.zeros(0)
        pdb = np.array([p[1] for p in peaks]) if peaks else np.zeros(0)
        pph = np.array([p[2] for p in peaks]) if peaks else np.zeros(0)
        if voiced:
            uv = noise_floor_env(spec, freqs, f0, cfg)
        else:
            uv = unvoiced_env(mag_db, freqs, cfg)
        if voiced and f0 > 0 and len(peaks):
            ks = np.round(pf / f0)
            spp = np.column_stack([ks[mask], pf[mask], pdb[mask], pph[mask]]) \
                      .astype(np.float32)
        else:
            spp = np.zeros((0, 4), np.float32)
        out.append(dict(t=t_c / cfg.sample_rate, voiced=voiced, f0=f0,
                        hf=(np.column_stack([pf[mask], pdb[mask]])
                            if voiced else np.zeros((0, 2))),
                        uv=uv, spp=spp))
    return out