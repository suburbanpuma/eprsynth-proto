import numpy as np

def source_db(f, gain, slope, sdepth):
    """Eq. (9): Source_dB(f) = Gain + SlopeDepth * (e^{-Slope*f} - 1)."""
    return gain + sdepth * np.expm1(-slope * np.asarray(f, float))

def res_db(f, F, Bw, Amp_db, fs):
    """Klatt 2nd-order resonance (eq. 3/11), in dB relative to source curve."""
    C = np.exp(-2 * np.pi * Bw / fs)
    B = -2 * np.exp(-np.pi * Bw / fs) * np.cos(2 * np.pi * F / fs)
    A = 1 - B - C
    w = 2 * np.pi * np.asarray(f, float) / fs
    z = np.exp(1j * w)
    H = A / (1 - B / z - C / (z * z))
    return np.maximum(20 * np.log10(np.abs(H) + 1e-9), -80.0) + Amp_db

def epr_ideal_db(f, gain, slope, sdepth, res_list, fs):
    """iEpR = source curve + max-of-neighbors resonances (engine optimization)."""
    base = source_db(f, gain, slope, sdepth)
    if not res_list:
        return base
    rel = np.max([res_db(f, F, Bw, A, fs) for F, Bw, A in res_list], axis=0)
    return base + rel

def hss_env(hf, hdb, fmax):
    xs = np.concatenate([[0.0], hf, [fmax]])
    ys = np.concatenate([[hdb[0]], hdb, [hdb[-1] - 40.0]])
    return lambda f: np.interp(f, xs, ys)

def fit_source_curve(hf, hdb):
    best = None
    for s in np.logspace(-6, -3, 41):
        A = np.column_stack([np.ones_like(hf), np.expm1(-s * hf)])
        g, d = np.linalg.lstsq(A, hdb, rcond=None)[0]
        err = np.mean((A @ [g, d] - hdb) ** 2)
        if best is None or err < best[0]:
            best = (err, float(g), float(s), float(d))
    return best[1], best[2], best[3]

def fit_resonances(fgrid, resid, n, prom=3.0):
    df = fgrid[1] - fgrid[0]
    peaks = []
    i = 1
    while i < len(resid) - 1:
        if resid[i] > resid[i - 1] and resid[i] >= resid[i + 1] and resid[i] > prom:
            l = i
            while l > 0 and resid[l] > resid[i] - 3.0:
                l -= 1
            r = i
            while r < len(resid) - 1 and resid[r] > resid[i] - 3.0:
                r += 1
            peaks.append((float(fgrid[i]), float(resid[i]), max(50.0, fgrid[r] - fgrid[l])))
            i += max(1, int(150 / df))
        else:
            i += 1
    peaks.sort(key=lambda p: -p[1])
    return sorted(peaks[:n])

def model_frame(hf, hdb, f0, cfg, fs):
    """Full EpR estimation for one voiced frame."""
    fmax = min(fs / 2, cfg.dss_fmax)
    gain, slope, sdepth = fit_source_curve(hf, hdb)
    fgrid = np.arange(30, fmax, cfg.fit_grid_step)
    resid = hss_env(hf, hdb, fmax)(fgrid) - source_db(fgrid, gain, slope, sdepth)
    peaks = fit_resonances(fgrid, resid, cfg.n_vt_res + 2)
    src_res = next((p for p in peaks if p[0] < cfg.src_res_fmax), (250.0, 0.0, 300.0))
    vt = [p for p in peaks if p[0] >= cfg.src_res_fmax][:cfg.n_vt_res]
    all_res = [src_res] + vt
    dss_f = np.arange(0, fmax, cfg.dss_step)
    dss = (hss_env(hf, hdb, fmax)(dss_f) -
           epr_ideal_db(dss_f, gain, slope, sdepth, all_res, fs))
    return dict(gain=gain, slope=slope, sdepth=sdepth,
                src_res=np.array(src_res, np.float32),
                vt=np.array(vt, np.float32).reshape(-1, 3),
                dss=dss.astype(np.float32))