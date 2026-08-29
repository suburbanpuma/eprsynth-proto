from dataclasses import dataclass

@dataclass
class AnalysisConfig:
    sample_rate: int = 44100
    fft_size: int = 2048
    hop_s: float = 0.005            # 5 ms analysis hop
    window: str = "blackmanharris"
    f0_min: float = 70.0
    f0_max: float = 1200.0
    harmonic_tol: float = 0.08      # rel. tolerance for harmonic matching
    voiced_ratio_min: float = 0.6   # harmonic-energy ratio for voicing
    peak_floor_db: float = -60.0    # peaks below max+floor ignored
    n_vt_res: int = 4               # vocal-tract resonances (lightweight)
    src_res_fmax: float = 600.0     # below this -> source resonance
    dss_step: float = 75.0          # Hz; coarse on purpose (lightweight spec)
    dss_fmax: float = 11000.0
    fit_grid_step: float = 25.0     # Hz grid for resonance fitting
    uv_bands: int = 16              # line-segment bands for unvoiced env
    min_steady_s: float = 0.05
    vr_gain: float = 1.0            # voiced residual (noise-floor) excitation gain
    exc_template: str = "delta"     # "delta" | "glottal" (excitation template)
    use_spp: bool = True            # render voiced frames from SPP peaks (False = EpR comb)
    formant_shift: float = 0.10     # 0 = fixed formants, 1 = fully proportional shift
    gender: float = 1.0             # GENDER: constant formant scale (1.0 = neutral)
    pitch_cents: float = 0.0        # global pitch offset in cents (-100..+100)
    voicing: float = 1.0            # 0 = fully unvoiced (whisper), 1 = normal
    breath: float = 1.0             # 0 = no breath, 1 = as recorded, 2 = very breathy
    bright: float = 0.0             # BRIGHTNESS: high-shelf EQ (dB, -12..+12)
    tension: float = 0.0            # TENSION: mid-shelf EQ (dB, -12..+12)