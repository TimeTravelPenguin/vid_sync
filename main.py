import argparse
import re
import subprocess
import sys
from pathlib import Path

import librosa
import numpy as np
from scipy.signal import butter, filtfilt, correlate
from scipy.fft import rfft, irfft


def parse_time_to_seconds(s: str) -> int:
    """Parse a string like '12h34m56s', '34m', '56s', or '2h' into total seconds."""
    pattern = r"^(?:(?P<h>\d+)h)?(?:(?P<m>\d+)m)?(?:(?P<s>\d+)s)?$"
    m = re.fullmatch(pattern, s)
    if not m:
        raise argparse.ArgumentTypeError(f"Invalid time format: {s!r}  (expected e.g. '1h2m3s')")
    hours = int(m.group("h") or 0)
    minutes = int(m.group("m") or 0)
    seconds = int(m.group("s") or 0)
    return hours * 3600 + minutes * 60 + seconds


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Find the offset of video2 to video1.")

    # first file
    p.add_argument("file1", type=Path, help="Path to the first file")
    p.add_argument(
        "--start1",
        type=float,
        default=0,
        metavar="TIME",
        help="Start time for file1, e.g. '12h34m56s' (default: 0s)",
    )

    # second file
    p.add_argument("file2", type=Path, help="Path to the second file")
    p.add_argument(
        "--start2",
        type=float,
        default=0,
        metavar="TIME",
        help="Start time for file2, e.g. '5m30s' (default: 0s)",
    )

    # search duration
    p.add_argument(
        "--search_dur",
        type=float,
        default=120.0,
        metavar="SECONDS",
        help="Duration of the search clip in seconds (default: 120s)",
    )

    # sampling rate
    p.add_argument(
        "--sr",
        type=int,
        default=16000,
        metavar="HERTZ",
        help="Sampling rate for audio processing (default: 16000Hz)",
    )

    # silent mode
    p.add_argument(
        "--silent",
        action="store_true",
        help="Run in silent mode without printing output",
    )

    return p


def extract_audio(video_path: Path, audio_path: Path, sr: int = 16000) -> None:
    # Extract mono 16 kHz WAV
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-stats",
            "-i",
            video_path,
            "-ac",
            "1",
            "-ar",
            str(sr),
            audio_path,
        ],
        check=True,
    )


def start_seconds(h: int, m: int, s: int) -> float:
    """Convert hours, minutes, seconds to total seconds."""
    return h * 3600 + m * 60 + s


def format_seconds(seconds: float) -> str:
    """Format seconds into a string of the form 'HH:MM:SS'."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02}:{m:02}:{s:02}"


def calc_similar_start(start1: float, start2: float, offset_sec: float) -> float:
    """Calculate the start time of the second video based on the first video's start and the offset."""
    return start2 + offset_sec - start1


def bandpass_filter(x: np.ndarray, sr: int, low: float = 300, high: float = 3400, order: int = 4):
    """4th-order Butterworth bandpass between low-high Hz."""
    nyq = sr / 2
    b, a = butter(order, [low / nyq, high / nyq], btype="band")
    return filtfilt(b, a, x)


def parabolic_interpolation(c: np.ndarray, idx: int) -> float:
    """Fit a parabola through c[idx-1], c[idx], c[idx+1] and return the fractional shift that peaks."""
    if idx <= 0 or idx >= len(c) - 1:
        return 0.0
    α, β, γ = c[idx - 1], c[idx], c[idx + 1]
    return 0.5 * (α - γ) / (α - 2 * β + γ)


