#!/usr/bin/env python3
"""Synthesise the bugle and air-horn samples (no third-party audio, so no licence question).

Pure stdlib: writes 16-bit mono WAVs, then ffmpeg converts them to MP3.
Usage: python3 tools/synth-horns.py [out_dir]   (default: sounds/horns)
"""
import math
import random
import struct
import subprocess
import sys
import wave
from pathlib import Path

SR = 44100


def brass(freq, dur, harmonics=12, bright=1.0, vibrato=0.0, attack=0.03, release=0.06):
    """Additive brass-ish tone: harmonics at ~1/n, a fast attack and a short release."""
    n = int(SR * dur)
    out = []
    for i in range(n):
        t = i / SR
        f = freq * (1 + vibrato * math.sin(2 * math.pi * 5.5 * t))
        s = 0.0
        for h in range(1, harmonics + 1):
            s += (bright ** (h - 1)) / h * math.sin(2 * math.pi * f * h * t)
        env = min(1.0, t / attack) * min(1.0, (dur - t) / release)
        out.append(s * max(env, 0.0))
    return out


def silence(dur):
    return [0.0] * int(SR * dur)


def mix(*tracks):
    n = max(len(t) for t in tracks)
    return [sum(t[i] for t in tracks if i < len(t)) for i in range(n)]


def write(path, samples, gain=0.9):
    peak = max(abs(s) for s in samples) or 1.0
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(s / peak * gain * 32767)) for s in samples))


def bugle():
    # "Charge!": G4 C5 E5 G5 . E5 G5 — notes of the natural bugle's harmonic series.
    G4, C5, E5, G5 = 392.0, 523.25, 659.25, 783.99
    notes = [(G4, 0.16), (C5, 0.16), (E5, 0.16), (G5, 0.32), (None, 0.06), (E5, 0.16), (G5, 0.7)]
    out = []
    for f, d in notes:
        out += silence(d) if f is None else brass(f, d, harmonics=10, bright=0.92, vibrato=0.003)
        out += silence(0.015)
    return out


def air_horn():
    # Stadium air horn: three blasts of a slightly detuned, very bright dyad.
    random.seed(7)
    out = []
    for dur in (0.45, 0.45, 1.3):
        a = brass(415.0, dur, harmonics=18, bright=0.97, attack=0.01, release=0.04)
        b = brass(523.0, dur, harmonics=18, bright=0.97, attack=0.01, release=0.04)
        c = brass(419.0, dur, harmonics=18, bright=0.97, attack=0.01, release=0.04)
        blast = mix(a, b, c)
        blast = [math.tanh(2.5 * s) for s in blast]  # saturate: makes it rasp
        out += blast + silence(0.12)
    return out


def main():
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "sounds/horns")
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, fn in (("bugle", bugle), ("air-horn", air_horn)):
        wav = out_dir / f"{name}.wav"
        write(wav, fn())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav),
                        "-codec:a", "libmp3lame", "-q:a", "4", str(out_dir / f"{name}.mp3")], check=True)
        wav.unlink()
        print(out_dir / f"{name}.mp3")


if __name__ == "__main__":
    main()
