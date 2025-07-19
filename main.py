import argparse
import re
import subprocess
from pathlib import Path

import librosa
import numpy as np
from scipy.signal import correlate


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
        type=parse_time_to_seconds,
        default=0,
        metavar="TIME",
        help="Start time for file1, e.g. '12h34m56s' (default: 0s)",
    )

    # second file
    p.add_argument("file2", type=Path, help="Path to the second file")
    p.add_argument(
        "--start2",
        type=parse_time_to_seconds,
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
    subprocess.run(["ffmpeg", "-y", "-i", video_path, "-ac", "1", "-ar", sr, audio_path], check=True)


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


def find_sync_offset(
    wav1: Path,
    wav2: Path,
    sr: int,
    start1: float,
    start2: float,
    template_dur: float,
    search_dur: float,
) -> tuple[float, float]:
    """
    Compute sync offset between two audio signals.

    Returns (offset_into_wav2, synced_start2_absolute).
    """
    # 1. Load template clip from video1
    tpl, _ = librosa.load(str(wav1), sr=sr, mono=True, offset=start1, duration=template_dur)

    # 2. Load search clip from video2 (longer than template)
    sig, _ = librosa.load(str(wav2), sr=sr, mono=True, offset=start2, duration=search_dur)

    # 3. Use amplitude envelope to reduce background interference
    env_tpl = np.abs(tpl)
    env_sig = np.abs(sig)

    # 4. Compute normalized cross-correlation
    corr = correlate(env_sig, env_tpl, mode="valid")
    tpl_energy = np.linalg.norm(env_tpl)
    window = np.ones_like(env_tpl)
    sig_energy = np.sqrt(np.convolve(env_sig**2, window, mode="valid"))
    ncc = corr / (tpl_energy * sig_energy + 1e-8)

    # 5. Find the lag with maximum correlation
    best_idx = int(np.argmax(ncc))
    offset_sec = best_idx / sr

    # 6. Compute the absolute start time for video2 to match video1
    synced_start2 = start2 + offset_sec - start1

    return offset_sec, synced_start2


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

    wav1 = Path(vid1).with_suffix(".wav")
    wav2 = Path(vid2).with_suffix(".wav")

    # Extract Audio Segments
    if not wav1.exists():
        extract_audio(vid1, wav1, sr=sr)

    if not wav2.exists():
        extract_audio(vid2, wav2, sr=sr)

    offset, synced_time = find_sync_offset(
        wav1,
        wav2,
        sr,
        start1,
        start2,
        template_dur=search_dur,
        search_dur=2 * search_dur,
    )

    # Clean up and return
    wav1.unlink(missing_ok=True)
    wav2.unlink(missing_ok=True)

    if not args.silent:
        print(f"Best match at {offset:.2f}s into video2 search clip")
        print(f"To sync, start video2 at {synced_time:.2f}s ({format_seconds(synced_time)})")
    else:
        print(f"{synced_time:.2f}")