def gcc_phat(x: np.ndarray, y: np.ndarray, sr: int, max_tau: float | None = None, interp: int = 1):
    """
    Generalized Cross-Correlation with Phase Transform.

    Returns: (delay_seconds, cc_signal)
    """
    n = x.size + y.size
    # FFT
    X = rfft(x, n=n)
    Y = rfft(y, n=n)
    R = X * np.conj(Y)
    R /= np.abs(R) + np.finfo(float).eps
    cc = irfft(R, n=interp * n)
    # center zero-lag
    max_shift = int(interp * n // 2)
    if max_tau is not None:
        max_shift = min(int(interp * max_tau * sr), max_shift)
    cc = np.concatenate((cc[-max_shift:], cc[: max_shift + 1]))
    shift = np.argmax(np.abs(cc)) - max_shift
    return shift / float(interp * sr), cc


def find_sync_offset(
    wav1: Path,
    wav2: Path,
    sr: int = 16_000,
    start1: float = 0.0,
    start2: float = 0.0,
    template_dur: float = 30.0,
    search_dur: float = 60.0,
    n_segments: int = 10,
    onset_ncc_thresh: float = 0.7,
):
    """Estimate the sync offset by averaging across `n_segments` sub-clips."""
    # 1) Load full template & search clips
    tpl_full, _ = librosa.load(wav1, sr=sr, mono=True, offset=start1, duration=template_dur)
    sig_full, _ = librosa.load(wav2, sr=sr, mono=True, offset=start2, duration=search_dur)

    # 2) Band-pass both
    tpl_bp_full = bandpass_filter(tpl_full, sr)
    sig_bp = bandpass_filter(sig_full, sr)

    # 3) Precompute onset-strength of search (for NCC)
    o_s = librosa.onset.onset_strength(y=sig_bp, sr=sr)

    # 4) Divide template into segments
    seg_len = len(tpl_bp_full) // n_segments
    offsets = []

    for i in range(n_segments):
        seg = tpl_bp_full[i * seg_len : (i + 1) * seg_len]

        # 4a) GCC-PHAT estimate
        tau, _ = gcc_phat(seg, sig_bp, sr)

        # 4b) Onset-strength NCC on this segment
        o_t = librosa.onset.onset_strength(y=seg, sr=sr)
        corr = correlate(o_s, o_t, mode="valid")
        Et = np.linalg.norm(o_t)
        win = np.ones_like(o_t)
        Es = np.sqrt(np.convolve(o_s**2, win, mode="valid"))
        ncc = corr / (Et * Es + 1e-8)

        idx = int(np.argmax(ncc))
        frac = parabolic_interpolation(ncc, idx)
        ncc_off = (idx + frac) / sr
        score = ncc[idx]

        # 4c) pick NCC if strong, else PHAT
        offsets.append(ncc_off if score >= onset_ncc_thresh else tau)

    # 5) Average across all segment-based estimates
    avg_offset = float(np.mean(offsets))

    return avg_offset


if __name__ == "__main__":
    args = build_parser().parse_args()

    vid1: Path = args.file1
    vid2: Path = args.file2
    start1: int = args.start1
    start2: int = args.start2
    search_dur: int = args.search_dur
    sr: int = args.sr
    silent: bool = args.silent

    # File paths
    vid1 = vid1.resolve(strict=True)
    vid2 = vid2.resolve(strict=True)

    wav1 = "./tmp" / Path(vid1.with_suffix(".wav").name)
    wav2 = "./tmp" / Path(vid2.with_suffix(".wav").name)

    # Extract Audio Segments
    if not wav1.exists():
        extract_audio(vid1, wav1, sr=sr)

    if not wav2.exists():
        extract_audio(vid2, wav2, sr=sr)

    wav1_duration = librosa.get_duration(path=wav1)
    wav2_duration = librosa.get_duration(path=wav2)
    min_duration = min(wav1_duration - start1, wav2_duration - start2)

    step = 60 * 60  # 1h step
    start_times = np.arange(0, min_duration, step)

    offsets = []

    for idx, start in enumerate(start_times):
        print(
            f"Processing segment {idx + 1}/{len(start_times)}: offset {start:.2f}s",
            file=sys.stderr,
        )

        offset = find_sync_offset(
            wav1,
            wav2,
            sr,
            start1=start + start1,
            start2=start + start2,
            template_dur=search_dur,
            search_dur=2 * search_dur,
        )

        offsets.append(offset)

    offset = float(np.mean(offsets))
    synced_time = start2 + offset - start1

    if not args.silent:
        print(f"Best match at {offset:.2f}s into video2 search clip")
        print(f"To sync, start video2 at {synced_time:.2f}s ({format_seconds(synced_time)})")
    else:
        print(f"To sync, start video2 at {synced_time:.2f}s ({format_seconds(synced_time)})", file=sys.stderr)
        print(f"{synced_time:.2f}")
