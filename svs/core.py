# =============================================================================
# core.py — database creation / import / inventory.
# Imports recordings (wav+labels or batchlab), builds EpR units + sustains,
# stores waveform previews, and auto-models the per-group voiced residual (VR)
# from the longest sustain whenever a group lacks one.
# =============================================================================
import json
import os
from math import gcd

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

from . import langcfg, manifest, vr as vrmod
from .analysis import analyze
from .config import AnalysisConfig
from .labels import parse_batchlab, parse_labels
from .unit import build_steady, build_unit, save_unit, wave_env

def read_wav(path, cfg):
    sr, x = wavfile.read(path)
    if x.ndim > 1:
        x = x.mean(1)
    if x.dtype == np.uint8:
        x = (x.astype(np.float64) - 128.) / 128.
    elif np.issubdtype(x.dtype, np.integer):
        x = x.astype(np.float64) / np.iinfo(x.dtype).max
    else:
        x = x.astype(np.float64)
    if sr != cfg.sample_rate:
        g = gcd(int(sr), int(cfg.sample_rate))
        x = resample_poly(x, cfg.sample_rate // g, sr // g)
    return x

def create_db(path, name, developer, version, language, groups):
    manifest.create_db(path, name, developer, version, language, groups)

def open_db(db):
    cp = manifest.load_manifest(db)
    return dict(name=cp["singer"]["name"], developer=cp["singer"]["developer"],
                version=cp["singer"]["version"], language=cp["singer"]["language"],
                groups=[g.strip() for g in cp["pitchgroups.base"]["groups"].split(",")
                        if g.strip()])

def _steady_index_meta(arrays, cfg, markers):
    f0s = arrays["f0"][arrays["f0"] > 0]
    return dict(frames=len(arrays["t"]), markers=markers,
                rec_pitch=float(np.median(f0s)) if len(f0s) else 0.0)

def _maybe_build_vr(db, group, x, frames, sus_labels, cfg, log):
    """Auto-build the voiced residual model for a pitch group (if missing)."""
    p = os.path.join(db, "base", group, "vr.npz")
    if os.path.exists(p) or not sus_labels: return
    lb = max(sus_labels, key=lambda l: l.end - l.start)
    sr = cfg.sample_rate
    seg = x[int(lb.start / 1000 * sr):int(lb.end / 1000 * sr)]
    fs = [f for f in frames if lb.start / 1000 <= f["t"] < lb.end / 1000]
    if len(seg) < cfg.fft_size or len(fs) < 10:
        log(f"  VR modeling skipped: sustain '{lb.p1}' too short"); return
    try:
        m = vrmod.model_vr(seg, fs, cfg)
        np.savez(p, **m)
        log(f"  voiced residual modeled from sustain '{lb.p1}' "
            f"({len(m['flat']) / sr:.2f}s loop, F0~{m['rec_pitch']:.0f})")
    except Exception as e:
        log(f"  VR modeling failed: {e}")

def import_recording(db, group, wav, labels_path, log=print):
    cfg = AnalysisConfig()
    lang = langcfg.lang_for_db(db)
    x = read_wav(wav, cfg)
    sr = cfg.sample_rate
    dur_ms = len(x) / sr * 1000.
    labels = parse_labels(labels_path, lang.phonemes(), dur_ms)
    gdir = os.path.join(db, "base", group)
    with open(os.path.join(gdir, "index.json")) as f:
        index = json.load(f)
    log(f"analyzing {os.path.basename(wav)} ({dur_ms:.0f} ms) ...")
    frames = analyze(x, cfg)
    sus_labels = []
    for n, lb in enumerate(labels):
        if lb.sustain:                       # 5-field line: real recorded sustain
            arrays, meta = build_steady(frames, lb, cfg, sr)
            arrays["wave"] = wave_env(x[int(lb.start / 1000 * sr):int(lb.end / 1000 * sr)])
            save_unit(os.path.join(gdir, "steady", f"{lb.p1}.npz"), arrays)
            im = _steady_index_meta(arrays, cfg, meta["markers"])
            im["file"] = f"steady/{lb.p1}.npz"
            index["steady"][lb.p1] = im
            log(f"  [{n+1}/{len(labels)}] sustain {lb.p1}: "
                f"{int(arrays['voiced'].sum())} voiced frames, "
                f"F0~{meta['rec_pitch']:.0f} Hz")
            sus_labels.append(lb)
            continue
        # 7-field line: articulation
        arrays, meta = build_unit(frames, lb.sec(), cfg, sr)
        arrays["wave"] = wave_env(x[int(lb.start / 1000 * sr):int(lb.end / 1000 * sr)])
        meta["markers"] = {k: v * 1000. for k, v in meta["markers"].items()}
        fname = f"{lb.p1}_{lb.p2}.npz"
        save_unit(os.path.join(gdir, "diphones", fname), arrays)
        index["units"][f"{lb.p1} {lb.p2}"] = dict(file=f"diphones/{fname}", **meta)
        log(f"  [{n+1}/{len(labels)}] {lb.p1}->{lb.p2}: "
            f"{int(arrays['voiced'].sum())} voiced frames, "
            f"F0~{meta['rec_pitch']:.0f} Hz")
    with open(os.path.join(gdir, "index.json"), "w") as f:
        json.dump(index, f, indent=1)
    _maybe_build_vr(db, group, x, frames, sus_labels, cfg, log)
    return index

def import_batchlab(db, group, batchlab_path, log=print):
    cfg = AnalysisConfig()
    lang = langcfg.lang_for_db(db)
    sr = cfg.sample_rate
    base = os.path.dirname(os.path.abspath(batchlab_path))
    gdir = os.path.join(db, "base", group)
    with open(os.path.join(gdir, "index.json")) as f:
        index = json.load(f)
    by_file = {}
    for fn, lb in parse_batchlab(batchlab_path, lang.phonemes()):
        by_file.setdefault(fn, []).append(lb)
    for fn, lbs in by_file.items():
        wav = os.path.join(base, fn)
        if not os.path.exists(wav):
            log(f"missing file: {fn} -> skipped {len(lbs)} label(s)")
            continue
        x = read_wav(wav, cfg)
        dur_ms = len(x) / sr * 1000.
        log(f"analyzing {fn} ({dur_ms:.0f} ms) ...")
        frames = analyze(x, cfg)
        sus_labels = []
        for lb in lbs:
            if lb.end > dur_ms + 1e-6:
                log(f"  {fn}: markers beyond file end, skipped"); continue
            if lb.sustain:
                arrays, meta = build_steady(frames, lb, cfg, sr)
                arrays["wave"] = wave_env(x[int(lb.start / 1000 * sr):int(lb.end / 1000 * sr)])
                save_unit(os.path.join(gdir, "steady", f"{lb.p1}.npz"), arrays)
                im = _steady_index_meta(arrays, cfg, meta["markers"])
                im["file"] = f"steady/{lb.p1}.npz"
                index["steady"][lb.p1] = im
                log(f"  sustain {lb.p1}: {int(arrays['voiced'].sum())} voiced frames")
                sus_labels.append(lb)
            else:
                arrays, meta = build_unit(frames, lb.sec(), cfg, sr)
                arrays["wave"] = wave_env(x[int(lb.start / 1000 * sr):int(lb.end / 1000 * sr)])
                meta["markers"] = {k: v * 1000. for k, v in meta["markers"].items()}
                fname = f"{lb.p1}_{lb.p2}.npz"
                save_unit(os.path.join(gdir, "diphones", fname), arrays)
                index["units"][f"{lb.p1} {lb.p2}"] = dict(file=f"diphones/{fname}", **meta)
                log(f"  {lb.p1}->{lb.p2}: {int(arrays['voiced'].sum())} voiced frames")
        _maybe_build_vr(db, group, x, frames, sus_labels, cfg, log)
    with open(os.path.join(gdir, "index.json"), "w") as f:
        json.dump(index, f, indent=1)
    return index

def inventory(db):
    info = open_db(db)
    lang = langcfg.lang_for_db(db)
    out = {}
    for g in info["groups"]:
        with open(os.path.join(db, "base", g, "index.json")) as f:
            idx = json.load(f)
        out[g] = (idx, [p for p in sorted(lang.phonemes())
                        if lang.steady(p) and p not in idx["steady"]])
    return info, out