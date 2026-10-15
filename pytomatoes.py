#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pygame-ce>=2.4", "numpy>=1.26"]
# ///
"""🍅 TOMATOES — un tomate del tamaño de una casa, un cocinero diminuto con
guantes de boxeo y noventa segundos. Todo en un único fichero.

Rufo, pinche de cocina bajito y testarudo, se enfrenta a tomates gigantes que
avisan antes de cada ataque. Esquivar, castigar, repetir. Cero recursos
externos: gráficos, luces, partículas, música y efectos se generan por código.

    uv run pytomatoes.py               # jugar
    python pytomatoes.py --selftest    # partida simulada por un bot, sin ventana
    python pytomatoes.py --shots DIR   # capturas PNG de cada pantalla (CI)

Controles: A/D o ←/→ moverse · W/↑/Espacio saltar (doble salto) · S/↓ agacharse
J jab (mantener: golpe cargado) · ↓+J jab bajo · K gancho · ↑+J gancho ascendente
↓+J en el aire: martillo · Shift/L esquiva · P/Esc pausa · F11 pantalla completa
B bloom · M silencio · F3 depuración.

Menú con dificultad, opciones (volúmenes, sacudida, destellos, vibración…),
trucos (vidas infinitas, reloj congelado, golpe de titán, nivel inicial,
Rufo cabezón…), tabla de récords con iniciales, modo demo y tutorial. Tomates especiales:
verde blindado (niveles 4, 8…), podrido (6, 10…) y enjambres de cherrys (7+).
Configuración, opciones y récords en ~/.tomatoes/.

Licencia MIT.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import tempfile
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import numpy as np

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════
# 1. CONSTANTES
# ═══════════════════════════════════════════════════════════════════════════

W, H = 1280, 720
FLOOR = 640  # línea donde se apoyan Rufo y el tomate
WALL_L, WALL_R = 40, 1240
PHYS_HZ = 120  # física a paso fijo
DT = 1.0 / PHYS_HZ
FRAME = 1.0 / 60  # los tiempos de golpe del diseño están en fotogramas a 60 FPS

ROUND_TIME = 90.0
MAX_HEARTS = 3
BUFFER = 0.10  # búfer de entrada
COYOTE = 0.10
COMBO_WINDOW = 1.2
PERFECT_WINDOW = 0.15

# Rufo
RUFO_W, RUFO_H, CROUCH_H = 30, 70, 42
RUN_MAX = 430.0
ACC_GROUND, DEC_GROUND, ACC_AIR = 5600.0, 7000.0, 3600.0
GRAVITY = 3200.0
JUMP_V, DJUMP_V = 1180.0, 1160.0
CUT_MULT, FALL_MULT, MAX_FALL = 2.6, 1.35, 1650.0
DASH_T, DASH_V, DASH_CD, DASH_EXTEND = 0.25, 980.0, 0.8, 0.45
INV_HURT = 1.2
BOUNCE_V = 760.0

# Golpes: (preparación, activo, recuperación) en fotogramas a 60 FPS.
# box = caja de golpe local (x0, y0, x1, y1) con Rufo mirando a la derecha y
# el origen en sus pies (y negativa hacia arriba).
ATTACKS: dict[str, dict] = {
    "jab": dict(f=(3, 3, 8), dmg=1, pts=10, box=(6, -62, 60, -30), stop=0.035, shake=0.16, knock=20, snd="jab"),
    "hook": dict(f=(7, 4, 14), dmg=2, pts=25, box=(2, -72, 66, -26), stop=0.05, shake=0.28, knock=190, snd="hook"),
    "upper": dict(f=(6, 5, 16), dmg=2, pts=25, box=(-2, -116, 48, -40), stop=0.05, shake=0.3, knock=40, snd="hook"),
    "charge": dict(f=(0, 6, 20), dmg=3, pts=15, box=(4, -70, 84, -24), stop=0.07, shake=0.5, knock=300, snd="heavy"),
    "hammer": dict(f=(5, 8, 18), dmg=3, pts=40, box=(-30, -26, 36, 34), stop=0.06, shake=0.45, knock=0, snd="heavy"),
}

# Tomate
TOMATO_ASPECT = 0.9  # ligeramente achatado
TELE = {"roll": 0.6, "bounce": 0.35, "jet": 0.5, "seeds": 0.7, "cherry": 0.6}
CHERRY_R = 17
KIND_NAMES = {"roja": "TOMATE", "verde": "TOMATE VERDE BLINDADO", "podrida": "TOMATE PODRIDO"}
ROT_JUICE = (118, 74, 26)

# Dificultad: tiempos de aviso, pausas, velocidad, daño de Rufo y puntuación
DIFFICULTY: dict[str, dict[str, float]] = {
    "Fácil": dict(tele=1.3, pause=1.35, speed=0.85, dmg=1.25, score=0.75),
    "Normal": dict(tele=1.0, pause=1.0, speed=1.0, dmg=1.0, score=1.0),
    "Difícil": dict(tele=0.85, pause=0.8, speed=1.12, dmg=1.0, score=1.5),
}
DIFF_ORDER = ["Fácil", "Normal", "Difícil"]

OPT_DEFAULT: dict = {
    "difficulty": "Normal",
    "music": 7,
    "sfx": 8,
    "shake": 100,
    "flashes": True,
    "bloom": True,
    "rumble": True,
    "fullscreen": False,
    "tutorial": True,
}
MENU_MAIN = ["JUGAR", "DIFICULTAD", "OPCIONES", "TRUCOS", "RÉCORDS", "SALIR"]
# Trucos: (texto del menú, clave). Con cualquiera activo (salvo los estéticos)
# la puntuación no entra en la tabla de récords.
CHEATS = [
    ("Vidas infinitas", "infinite"),
    ("Reloj congelado", "freeze"),
    ("Golpe de titán (daño ×3)", "titan"),
    ("Punto débil gigante", "bigweak"),
    ("Esquiva sin espera", "nodash_cd"),
    ("Empezar en el nivel", "start_level"),
    ("Velocidad del juego", "speed"),
    ("Rufo cabezón", "bighead"),
    ("Tomates arcoíris", "rainbow"),
]
CHEAT_DEFAULT: dict = {
    "infinite": False,
    "freeze": False,
    "titan": False,
    "bigweak": False,
    "nodash_cd": False,
    "start_level": 1,
    "speed": 100,
    "bighead": False,
    "rainbow": False,
}
COSMETIC_CHEATS = {"bighead", "rainbow"}
MENU_CHEATS = [c[0] for c in CHEATS] + ["Desactivar todos", "Volver"]
MENU_OPTIONS = ["Dificultad", "Música", "Efectos", "Sacudida de cámara", "Destellos", "Bloom", "Vibración del mando", "Pantalla completa", "Tutorial", "Volver"]
DEMO_IDLE = 20.0  # segundos quieto en el título antes del modo demo


def tomato_radius(level: int) -> int:
    return min(220 + 12 * (level - 1), 320)


def tomato_kind(level: int) -> str:
    """Cada cuatro niveles, un tomate especial."""
    if level % 4 == 0:
        return "verde"
    if level >= 6 and level % 4 == 2:
        return "podrida"
    return "roja"
STUN_T = 0.8
HOVER_T = 0.8  # la sombra avisa del bote durante este tiempo

# Paleta
INK = (22, 14, 18)
JUICE = (205, 22, 28)
JUICE_HI = (255, 96, 80)
GOLD = (255, 205, 90)
WHITE = (255, 255, 255)

CFG_DIR = Path.home() / ".tomatoes"

DEFAULT_KEYS: dict[str, list[str]] = {
    "left": ["a", "left"],
    "right": ["d", "right"],
    "up": ["w", "up"],
    "down": ["s", "down"],
    "jump": ["w", "up", "space"],
    "jab": ["j"],
    "hook": ["k"],
    "dash": ["left shift", "right shift", "l"],
    "pause": ["p", "escape"],
    "fullscreen": ["f11"],
    "bloom": ["b"],
    "mute": ["m"],
    "debug": ["f3"],
    "confirm": ["return", "space", "j"],
}
# Mando con mapeo SDL estándar (Xbox): A=0, X=2, Y=3, RB=5, Start=7
PAD_BUTTONS: dict[int, list[str]] = {0: ["jump", "confirm"], 2: ["jab", "confirm"], 3: ["hook"], 5: ["dash"], 7: ["pause"]}


# ═══════════════════════════════════════════════════════════════════════════
# 2. UTILIDADES
# ═══════════════════════════════════════════════════════════════════════════


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def approach(v: float, target: float, delta: float) -> float:
    if v < target:
        return min(v + delta, target)
    return max(v - delta, target)


def sign(v: float) -> int:
    return (v > 0) - (v < 0)


def smooth(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def ease_out(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return 1 - (1 - t) ** 3


def back_out(t: float) -> float:
    t = clamp(t, 0.0, 1.0) - 1
    return 1 + 2.70158 * t**3 + 1.70158 * t**2


def elastic(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    if t in (0.0, 1.0):
        return t
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi / 3)) + 1


def mix(c1, c2, t: float) -> tuple[int, int, int]:
    t = clamp(t, 0.0, 1.0)
    return (int(c1[0] + (c2[0] - c1[0]) * t), int(c1[1] + (c2[1] - c1[1]) * t), int(c1[2] + (c2[2] - c1[2]) * t))


def scale_c(c, k: float) -> tuple[int, int, int]:
    return (int(clamp(c[0] * k, 0, 255)), int(clamp(c[1] * k, 0, 255)), int(clamp(c[2] * k, 0, 255)))


def lerp2(p, q, t: float) -> tuple[float, float]:
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)


def bezier(p0, p1, p2, t: float) -> tuple[float, float]:
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0], u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])


def rect_ellipse(rect: pygame.Rect, cx: float, cy: float, rx: float, ry: float) -> bool:
    """¿Toca el rectángulo la elipse? Punto más cercano en espacio normalizado."""
    px = clamp(cx, rect.left, rect.right)
    py = clamp(cy, rect.top, rect.bottom)
    dx, dy = (px - cx) / rx, (py - cy) / ry
    return dx * dx + dy * dy <= 1.0


class Spring:
    """Muelle amortiguado: el alma del squash & stretch."""

    __slots__ = ("k", "d", "x", "v", "target")

    def __init__(self, k: float, d: float, x: float = 0.0):
        self.k, self.d, self.x, self.v, self.target = k, d, x, 0.0, x

    def kick(self, dv: float) -> None:
        self.v += dv

    def step(self, dt: float) -> None:
        self.v += (-self.k * (self.x - self.target) - self.d * self.v) * dt
        self.x += self.v * dt


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path: Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # disco de solo lectura, CI...: el juego sigue


# ── Sprites procedurales cacheados ─────────────────────────────────────────

_glow_cache: dict = {}
_blob_cache: dict = {}


def glow(radius: float, color, power: float = 2.0) -> pygame.Surface:
    """Gradiente radial opaco para mezclar en modo aditivo."""
    r = max(2, int(radius))
    key = (r, tuple(color), power)
    s = _glow_cache.get(key)
    if s is None:
        g = np.linspace(-1, 1, 2 * r)
        xx, yy = np.meshgrid(g, g, indexing="ij")
        f = np.clip(1 - np.sqrt(xx * xx + yy * yy), 0, 1) ** power
        arr = (f[..., None] * np.array(color, float)[None, None, :]).astype(np.uint8)
        s = pygame.surfarray.make_surface(arr)
        _glow_cache[key] = s
    return s


def soft_blob(radius: float, color, alpha: int, power: float = 1.5) -> pygame.Surface:
    """Disco con borde suave y transparencia (sombras, moratones, polvo)."""
    r = max(2, int(radius))
    key = (r, tuple(color), alpha, power)
    s = _blob_cache.get(key)
    if s is None:
        s = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)
        g = np.linspace(-1, 1, 2 * r)
        xx, yy = np.meshgrid(g, g, indexing="ij")
        f = np.clip(1 - np.sqrt(xx * xx + yy * yy), 0, 1) ** power
        px = pygame.surfarray.pixels3d(s)
        px[...] = np.array(color, np.uint8)
        del px
        pa = pygame.surfarray.pixels_alpha(s)
        pa[...] = (f * alpha).astype(np.uint8)
        del pa
        _blob_cache[key] = s
    return s


def blit_add(dst: pygame.Surface, src: pygame.Surface, cx: float, cy: float) -> None:
    dst.blit(src, (int(cx - src.get_width() / 2), int(cy - src.get_height() / 2)), special_flags=pygame.BLEND_ADD)


def blit_center(dst: pygame.Surface, src: pygame.Surface, cx: float, cy: float) -> None:
    dst.blit(src, (int(cx - src.get_width() / 2), int(cy - src.get_height() / 2)))


def blur(surf: pygame.Surface, factor: int) -> pygame.Surface:
    w, h = surf.get_size()
    small = pygame.transform.smoothscale(surf, (max(1, w // factor), max(1, h // factor)))
    return pygame.transform.smoothscale(small, (w, h))


# ═══════════════════════════════════════════════════════════════════════════
# 3. AUDIO SINTETIZADO
# ═══════════════════════════════════════════════════════════════════════════


class Audio:
    """Efectos y música generados con numpy al arrancar. Si no hay mezclador,
    el juego sigue mudo sin quejarse."""

    def __init__(self, enabled: bool = True):
        self.ok = False
        self.muted = False
        self.vol_music = 0.7
        self.vol_sfx = 0.8
        self.snd: dict[str, pygame.mixer.Sound] = {}
        self.music: pygame.mixer.Sound | None = None
        self.music_ch: pygame.mixer.Channel | None = None
        if not enabled:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(44100, -16, 2, 512)
            init = pygame.mixer.get_init()
            if not init:
                return
            self.sr, _, self.channels = init
            pygame.mixer.set_num_channels(32)
            pygame.mixer.set_reserved(1)
            self._build()
            self.ok = True
        except Exception:  # noqa: BLE001 — cualquier fallo de audio = juego mudo
            self.ok = False

    # ── síntesis ────────────────────────────────────────────────────────
    def _mk(self, x: np.ndarray, vol: float = 0.9) -> pygame.mixer.Sound:
        x = np.asarray(x, np.float64)
        peak = float(np.max(np.abs(x))) or 1.0
        x = np.tanh(x / peak * 1.2) / math.tanh(1.2) * vol
        a = (x * 32000).astype(np.int16)
        if self.channels == 2:
            a = np.ascontiguousarray(np.repeat(a[:, None], 2, axis=1))
        return pygame.sndarray.make_sound(a)

    def _build(self) -> None:
        sr = self.sr
        rng = np.random.default_rng(7)

        def T(d):
            return np.arange(int(sr * d)) / sr

        def noise(d):
            return rng.standard_normal(int(sr * d))

        def sweep(f0, f1, d, wave="sin"):
            t = T(d)
            f = f0 * (f1 / f0) ** (t / d)
            ph = 2 * np.pi * np.cumsum(f) / sr
            if wave == "tri":
                return 2 / np.pi * np.arcsin(np.sin(ph))
            if wave == "sq":
                return np.tanh(np.sin(ph) * 4)
            return np.sin(ph)

        def env(d, decay, attack=0.002):
            t = T(d)
            return np.exp(-t * decay) * np.clip(t / attack, 0, 1)

        def filt(x, lo=None, hi=None):
            X = np.fft.rfft(x)
            f = np.fft.rfftfreq(len(x), 1 / sr)
            if hi:
                X *= 1 / (1 + (f / hi) ** 4)
            if lo:
                X *= 1 / (1 + (lo / np.maximum(f, 1)) ** 4)
            return np.fft.irfft(X, len(x))

        def add(*xs):
            n = max(len(x) for x in xs)
            out = np.zeros(n)
            for x in xs:
                out[: len(x)] += x
            return out

        def thud(f0, f1, d, decay, click=0.4, body=600):
            return add(
                sweep(f0, f1, d) * env(d, decay),
                filt(noise(d), lo=1500) * env(d, 90) * click,
                filt(noise(d), hi=body) * env(d, decay * 1.5) * 0.6,
            )

        def chime(freqs, step, d=0.35, wave="tri"):
            out = np.zeros(int(sr * (step * len(freqs) + d)))
            for i, f in enumerate(freqs):
                n = sweep(f, f * 1.001, d, wave) * env(d, 9)
                st = int(i * step * sr)
                out[st : st + len(n)] += n
            return out

        s = self.snd
        s["jab"] = self._mk(thud(190, 70, 0.14, 32), 0.55)
        s["hook"] = self._mk(thud(150, 48, 0.22, 18, 0.5, 800), 0.7)
        s["heavy"] = self._mk(thud(120, 34, 0.42, 9, 0.6, 500), 0.85)
        splash = filt(noise(0.45), lo=900, hi=6000) * env(0.45, 11) * (0.6 + 0.4 * np.sin(T(0.45) * 2 * np.pi * 38))
        s["crit"] = self._mk(add(thud(160, 50, 0.3, 14), splash * 0.9, sweep(900, 2100, 0.18) * env(0.18, 16) * 0.35), 0.9)
        s["whiff"] = self._mk(filt(noise(0.12), lo=600, hi=3000) * np.sin(np.linspace(0, np.pi, int(sr * 0.12))), 0.22)
        s["jump"] = self._mk(sweep(320, 640, 0.09, "tri") * env(0.09, 20), 0.22)
        s["djump"] = self._mk(sweep(420, 900, 0.11, "tri") * env(0.11, 18), 0.22)
        s["land"] = self._mk(filt(noise(0.08), hi=420) * env(0.08, 45), 0.35)
        whoosh_t = T(0.24)
        s["dash"] = self._mk(
            filt(noise(0.24), lo=700, hi=4000) * np.sin(np.pi * whoosh_t / 0.24) ** 2
            + sweep(900, 300, 0.24) * env(0.24, 10) * 0.15,
            0.4,
        )
        crackle = filt(noise(0.6) * (rng.random(int(sr * 0.6)) > 0.985) * 6, hi=900)
        s["warn_roll"] = self._mk(add(crackle, sweep(70, 50, 0.6) * env(0.6, 2) * 0.5), 0.6)
        vib = 1 + 0.03 * np.sin(T(0.8) * 2 * np.pi * 9)
        s["warn_bounce"] = self._mk(sweep(380, 1500, 0.8) * vib * np.clip(T(0.8) / 0.05, 0, 1) * 0.6, 0.4)
        bubbles = np.zeros(int(sr * 0.5))
        for i in range(9):
            st = int(i * sr * 0.05 + rng.integers(0, 600))
            b = sweep(rng.uniform(180, 420), rng.uniform(500, 900), 0.06) * env(0.06, 50)
            bubbles[st : st + len(b)] += b[: max(0, len(bubbles) - st)]
        s["warn_jet"] = self._mk(bubbles, 0.5)
        clicks = np.zeros(int(sr * 0.7))
        for i in range(16):
            st = int(rng.uniform(0, 0.66) * sr)
            c = filt(noise(0.012), lo=2500) * env(0.012, 300)
            clicks[st : st + len(c)] += c
        s["warn_seeds"] = self._mk(clicks, 0.45)
        s["slam"] = self._mk(add(sweep(85, 26, 1.0) * env(1.0, 3.5), filt(noise(1.0), hi=280) * env(1.0, 4.5) * 1.2), 1.0)
        s["jet"] = self._mk(filt(noise(0.6), lo=500, hi=5000) * env(0.6, 3, 0.03) * (0.7 + 0.3 * np.sin(T(0.6) * 2 * np.pi * 23)), 0.45)
        s["hurt"] = self._mk(
            add(filt(noise(0.12), hi=900) * env(0.12, 28), sweep(520, 240, 0.35, "tri") * env(0.35, 6) * 0.6), 0.6
        )
        burst_bub = filt(noise(1.4), lo=500, hi=7000) * env(1.4, 3.2) * (0.5 + 0.5 * np.abs(np.sin(T(1.4) * 2 * np.pi * 11)))
        s["burst"] = self._mk(add(sweep(95, 24, 1.6) * env(1.6, 2.6) * 1.2, burst_bub, filt(noise(0.2), hi=1200) * env(0.2, 12)), 1.0)
        s["tick"] = self._mk(np.sin(2 * np.pi * 1250 * T(0.045)) * env(0.045, 70), 0.35)

        s["perfect"] = self._mk(chime([880, 1320, 1760, 2640], 0.045), 0.45)
        s["level"] = self._mk(chime([523, 659, 784, 1047, 1319], 0.08, 0.5), 0.5)
        s["select"] = self._mk(chime([660, 990], 0.05, 0.12), 0.35)
        s["ready"] = self._mk(chime([1568, 2093], 0.04, 0.2), 0.3)
        s["charge"] = self._mk(sweep(180, 520, 0.8, "sq") * (0.6 + 0.4 * np.sin(T(0.8) * 2 * np.pi * 14)) * env(0.8, 1.2, 0.05), 0.18)
        s["seed_hit"] = self._mk(sweep(1400, 700, 0.05) * env(0.05, 60), 0.3)
        s["over"] = self._mk(chime([523, 415, 330, 262], 0.16, 0.6), 0.5)
        s["wall"] = self._mk(thud(110, 40, 0.3, 12, 0.3, 400), 0.7)
        pop = add(sweep(260, 950, 0.07, "tri") * env(0.07, 40), filt(noise(0.05), lo=1500) * env(0.05, 120) * 0.5)
        s["pop"] = self._mk(pop, 0.45)
        trio = np.zeros(int(sr * 0.6))
        for i in range(3):
            st = int(i * 0.17 * sr)
            trio[st : st + len(pop)] += pop
        s["warn_cherry"] = self._mk(trio, 0.5)
        ring = sum(np.sin(2 * np.pi * f * T(0.5)) * np.exp(-T(0.5) * d) for f, d in ((1840, 9), (2710, 12), (4130, 16)))
        s["clonk"] = self._mk(add(thud(220, 90, 0.12, 30, 0.8), ring * 0.5), 0.6)
        s["ripe"] = self._mk(add(chime([523, 784, 1047, 1568], 0.06, 0.6), sweep(200, 900, 0.5) * env(0.5, 4) * 0.3), 0.6)
        self.music = self._mk(self._compose(), 0.55)

    def _compose(self) -> np.ndarray:
        """Bucle de 8 compases: bombo, caja, charles, bajo y acordes de pluck."""
        sr = self.sr
        rng = np.random.default_rng(3)
        bpm = 118
        beat = 60 / bpm
        n = int(sr * beat * 32)
        out = np.zeros(n)

        def put(x, t0):
            st = int(t0 * sr)
            if st >= n:
                return
            m = min(len(x), n - st)
            out[st : st + m] += x[:m]

        def tone(f, d, decay, wave="saw"):
            t = np.arange(int(sr * d)) / sr
            if wave == "saw":
                x = 2 * ((t * f) % 1) - 1
                k = np.ones(9) / 9
                x = np.convolve(x, k, mode="same")
            elif wave == "sin":
                x = np.sin(2 * np.pi * f * t)
            else:
                x = np.tanh(3 * np.sin(2 * np.pi * f * t))
            return x * np.exp(-t * decay) * np.clip(t / 0.004, 0, 1)

        kick_t = np.arange(int(sr * 0.3)) / sr
        kick = np.sin(2 * np.pi * np.cumsum(50 + 110 * np.exp(-kick_t * 30)) / sr) * np.exp(-kick_t * 9)
        snare = rng.standard_normal(int(sr * 0.18)) * np.exp(-np.arange(int(sr * 0.18)) / sr * 22) * 0.35
        hat = rng.standard_normal(int(sr * 0.04))
        hat = np.diff(hat, prepend=0) * np.exp(-np.arange(len(hat)) / sr * 90) * 0.12
        roots = [45, 45, 41, 43, 45, 45, 48, 43]  # La menor con giros de cocina canalla
        for bar in range(8):
            t_bar = bar * 4 * beat
            r = roots[bar]
            for b in range(4):
                if b in (0, 2) or (b == 3 and bar % 2):
                    put(kick, t_bar + b * beat)
                if b in (1, 3):
                    put(snare, t_bar + b * beat)
                for h8 in range(2):
                    put(hat * (1.0 if h8 else 0.6), t_bar + b * beat + h8 * beat / 2)
            for step_i, (off, semi) in enumerate([(0, 0), (0.75, 0), (1.5, 12), (2, 0), (2.75, 7), (3.5, 10)]):
                f = 440 * 2 ** ((r + semi - 69 + 12) / 12) / 2
                put(tone(f, beat * 0.6, 7, "sq") * 0.32, t_bar + off * beat)
            chord = [r + 24, r + 27, r + 31] if bar % 4 != 3 else [r + 24, r + 28, r + 31]
            for off in (0.5, 1.5, 2.5):
                for c in chord:
                    put(tone(440 * 2 ** ((c - 69) / 12), beat * 0.45, 10) * 0.07, t_bar + off * beat)
        return out

    # ── reproducción ───────────────────────────────────────────────────
    def play(self, name: str, vol: float = 1.0) -> None:
        if not self.ok or self.muted:
            return
        snd = self.snd.get(name)
        if snd is not None:
            ch = snd.play()
            if ch is not None:
                ch.set_volume(min(1.0, vol) * self.vol_sfx)

    def start_music(self) -> None:
        if not self.ok or self.music is None:
            return
        self.music_ch = pygame.mixer.Channel(0)
        self.music_ch.play(self.music, loops=-1)
        self.music_ch.set_volume(0.0 if self.muted else 0.47 * self.vol_music)

    def set_volumes(self, music: int, sfx: int) -> None:
        self.vol_music, self.vol_sfx = clamp(music / 10, 0, 1), clamp(sfx / 10, 0, 1)
        if self.ok and self.music_ch is not None:
            self.music_ch.set_volume(0.0 if self.muted else 0.47 * self.vol_music)

    def toggle_mute(self) -> None:
        self.muted = not self.muted
        if self.ok:
            if self.muted:
                pygame.mixer.stop()
            if not self.muted:
                self.start_music()


# ═══════════════════════════════════════════════════════════════════════════
# 4. ENTRADA: teclado, mando, reasignación
# ═══════════════════════════════════════════════════════════════════════════


class Input:
    def __init__(self, keymap: dict[str, list[str]]):
        self.code_actions: dict[int, list[str]] = {}
        for action, names in keymap.items():
            for name in names:
                try:
                    code = pygame.key.key_code(name)
                except (ValueError, pygame.error):
                    continue
                self.code_actions.setdefault(code, []).append(action)
        self.keys_down: set[int] = set()
        self.pad: pygame.joystick.JoystickType | None = None
        self.pad_buttons: set[int] = set()
        self.pad_axes = [0.0, 0.0]
        self.pad_hat = (0, 0)
        self.virtual: set[str] = set()  # para el bot del selftest
        self.last_dir = {"left": False, "right": False, "up": False, "down": False}

    def held(self, action: str) -> bool:
        if action in self.virtual:
            return True
        for code in self.keys_down:
            if action in self.code_actions.get(code, ()):
                return True
        if self.pad is not None:
            ax, ay = self.pad_axes
            hx, hy = self.pad_hat
            if action == "left" and (ax < -0.45 or hx < 0):
                return True
            if action == "right" and (ax > 0.45 or hx > 0):
                return True
            if action == "up" and (ay < -0.6 or hy > 0):
                return True
            if action == "down" and (ay > 0.6 or hy < 0):
                return True
            for b in self.pad_buttons:
                if action in PAD_BUTTONS.get(b, ()):
                    return True
        return False

    def event(self, e: pygame.event.Event) -> list[str]:
        """Procesa un evento y devuelve las acciones recién pulsadas."""
        if e.type == pygame.KEYDOWN:
            self.keys_down.add(e.key)
            return list(self.code_actions.get(e.key, ()))
        if e.type == pygame.KEYUP:
            self.keys_down.discard(e.key)
        elif e.type == pygame.JOYDEVICEADDED and self.pad is None:
            try:
                self.pad = pygame.joystick.Joystick(e.device_index)
            except pygame.error:
                self.pad = None
        elif e.type == pygame.JOYDEVICEREMOVED:
            self.pad = None
            self.pad_buttons.clear()
            return ["pad_lost"]
        elif e.type == pygame.JOYBUTTONDOWN:
            self.pad_buttons.add(e.button)
            return list(PAD_BUTTONS.get(e.button, ()))
        elif e.type == pygame.JOYBUTTONUP:
            self.pad_buttons.discard(e.button)
        elif e.type == pygame.JOYAXISMOTION and e.axis in (0, 1):
            old = self.pad_axes[e.axis]
            self.pad_axes[e.axis] = e.value
            neg, pos = ("left", "right") if e.axis == 0 else ("up", "down")
            out = []
            if e.value < -0.6 <= old:
                out.append(neg)
            if e.value > 0.6 >= old:
                out.append(pos)
            return out
        elif e.type == pygame.JOYHATMOTION and e.hat == 0:
            (ox, oy), (hx, hy) = self.pad_hat, e.value
            self.pad_hat = e.value
            out = []
            if hx < 0 <= ox:
                out.append("left")
            if hx > 0 >= ox:
                out.append("right")
            if hy > 0 >= oy:
                out.append("up")
            if hy < 0 <= oy:
                out.append("down")
            return out
        return []

    def clear(self) -> None:
        self.keys_down.clear()
        self.pad_buttons.clear()


# ═══════════════════════════════════════════════════════════════════════════
# 5. RUFO
# ═══════════════════════════════════════════════════════════════════════════


class Rufo:
    def __init__(self, x: float):
        self.x, self.y = x, float(FLOOR)
        self.vx = self.vy = 0.0
        self.facing = 1
        self.on_ground, self.on_tomato = True, False
        self.coyote = 0.0
        self.air_jumps = 1
        self.air_dash = True
        self.upper_lift = True
        self.jumping = False
        self.state = "normal"  # normal, attack, charge, dash, hurt, dead
        self.atk = ""
        self.atk_t = 0.0
        self.atk_hit = False
        self.atk_dmg = 0
        self.atk_fired = False
        self.atk_low = False
        self.chain = 0
        self.chain_t = 0.0
        self.j_armed = False
        self.j_hold = 0.0
        self.charge_snd = False
        self.dash_t = 0.0
        self.dash_cd = 0.0
        self.dash_dir = 1
        self.dash_start = -9.0
        self.dash_ext = 0.0
        self.inv = 0.0
        self.hurt_t = 0.0
        self.slow = 0.0
        self.crouch = False
        self.cr = Spring(500, 40)  # agachado 0..1
        self.sq = Spring(320, 15)  # aplastamiento (+ = chato)
        self.hat = Spring(140, 7)  # inclinación del gorro
        self.run_phase = 0.0
        self.time = 0.0
        self.trail: list[tuple[float, float, float]] = []
        self.juice = 0.0
        self.stains: list[tuple[float, float, float]] = []
        self.blink_t = 2.0
        self.ghost_t = 0.0
        self.flash = 0.0
        self.bighead = False
        self.step_t = 0.0
        self.prev = (x, float(FLOOR))
        self.last_sprite: pygame.Surface | None = None

    # ── consultas ───────────────────────────────────────────────────────
    def height(self) -> float:
        return CROUCH_H if self.crouch else RUFO_H

    def hurtbox(self) -> pygame.Rect:
        h = self.height()
        return pygame.Rect(int(self.x - RUFO_W / 2), int(self.y - h), RUFO_W, int(h))

    def phase(self) -> tuple[str, float]:
        """Fase del golpe actual y progreso 0..1 dentro de ella."""
        su, ac, rc = (f * FRAME for f in ATTACKS[self.atk]["f"])
        t = self.atk_t
        if t < su:
            return "su", t / su if su else 1.0
        if t < su + ac:
            return "ac", (t - su) / ac
        if t < su + ac + rc:
            return "rc", (t - su - ac) / rc
        return "end", 1.0

    def hitbox(self) -> pygame.Rect | None:
        return None if self.atk_hit else self.active_box()

    def active_box(self) -> pygame.Rect | None:
        """Caja del golpe activo (aunque ya haya conectado con el tomate)."""
        if self.state != "attack" or self.phase()[0] != "ac":
            return None
        x0, y0, x1, y1 = ATTACKS[self.atk]["box"]
        if self.atk_low:  # jab agachado: barre a ras de suelo
            y0, y1 = -34, -4
        if self.facing < 0:
            x0, x1 = -x1, -x0
        return pygame.Rect(int(self.x + x0), int(self.y + y0), x1 - x0, y1 - y0)

    def vulnerable(self) -> bool:
        return self.inv <= 0 and self.state not in ("dash", "dead")

    # ── acciones ────────────────────────────────────────────────────────
    def start_attack(self, g: "Game", name: str) -> None:
        if name == "jab":
            self.chain = self.chain + 1 if self.chain == 1 and self.chain_t > 0 else 1
        elif name == "hook":
            self.chain = 3 if self.chain == 2 and self.chain_t > 0 else 0
        else:
            self.chain = 0
        self.chain_t = 0.6
        self.state = "attack"
        self.atk = name
        self.atk_t = 0.0
        self.atk_hit = False
        self.atk_fired = False
        self.atk_low = name == "jab" and self.crouch
        self.trail.clear()
        if name == "charge":
            self.atk_dmg = 3 + round(3 * clamp((self.j_hold - 0.4) / 0.8, 0, 1))
        else:
            self.atk_dmg = ATTACKS[name]["dmg"]
        if name in ("jab", "hook") and self.on_ground:
            self.vx += self.facing * (70 if name == "jab" else 150)

    def chain_ok(self, want: str) -> str | None:
        """¿Se puede cancelar la recuperación con este golpe? (Jab→Jab→Gancho→Ascendente)"""
        if self.chain_t <= 0:
            return None
        if self.atk == "jab" and self.chain == 1 and want == "jab":
            return "jab"
        if self.atk == "jab" and self.chain == 2 and want == "hook":
            return "hook"
        if self.atk == "hook" and self.chain == 3 and want in ("jab", "upper"):
            return "upper"
        return None

    def jump(self, g: "Game") -> None:
        self.vy = -JUMP_V * (0.82 if self.slow > 0 else 1.0)
        self.on_ground = self.on_tomato = False
        self.coyote = 0.0
        self.jumping = True
        self.sq.kick(-4.5)
        g.audio.play("jump")
        g.fx.puff(self.x, self.y, 5)

    def double_jump(self, g: "Game") -> None:
        self.vy = -DJUMP_V * (0.82 if self.slow > 0 else 1.0)
        self.air_jumps -= 1
        self.jumping = True
        self.sq.kick(-4.0)
        g.audio.play("djump")
        g.fx.ring(self.x, self.y - 6, 40, (255, 240, 220), 0.25, 3, flat=0.35)

    def land(self, g: "Game", vy: float) -> None:
        self.jumping = False
        if vy > 250:
            self.sq.kick(min(6.0, vy * 0.004))
            self.hat.kick(-sign(self.vx) * 1.5)
        if vy > 650:
            g.audio.play("land", min(1.0, vy / 1400))
            g.fx.puff(self.x, self.y, 6)

    # ── paso de física ─────────────────────────────────────────────────
    def step(self, g: "Game", dt: float) -> None:
        inp = g.inp
        self.time += dt
        self.dash_cd = max(0.0, self.dash_cd - dt)
        self.inv = max(0.0, self.inv - dt)
        self.slow = max(0.0, self.slow - dt)
        self.juice = max(0.0, self.juice - dt)
        self.flash = max(0.0, self.flash - dt * 5)
        self.chain_t = max(0.0, self.chain_t - dt)
        self.cr.step(dt)
        self.sq.step(dt)
        self.hat.target = clamp(-self.vx / RUN_MAX * 0.25, -0.35, 0.35)
        self.hat.step(dt)
        self.blink_t -= dt
        if self.blink_t < -0.12:
            self.blink_t = random.uniform(1.8, 4.0)

        if self.state == "dead":
            self.vx = approach(self.vx, 0, 1400 * dt)
            self.vy = min(self.vy + GRAVITY * dt, MAX_FALL)
            self._integrate(g, dt)
            return

        mx = int(inp.held("right")) - int(inp.held("left"))
        up, down = inp.held("up"), inp.held("down")

        # Golpe cargado: se mide cuánto tiempo sigue apretado J tras el jab
        if self.j_armed:
            if inp.held("jab"):
                self.j_hold += dt
            else:
                self.j_armed = False
                if self.state == "charge":
                    self.start_attack(g, "charge")
        if (
            self.j_armed
            and self.j_hold >= 0.4
            and self.on_ground
            and (self.state == "normal" or (self.state == "attack" and self.atk == "jab" and self.phase()[0] == "rc"))
        ):
            self.state = "charge"
            g.audio.play("charge")
            self.charge_snd = False
        if self.state == "charge":
            if self.j_hold >= 1.2 and not self.charge_snd:
                self.charge_snd = True
                g.audio.play("ready")
            if random.random() < 0.5:
                g.fx.charge_mote(self.x + self.facing * 10, self.y - 40)

        if self.state == "hurt":
            self.hurt_t -= dt
            if self.hurt_t <= 0:
                self.state = "normal"
            mx = 0

        free = self.state in ("normal", "charge")
        in_rc = self.state == "attack" and self.phase()[0] == "rc"
        self.crouch = down and self.on_ground and (self.state in ("normal", "charge") or (self.state == "attack" and self.atk_low))
        self.cr.target = 1.0 if self.crouch else 0.0
        if free and mx:
            self.facing = mx

        # Esquiva rápida (cancela la recuperación de un golpe)
        if (free or in_rc) and self.dash_cd <= 0 and (self.on_ground or self.air_dash) and g.consume("dash"):
            self.state = "dash"
            self.dash_t = DASH_T
            self.dash_ext = 0.0
            self.dash_dir = mx or self.facing
            self.facing = self.dash_dir
            self.dash_start = g.t
            self.dash_cd = 0.12 if g.cheat("nodash_cd") else DASH_CD
            if not self.on_ground:
                self.air_dash = False
            self.j_armed = False
            self.crouch = False
            g.audio.play("dash")
            g.fx.puff(self.x, self.y, 4)

        # Salto con coyote time y búfer
        if (self.state == "normal" or in_rc) and g.peek("jump"):
            if self.on_ground or self.coyote > 0:
                g.consume("jump")
                self.state = "normal"
                self.jump(g)
            elif self.air_jumps > 0 and self.state == "normal":
                g.consume("jump")
                self.double_jump(g)

        # Golpes con búfer de entrada
        want = None
        if g.peek("jab"):
            if not self.on_ground and down:
                want = "hammer"
            elif up:
                want = "upper"
            else:
                want = "jab"
            if want == "jab" and self.chain == 3 and self.chain_t > 0 and self.atk == "hook":
                want = "upper"
            key = "jab"
        elif g.peek("hook"):
            want, key = "hook", "hook"
        if want is not None:
            started = None
            if self.state == "normal":
                started = want
            elif in_rc:
                started = self.chain_ok(want)
            if started:
                g.consume(key)
                if key == "jab":
                    self.j_armed = True
                    self.j_hold = 0.0
                self.start_attack(g, started)

        # Movimiento por estado
        if self.state == "dash":
            if not g.dash_overlap:
                self.dash_t -= dt
            else:
                self.dash_ext += dt
                if self.dash_ext > DASH_EXTEND:
                    self.dash_t -= dt
            self.vx = self.dash_dir * DASH_V
            self.vy = 0.0
            self.ghost_t -= dt
            if self.dash_t <= 0:
                self.state = "normal"
                self.vx *= 0.45
        else:
            if self.state == "attack":
                ph, _ = self.phase()
                if ph == "ac" and not self.atk_fired:
                    self.atk_fired = True
                    g.audio.play("whiff")
                    if self.atk == "hammer":
                        self.vy = 1400.0
                        self.vx *= 0.3
                    elif self.atk == "upper" and self.upper_lift:
                        self.upper_lift = False
                        self.vy = min(self.vy, -560.0)
                        self.on_ground = False
                    elif self.atk == "charge":
                        self.vx += self.facing * 260
                if self.on_ground:
                    self.vx = approach(self.vx, 0, DEC_GROUND * 0.6 * dt * (0.08 if g.slipping else 1.0))
                else:
                    self.vx = approach(self.vx, mx * RUN_MAX * 0.6, ACC_AIR * 0.5 * dt)
                if ph in ("ac", "rc"):
                    lx, ly = glove_world(self)
                    self.trail.append((lx, ly, self.time))
                self.atk_t += dt
                if self.phase()[0] == "end":
                    self.state = "normal"
                    self.chain_t = 0.35
            else:
                maxs = RUN_MAX
                if self.slow > 0:
                    maxs *= 0.5
                if self.crouch:
                    maxs = 0.0
                if self.state == "charge":
                    maxs *= 0.3
                target = mx * maxs
                if self.on_ground:
                    acc = ACC_GROUND if (mx and sign(self.vx) in (0, mx)) else DEC_GROUND
                    if g.slipping:
                        acc *= 0.1  # charco del tomate podrido
                else:
                    acc = ACC_AIR
                self.vx = approach(self.vx, target, acc * dt)
            grav = GRAVITY
            if self.vy < 0 and self.jumping and not inp.held("jump"):
                grav *= CUT_MULT  # salto de altura variable
            elif self.vy > 0:
                grav *= FALL_MULT
            if self.state == "attack" and self.atk == "hammer" and self.phase()[0] == "su":
                grav *= 0.15  # se queda suspendido un instante antes del picado
                self.vy *= 0.85
            self.vy = min(self.vy + grav * dt, MAX_FALL)

        if self.on_ground and abs(self.vx) > 20:
            self.run_phase += abs(self.vx) * dt * 0.045
            # Polvo de pisadas
            self.step_t += abs(self.vx) * dt
            if self.step_t > 70 and not self.on_tomato:
                self.step_t = 0.0
                g.fx.p.append([PUFF, self.x - self.facing * 8, self.y - 2, -self.vx * 0.15, -20, 0.35, 0.35, 5, (130, 120, 115), 0])
        while len(self.trail) > 10:
            self.trail.pop(0)
        self._integrate(g, dt)

    def _integrate(self, g: "Game", dt: float) -> None:
        self.x += self.vx * dt
        self.y += self.vy * dt
        half = RUFO_W / 2
        if self.x - half < WALL_L:
            self.x = WALL_L + half
            self.vx = max(self.vx, 0)
        elif self.x + half > WALL_R:
            self.x = WALL_R - half
            self.vx = min(self.vx, 0)
        was_ground = self.on_ground
        self.on_ground = self.on_tomato = False
        if self.y >= FLOOR:
            self.y = float(FLOOR)
            if self.vy > 0:
                self.land(g, self.vy)
                if self.state == "attack" and self.atk == "hammer" and self.phase()[0] in ("su", "ac"):
                    g.hammer_ground(self)
            self.vy = 0.0
            self.on_ground = True
        self._ground_flags(was_ground, dt)

    def _ground_flags(self, was_ground: bool, dt: float) -> None:
        if self.on_ground:
            self.coyote = COYOTE
            self.air_jumps = 1
            self.air_dash = True
            self.upper_lift = True
        elif was_ground:
            self.coyote = COYOTE - dt
        else:
            self.coyote -= dt


def rounded_box(x0, y0, x1, y1, rad, flare=0.0) -> list[tuple[float, float]]:
    """Rectángulo de esquinas redondeadas como polígono (el torso de Rufo)."""
    pts = []
    for cx, cy, a0 in ((x1 - rad, y0 + rad, -90), (x1 - rad + flare, y1 - rad, 0), (x0 + rad - flare, y1 - rad, 90), (x0 + rad, y0 + rad, 180)):
        for i in range(5):
            a = math.radians(a0 + i * 22.5)
            pts.append((cx + math.cos(a) * rad, cy + math.sin(a) * rad))
    return pts


def glove_pose(r: Rufo) -> dict:
    """Pose procedural de Rufo en coordenadas locales (mirando a la derecha,
    origen en los pies). Devuelve guantes, inclinación y gestos."""
    cr = clamp(r.cr.x, 0, 1)
    sh_y = -46 + cr * 15
    gf, gb = (15.0, -8.0), (8.0, -13.0)  # guardia
    lean = clamp(r.vx * r.facing / RUN_MAX, -1, 1) * 0.13
    mouth = "flat"
    if r.state == "normal" and r.on_ground and abs(r.vx) > 40:
        p = math.sin(r.run_phase * 2)
        gf = (14 + 5 * p, -4 - 3 * abs(p))
        gb = (6 - 5 * p, -9 + 2 * abs(p))
    elif r.state == "normal" and r.on_ground:
        bob = math.sin(r.time * 3.4) * 1.3
        gf = (15.0, -8 + bob)
        gb = (8.0, -13 - bob)
    elif r.state == "normal":
        gf, gb = ((17.0, -15.0), (5.0, -20.0)) if r.vy < 0 else ((18.0, -6.0), (-2.0, -9.0))
    if r.state == "attack":
        ph, p = r.phase()
        k = r.atk
        wind, ext, ctrl, arm = {
            "jab": ((9, -5), (47, -7), None, "f"),
            "hook": ((-12, -4), (46, -14), (30, -36), "b"),
            "upper": ((6, 12), (18, -44), (30, 0), "f"),
            "charge": ((-18, -4), (62, -6), None, "b"),
            "hammer": ((0, -42), (16, 30), (22, -14), "both"),
        }[k]
        if r.atk_low:
            wind, ext = (9, 6), (46, 20)
        guard = gf if arm == "f" else gb
        if ph == "su":
            pos = lerp2(guard, wind, ease_out(p))
        elif ph == "ac":
            q = back_out(min(1.0, p * 1.6))
            pos = bezier(wind, ctrl, ext, q) if ctrl else lerp2(wind, ext, q)
            mouth = "grit"
        else:
            pos = lerp2(ext, guard, smooth(p))
        if arm == "f":
            gf = pos
        elif arm == "b":
            gb = pos
            gf = (10.0, -16.0)
        else:
            gf = pos
            gb = (pos[0] - 9, pos[1] + 2)
        lean += {"su": -0.06, "ac": 0.14, "rc": 0.05, "end": 0.0}[ph] * (0.3 if k == "hammer" else 1)
    elif r.state == "charge":
        j = math.sin(r.time * 70) * 1.5
        gb = (-17 + j, -5.0)
        gf = (12.0, -14.0)
        lean -= 0.08
        mouth = "grit"
    elif r.state == "dash":
        gf, gb = (21.0, -2.0), (13.0, 3.0)
        lean = 0.42
    elif r.state == "hurt":
        gf, gb = (-8.0, -24.0), (-18.0, -10.0)
        lean = -0.32
        mouth = "o"
    elif r.state == "dead":
        mouth = "o"
    return {"gf": gf, "gb": gb, "lean": lean, "sh_y": sh_y, "cr": cr, "mouth": mouth}


def glove_world(r: Rufo) -> tuple[float, float]:
    p = glove_pose(r)
    arm = "b" if r.atk in ("hook", "charge") else "f"
    g = p["gb"] if arm == "b" else p["gf"]
    sx = 3 if arm == "f" else -5
    return (r.x + (sx + g[0]) * r.facing, r.y + p["sh_y"] + g[1])


# ═══════════════════════════════════════════════════════════════════════════
# 6. EL TOMATE
# ═══════════════════════════════════════════════════════════════════════════

# Ángulos (radianes, 0 = derecha, -π/2 = arriba) donde puede estar el punto
# débil: nunca debajo, que ahí no llega nadie.
WEAK_RANGES = [(-2.75, -0.4), (-0.4, 0.75), (2.4, 3.55)]


def random_weak_angle(avoid: float | None = None) -> float:
    for _ in range(30):
        lo, hi = random.choice(WEAK_RANGES)
        a = random.uniform(lo, hi)
        if avoid is None or abs(math.atan2(math.sin(a - avoid), math.cos(a - avoid))) > 0.9:
            return a
    return -math.pi / 2


def angle_ok(a: float) -> bool:
    a = math.atan2(math.sin(a), math.cos(a))
    return not (0.75 < a < 2.4)


class Crack:
    __slots__ = ("ang", "pts", "age", "width", "bruise")

    def __init__(self, ang: float, depth: float, width: float):
        self.ang = ang
        self.age = 0.0
        self.width = width
        self.bruise = random.random() < 0.5
        # Polilínea quebrada en coordenadas normalizadas del disco unidad
        rim = 0.985
        pts = [(math.cos(ang) * rim, math.sin(ang) * rim)]
        n = 5
        for i in range(1, n + 1):
            d = rim - depth * i / n
            jitter = random.uniform(-0.11, 0.11) * (1 - i / (n + 2))
            a = ang + jitter
            pts.append((math.cos(a) * d, math.sin(a) * d))
        self.pts = pts


class Tomato:
    uid_counter = 0

    def __init__(self, level: int, x: float = W * 0.62, diff: dict[str, float] | None = None):
        Tomato.uid_counter += 1
        self.uid = Tomato.uid_counter
        self.level = level
        self.diff = diff or DIFFICULTY["Normal"]
        self.kind = tomato_kind(level)
        self.r = tomato_radius(level)
        self.maxhp = self.hp = 30 + 10 * (level - 1)
        self.hp_trail = float(self.hp)
        self.pause = max(3.0 - 0.25 * (level - 1), 1.2) * self.diff["pause"]
        self.attacks = ["roll", "bounce"] + (["jet"] if level >= 3 else []) + (["seeds"] if level >= 5 else []) + (["cherry"] if level >= 7 else [])
        # Tomate verde: coraza que hay que romper (madurar) con golpes fuertes
        self.max_armor = self.armor = float(10 + 2 * level) if self.kind == "verde" else 0.0
        self.ripe = 0.0 if self.kind == "verde" else 1.0
        self.puddle_t = 0.0
        self.x = x
        self.y = -self.r * 2.2
        self.vx = self.vy = 0.0
        self.sq = Spring(150, 7)  # + = achatado
        self.theta = 0.0
        self.state = "intro"
        self.t = 0.0
        self.timer = 0.0
        self.attack = ""
        self.phase = ""
        self.fury_chain = 0
        self.hazard = 0
        self.dir = -1
        self.jet_high = True
        self.target_x = x
        self.recent: list[str] = []
        self.flash = 0.0
        self.tremble = 0.0
        self.cracks: list[Crack] = []
        self.weak = random_weak_angle()
        self.cracks.append(Crack(self.weak, 0.22, 1.0))
        self.drip_t = 0.0
        self.alive = True
        self.sleeping = False
        self.big_weak = False
        self.rainbow = False
        self.prev = (self.x, self.y)

    # ── geometría ──────────────────────────────────────────────────────
    def scale(self) -> tuple[float, float]:
        s = clamp(self.sq.x, -0.35, 0.45)
        return 1 + s * 0.65, 1 - s

    def radii(self) -> tuple[float, float]:
        sx, sy = self.scale()
        return self.r * sx, self.r * TOMATO_ASPECT * sy

    def fury(self) -> bool:
        return self.hp <= self.maxhp * 0.25

    def tele(self, attack: str) -> float:
        return TELE[attack] * self.diff["tele"] * (0.85 if self.fury_chain else 1.0)

    def juice(self) -> tuple[int, int, int]:
        return ROT_JUICE if self.kind == "podrida" else JUICE

    def art_key(self) -> tuple[str, int]:
        return self.kind, round(self.ripe * 4)

    def bucket(self) -> int:
        f = self.hp / self.maxhp
        return 0 if f > 0.75 else 1 if f > 0.5 else 2 if f > 0.25 else 3

    def weak_pos(self) -> tuple[float, float]:
        rx, ry = self.radii()
        a = self.weak + self.theta
        return self.x + math.cos(a) * rx * 0.86, self.y + math.sin(a) * ry * 0.86

    def offscreen(self) -> bool:
        return self.y + self.radii()[1] < -10

    def hazard_id(self) -> str:
        return f"{self.uid}:{self.hazard}"

    def grounded(self) -> bool:
        return self.state in ("idle", "stun", "tele") or (
            self.state == "atk" and self.attack in ("roll", "jet", "seeds", "cherry") or (self.attack == "bounce" and self.phase == "land")
        )

    def body_dangerous(self) -> bool:
        if self.state != "atk":
            return False
        if self.attack == "roll" and self.phase == "go":
            return True
        return self.attack == "bounce" and (self.phase == "fall" or (self.phase == "land" and self.timer < 0.06))

    # ── reacciones ─────────────────────────────────────────────────────
    def take_hit(self, ang_world: float, dmg: int, knock: float, crit: bool, heavy: bool = True) -> tuple[int, str | None]:
        """Aplica un golpe. Devuelve (daño real, evento): «clonk» si la coraza
        lo absorbe, «ripe» si la coraza se rompe y el tomate madura."""
        event = None
        if self.armor > 0:
            self.armor = max(0.0, self.armor - dmg * (1.0 if crit else 1.6 if heavy else 0.6))
            if not crit:
                dmg = dmg // 2 if heavy else 0
                event = "clonk"
            if self.armor <= 0:
                event = "ripe"
        self.hp = max(0, self.hp - dmg)
        self.sq.kick(2.2 + dmg * 0.9 + (2.0 if crit else 0))
        self.flash = 1.0 if crit else 0.6
        if knock and self.grounded() and self.state != "atk":
            self.vx += knock * (220 / self.r) * (-1 if math.cos(ang_world) > 0 else 1)
        local = ang_world - self.theta
        if len(self.cracks) < 16 and angle_ok(local):
            near = [c for c in self.cracks if abs(math.atan2(math.sin(c.ang - local), math.cos(c.ang - local))) < 0.18]
            if near:
                near[0].width = min(2.2, near[0].width + 0.25)
            else:
                self.cracks.append(Crack(local, random.uniform(0.1, 0.18) + dmg * 0.025, 0.7 + dmg * 0.15))
        if crit:
            # El punto débil salta a otra grieta lejana (o abre una nueva)
            far = [c.ang for c in self.cracks if angle_ok(c.ang) and abs(math.atan2(math.sin(c.ang - self.weak), math.cos(c.ang - self.weak))) > 0.9]
            if far and random.random() < 0.7:
                self.weak = random.choice(far)
            else:
                self.weak = random_weak_angle(self.weak)
                self.cracks.append(Crack(self.weak, 0.2, 1.0))
        return dmg, event

    # ── cerebro y física ────────────────────────────────────────────────
    def step(self, g: "Game", dt: float) -> None:
        self.t += dt
        self.timer += dt
        self.sq.step(dt)
        self.flash = max(0.0, self.flash - dt * 4)
        self.hp_trail = approach(self.hp_trail, self.hp, max(4.0, (self.hp_trail - self.hp) * 3) * dt)
        for c in self.cracks:
            c.age += dt
        rolling = self.state == "atk" and self.attack == "roll" and self.phase == "go"
        if not rolling:
            # Como un tentetieso: siempre vuelve con el cáliz arriba
            target = round(self.theta / (2 * math.pi)) * 2 * math.pi
            self.theta = lerp(self.theta, target, 1 - math.exp(-dt * 5))
        if self.kind == "verde":
            target = 1.0 if self.armor <= 0 else 0.55 * (1 - self.armor / self.max_armor)
            self.ripe = approach(self.ripe, target, dt * (2.5 if self.armor <= 0 else 1.0))
        base_trem = 1.6 if self.fury() and self.state not in ("intro", "dead") else 0.0
        self.tremble = approach(self.tremble, base_trem, 20 * dt)
        if self.sleeping:
            self.sq.target = 0.035 * math.sin(self.t * 1.6)
            self.y = FLOOR - self.radii()[1]
            return
        getattr(self, "st_" + self.state)(g, dt)
        if self.grounded():
            self._ground(g, dt)
        # Goteo cuando está malherido
        rotten = self.kind == "podrida"
        if (self.bucket() >= 2 or rotten) and self.state != "intro" and not self.offscreen():
            self.drip_t -= dt
            if self.drip_t <= 0:
                self.drip_t = random.uniform(0.15, 0.5) / max(1, self.bucket() - 1) * (2.0 if rotten and self.bucket() < 2 else 1.0)
                c = random.choice(self.cracks)
                rx, ry = self.radii()
                a = c.ang + self.theta
                g.fx.drop(self.x + math.cos(a) * rx * 0.97, self.y + math.sin(a) * ry * 0.97, random.uniform(-40, 40), random.uniform(-20, 40), 2.5, self.juice())
        # El podrido deja un rastro de charcos al rodar
        if rotten and self.state == "atk" and self.attack == "roll" and self.phase == "go":
            self.puddle_t -= dt
            if self.puddle_t <= 0:
                self.puddle_t = 0.09
                g.add_puddle(self.x - sign(self.vx) * self.radii()[0] * 0.5, 46)

    def _ground(self, g: "Game", dt: float) -> None:
        rolling = self.state == "atk" and self.attack == "roll" and self.phase == "go"
        if not rolling:
            self.vx = approach(self.vx, 0, 700 * dt)
        self.x += self.vx * dt
        if rolling:
            self.theta += self.vx * dt / self.r
        rx, ry = self.radii()
        self.y = FLOOR - ry
        hit_wall = 0
        if self.attack == "bounce" and self.phase == "land":
            # Cayó medio empotrado en la pared: sale deslizándose, sin saltos bruscos
            self.x = clamp(self.x, approach(self.x, WALL_L + rx, 900 * dt), approach(self.x, WALL_R - rx, 900 * dt))
            return
        if self.x - rx < WALL_L:
            self.x = WALL_L + rx
            hit_wall = -1
        elif self.x + rx > WALL_R:
            self.x = WALL_R - rx
            hit_wall = 1
        if hit_wall and abs(self.vx) > 1:
            speed = abs(self.vx)
            if rolling:
                self.vx = -self.vx * 0.3
                self.phase = "stop"
                self.timer = 0.0
                self.sq.kick(-3.5)
                g.shake(0.55)
                g.audio.play("wall")
                g.scene.kick(0.6)
                g.fx.wall_splat(WALL_L if hit_wall < 0 else WALL_R, self.y)
            elif speed > 180 and self.state in ("idle", "stun"):
                # Empujado contra la pared: rebota y queda aturdido
                self.vx = -self.vx * 0.5
                self.sq.kick(-2.5)
                self.state, self.timer = "stun", 0.0
                g.shake(0.35)
                g.audio.play("wall")
                g.fx.text(self.x, self.y - ry - 30, "¡PARED!", (255, 230, 160), 34)
            else:
                self.vx = 0.0

    def st_intro(self, g: "Game", dt: float) -> None:
        self.vy += 2600 * dt
        self.y += self.vy * dt
        rx, ry = self.radii()
        if self.y + ry >= FLOOR:
            self.y = FLOOR - ry
            self.sq.kick(self.vy * 0.0026)
            g.slam(self, 0.75)
            self.vy = 0.0
            self.state, self.timer = "idle", -0.6

    def st_idle(self, g: "Game", dt: float) -> None:
        self.sq.target = 0.03 * math.sin(self.t * 2.3)
        r = g.rufo
        d = r.x - self.x
        rx, _ = self.radii()
        if abs(d) > rx + 240:
            self.vx = approach(self.vx, sign(d) * 70, 400 * dt)
        if self.timer >= self.pause:
            self.choose(g)

    def choose(self, g: "Game", chained: bool = False) -> None:
        r = g.rufo
        opts = [a for a in self.attacks if not (len(self.recent) >= 2 and self.recent[-1] == self.recent[-2] == a)]
        if chained and len(opts) > 1 and self.attack in opts:
            opts.remove(self.attack)
        opts = opts or list(self.attacks)
        if r.on_tomato and "bounce" in opts and random.random() < 0.6:
            pick = "bounce"
        else:
            pick = random.choice(opts)
        self.attack = pick
        self.recent = (self.recent + [pick])[-3:]
        self.state, self.timer = "tele", 0.0
        self.hazard += 1
        self.dir = 1 if r.x > self.x else -1
        self.sq.target = 0.0
        if pick == "roll":
            g.audio.play("warn_roll")
        elif pick == "bounce":
            g.audio.play("warn_bounce")
        elif pick == "jet":
            self.jet_high = random.random() < 0.5
            g.audio.play("warn_jet")
        elif pick == "cherry":
            g.audio.play("warn_cherry")
        else:
            g.audio.play("warn_seeds")
        if r.on_tomato and pick in ("roll", "bounce"):
            g.shrug_rufo(self)

    def st_tele(self, g: "Game", dt: float) -> None:
        dur = self.tele(self.attack)
        p = clamp(self.timer / dur, 0, 1)
        if self.attack == "roll":
            self.sq.target = 0.26 * ease_out(p)
            self.tremble = 3 + 5 * p
            if random.random() < 0.3:
                g.fx.puff(self.x - self.dir * self.radii()[0] * 0.8, FLOOR, 2)
        elif self.attack == "bounce":
            self.sq.target = 0.3 * ease_out(p)
            self.tremble = 2
        elif self.attack == "jet":
            self.sq.target = -0.05 * p
            if random.random() < 0.35:
                rx, ry = self.radii()
                jy = self.jet_y()
                g.fx.drop(self.x + self.dir * self.rim_dx(jy), jy, self.dir * random.uniform(20, 90), random.uniform(-30, 30), 2.5)
        elif self.attack == "cherry":
            self.sq.target = -0.12 * ease_out(p)
            self.tremble = 2 + 2 * p
            if random.random() < 0.05:
                g.audio.play("pop", 0.5)
        else:
            self.tremble = 4 + 3 * math.sin(self.timer * 40)
        if self.timer >= dur:
            self.state, self.timer = "atk", 0.0
            self.start_attack(g)

    def jet_y(self) -> float:
        return FLOOR - (60 if self.jet_high else 16)

    def rim_dx(self, y: float) -> float:
        rx, ry = self.radii()
        k = clamp((y - self.y) / ry, -1, 1)
        return rx * math.sqrt(max(0.0, 1 - k * k))

    def start_attack(self, g: "Game") -> None:
        a = self.attack
        if a == "roll":
            self.phase = "go"
            self.dir = 1 if g.rufo.x > self.x else -1
            self.vx = self.dir * (780 + 28 * self.level) * self.diff["speed"]
            self.sq.target = 0.22
            self.sq.kick(-2.0)
            g.shake(0.25)
        elif a == "bounce":
            self.phase = "rise"
            self.vy = -2500.0
            self.sq.target = -0.15
            self.sq.kick(-4.0)
            self.target_x = g.rufo.x
            g.fx.puff(self.x, FLOOR, 12)
            g.shake(0.3)
        elif a == "jet":
            self.phase = "fire"
            self.sq.kick(-2.5)
            y = self.jet_y()
            x0 = self.x + self.dir * self.rim_dx(y)
            g.spawn_jet(x0, y, self.dir, self.hazard_id())
            g.audio.play("jet")
        elif a == "cherry":
            self.phase = "spit"
            self.sq.kick(-3.5)
            g.spawn_cherries(self)
            g.audio.play("pop")
        else:
            self.phase = "spray"
            self.sq.kick(3.0)
            g.spawn_seeds(self)

    def st_atk(self, g: "Game", dt: float) -> None:
        a = self.attack
        done = False
        if a == "roll":
            if self.phase == "go":
                self.tremble = 1.5
                if self.timer > 2.6:
                    self.phase, self.timer = "stop", 0.0
            elif self.phase == "stop":
                self.sq.target = 0.0
                if self.timer > 0.45:
                    done = True
        elif a == "bounce":
            rx, ry = self.radii()
            lo = WALL_L + rx * 0.55
            hi = WALL_R - rx * 0.55
            if self.phase == "rise":
                self.y += self.vy * dt
                self.x += (clamp(g.rufo.x, lo, hi) - self.x) * min(1.0, dt * 2)
                if self.y + ry < -40:
                    self.phase, self.timer = "hover", 0.0
            elif self.phase == "hover":
                if self.timer < 0.35:  # sigue a Rufo y luego se fija
                    self.target_x = lerp(self.target_x, clamp(g.rufo.x, lo, hi), 1 - math.exp(-dt * 6))
                self.x = self.target_x
                if self.timer >= HOVER_T:
                    self.phase, self.timer = "fall", 0.0
                    self.vy = 2400.0
                    self.sq.target = 0.0
                    self.sq.x = -0.25
            elif self.phase == "fall":
                self.vy += 3000 * dt
                self.y += self.vy * dt
                if self.y + ry >= FLOOR:
                    self.y = FLOOR - ry
                    self.sq.kick(self.vy * 0.0032)
                    self.phase, self.timer = "land", 0.0
                    g.slam(self, 1.0)
                    g.slam_hazard(self)
                    self.vy = 0.0
            elif self.phase == "land":
                # Si cayó medio empotrado en la pared, sale rodando
                if self.x - rx < WALL_L:
                    self.vx = 160
                elif self.x + rx > WALL_R:
                    self.vx = -160
                if self.timer > 0.35:
                    done = True
        elif a == "jet":
            self.sq.target = 0.06
            if self.timer > 0.75:
                done = True
        else:
            self.tremble = max(0.0, 3 - self.timer * 6)
            if self.timer > 0.55:
                done = True
        if done:
            self.phase = ""
            self.sq.target = 0.0
            if self.fury() and self.fury_chain == 0:
                self.fury_chain = 1
                self.choose(g, chained=True)
            else:
                self.fury_chain = 0
                self.state, self.timer = "stun", 0.0

    def st_stun(self, g: "Game", dt: float) -> None:
        self.sq.target = 0.06 * math.sin(self.t * 9) * (1 - self.timer / STUN_T)
        if self.timer >= STUN_T:
            self.state, self.timer = "idle", 0.0

    def st_dead(self, g: "Game", dt: float) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# 7. EFECTOS: partículas, manchas, ondas, textos
# ═══════════════════════════════════════════════════════════════════════════

# Partícula: [kind, x, y, vx, vy, life, maxlife, size, color, bounces]
DROP, PULP, SEED, SPARK, PUFF, MOTE = range(6)


class FX:
    def __init__(self, scene: "Scene"):
        self.scene = scene
        self.p: list[list] = []
        self.rings: list[list] = []
        self.texts: list[list] = []
        self.ghosts: list[list] = []

    def clear(self) -> None:
        self.p.clear()
        self.rings.clear()
        self.texts.clear()
        self.ghosts.clear()

    # ── emisores ────────────────────────────────────────────────────────
    def drop(self, x, y, vx, vy, size=3.0, color=JUICE) -> None:
        if len(self.p) < 900:
            self.p.append([DROP, x, y, vx, vy, 2.5, 2.5, size, color, 0])

    def squirt(self, x, y, ang, n, speed, spread=0.7, size=(2, 5), color=JUICE) -> None:
        hi = (255, 60, 40) if color == JUICE else scale_c(color, 1.4)
        for _ in range(n):
            a = ang + random.uniform(-spread, spread)
            s = speed * random.uniform(0.35, 1.0)
            self.drop(x, y, math.cos(a) * s, math.sin(a) * s, random.uniform(*size), mix(color, hi, random.random() * 0.5))

    def sparks(self, x, y, n, speed, color=(255, 210, 120), life=0.25) -> None:
        for _ in range(n):
            a = random.uniform(0, math.tau)
            s = speed * random.uniform(0.3, 1.0)
            self.p.append([SPARK, x, y, math.cos(a) * s, math.sin(a) * s, life, life, random.uniform(4, 9), color, 0])

    def puff(self, x, y, n) -> None:
        for _ in range(n):
            self.p.append([PUFF, x + random.uniform(-10, 10), y - 4, random.uniform(-120, 120), random.uniform(-60, -10), 0.5, 0.5, random.uniform(8, 16), (150, 140, 135), 0])

    def charge_mote(self, x, y) -> None:
        a = random.uniform(0, math.tau)
        d = random.uniform(30, 55)
        self.p.append([MOTE, x + math.cos(a) * d, y + math.sin(a) * d, -math.cos(a) * d * 4, -math.sin(a) * d * 4, 0.25, 0.25, 4, GOLD, 0])

    def seeds(self, x, y, n, speed) -> None:
        for _ in range(n):
            a = random.uniform(-math.pi, 0)
            s = speed * random.uniform(0.3, 1)
            self.p.append([SEED, x, y, math.cos(a) * s, math.sin(a) * s - 200, 3.0, 3.0, random.uniform(3, 5), (240, 222, 150), 0])

    def pulp(self, x, y, n, speed) -> None:
        for _ in range(n):
            a = random.uniform(-math.pi, 0.2)
            s = speed * random.uniform(0.3, 1)
            self.p.append([PULP, x, y, math.cos(a) * s, math.sin(a) * s, 3.0, 3.0, random.uniform(5, 11), mix((170, 10, 22), (230, 50, 40), random.random()), 0])

    def ring(self, x, y, radius, color, life, width, flat=1.0) -> None:
        self.rings.append([x, y, 0.0, radius, life, life, width, color, flat])

    def text(self, x, y, s, color, size=30, life=0.9, vy=-90.0) -> None:
        self.texts.append([x, y, s, color, size, life, life, vy])

    def wall_splat(self, wx, y) -> None:
        for _ in range(14):
            self.scene.stain(wx + random.uniform(-6, 6), y + random.uniform(-160, 160), random.uniform(10, 26), wall=True)

    # ── simulación ──────────────────────────────────────────────────────
    def step(self, dt: float) -> None:
        keep = []
        scene = self.scene
        for q in self.p:
            k = q[0]
            q[5] -= dt
            if q[5] <= 0:
                continue
            if k == DROP or k == PULP:
                q[4] += 1900 * dt
                q[3] *= 1 - 0.4 * dt
                q[1] += q[3] * dt
                q[2] += q[4] * dt
                if q[2] >= FLOOR + 4:
                    scene.stain(q[1], FLOOR + random.uniform(4, 70) * (q[7] / 6), q[7] * random.uniform(1.4, 2.6))
                    if k == PULP and q[9] == 0 and q[4] > 300:
                        q[9] = 1
                        q[4] *= -0.3
                        q[2] = FLOOR + 3
                        keep.append(q)
                    continue
                if q[1] < WALL_L or q[1] > WALL_R:
                    scene.stain(clamp(q[1], WALL_L - 20, WALL_R + 20), q[2], q[7] * 2.4, wall=True)
                    continue
            elif k == SEED:
                q[4] += 1900 * dt
                q[1] += q[3] * dt
                q[2] += q[4] * dt
                if q[2] >= FLOOR + 6:
                    q[2] = FLOOR + 6
                    if q[9] < 2:
                        q[4] *= -0.35
                        q[3] *= 0.6
                        q[9] += 1
                    else:
                        q[3] = q[4] = 0
                if not WALL_L < q[1] < WALL_R:
                    q[3] = -q[3]
                    q[1] = clamp(q[1], WALL_L, WALL_R)
            elif k == SPARK:
                q[3] *= 1 - 5 * dt
                q[4] = q[4] * (1 - 5 * dt) + 300 * dt
                q[1] += q[3] * dt
                q[2] += q[4] * dt
            elif k == PUFF:
                q[3] *= 1 - 4 * dt
                q[4] *= 1 - 4 * dt
                q[1] += q[3] * dt
                q[2] += q[4] * dt
                q[7] += 30 * dt
            else:  # MOTE
                q[1] += q[3] * dt
                q[2] += q[4] * dt
            keep.append(q)
        self.p = keep
        for rg in self.rings:
            rg[4] -= dt
            rg[2] = rg[3] * ease_out(1 - rg[4] / rg[5])
        self.rings = [rg for rg in self.rings if rg[4] > 0]
        for tx in self.texts:
            tx[5] -= dt
            tx[1] += tx[7] * dt
            tx[7] *= 1 - 2.5 * dt
        self.texts = [tx for tx in self.texts if tx[5] > 0]
        for gh in self.ghosts:
            gh[3] -= dt
        self.ghosts = [gh for gh in self.ghosts if gh[3] > 0]

    # ── dibujo ──────────────────────────────────────────────────────────
    def draw(self, surf: pygame.Surface, add: pygame.Surface) -> None:
        dc = pygame.draw.circle
        for q in self.p:
            k = q[0]
            x, y = q[1], q[2]
            if k == DROP:
                s = q[7]
                tail = 0.016
                pygame.draw.line(surf, q[8], (x - q[3] * tail, y - q[4] * tail), (x, y), max(1, int(s)))
                dc(surf, q[8], (x, y), s * 0.62)
                if s > 2.5:
                    dc(surf, JUICE_HI, (x - s * 0.25, y - s * 0.25), max(1, s * 0.25))
            elif k == PULP:
                s = q[7]
                dc(surf, (90, 0, 12), (x, y), s + 1)
                dc(surf, q[8], (x, y), s)
                dc(surf, (250, 140, 120), (x - s * 0.3, y - s * 0.35), s * 0.3)
            elif k == SEED:
                a = min(1.0, q[5] / 0.6)
                c = scale_c(q[8], a)
                pygame.draw.ellipse(surf, scale_c((120, 110, 70), a), (x - q[7] - 1, y - q[7] * 0.7 - 1, q[7] * 2 + 2, q[7] * 1.4 + 2))
                pygame.draw.ellipse(surf, c, (x - q[7], y - q[7] * 0.7, q[7] * 2, q[7] * 1.4))
            elif k == SPARK or k == MOTE:
                f = q[5] / q[6]
                blit_add(add, glow(q[7] * (0.5 + f), scale_c(q[8], f), 1.6), x, y)
            elif k == PUFF:
                f = q[5] / q[6]
                blit_center(surf, soft_blob(q[7], q[8], int(110 * f)), x, y)
        for x, y, rad, _mx, life, maxlife, width, color, flat in self.rings:
            f = life / maxlife
            if rad < 2:
                continue
            rw, rh = int(rad * 2) + 4, max(6, int(rad * 2 * flat)) + 4
            tmp = pygame.Surface((rw, rh))
            pygame.draw.ellipse(tmp, scale_c(color, f * 0.9), (2, 2, rw - 4, rh - 4), max(1, int(width * f + 1)))
            add.blit(tmp, (int(x - rw / 2), int(y - rh / 2)), special_flags=pygame.BLEND_ADD)

    def draw_texts(self, surf: pygame.Surface, txt: "TextKit") -> None:
        for x, y, s, color, size, life, maxlife, _vy in self.texts:
            age = maxlife - life
            pop = back_out(min(1.0, age / 0.18))
            sz = max(8, int(size * (0.4 + 0.6 * pop)))
            img = txt.outlined(s, sz, color)
            if life < 0.3:
                img = img.copy()
                img.set_alpha(int(255 * life / 0.3))
            blit_center(surf, img, x, y)


# ═══════════════════════════════════════════════════════════════════════════
# 8. ESCENARIO: almacén de cocina de noche
# ═══════════════════════════════════════════════════════════════════════════


class Lamp:
    __slots__ = ("x", "length", "ang", "av")

    def __init__(self, x: float, length: float):
        self.x, self.length = x, length
        self.ang = random.uniform(-0.05, 0.05)
        self.av = 0.0

    def bulb(self) -> tuple[float, float]:
        return self.x + math.sin(self.ang) * self.length, math.cos(self.ang) * self.length


class Scene:
    def __init__(self):
        rng = random.Random(11)
        self.bg = build_background(rng)
        self.live = self.bg.copy()  # fondo con manchas horneadas
        self.stains = pygame.Surface((W, H), pygame.SRCALPHA)
        self.stain_dirty = 0.0
        self.fade_t = 0.0
        splats = [make_splat(rng, s) for s in (12, 16, 20, 26, 30, 34)]
        self.splats_floor = [pygame.transform.scale(sp, (sp.get_width(), max(3, int(sp.get_height() * 0.38)))) for sp in splats]
        self.splats_wall = [pygame.transform.scale(sp, (sp.get_width() // 2 + 2, sp.get_height())) for sp in splats]
        self.pool = pygame.transform.scale(glow(170, (70, 52, 30), 1.7), (420, 70))
        self.lamps = [Lamp(250, 150), Lamp(640, 118), Lamp(1030, 160)]
        self.cone = build_cone()
        self.cone_cache: dict[int, pygame.Surface] = {}
        self.dust = [[rng.uniform(WALL_L, WALL_R), rng.uniform(40, FLOOR), rng.uniform(-6, 6), rng.uniform(-4, 4), rng.uniform(0, 6.28)] for _ in range(110)]
        self.vignette = build_vignette()
        self.refl_fade = build_refl_fade()
        self.t = 0.0

    def reset(self) -> None:
        self.stains.fill((0, 0, 0, 0))
        self.live = self.bg.copy()

    def kick(self, power: float) -> None:
        for lamp in self.lamps:
            lamp.av += random.uniform(0.4, 1.0) * power * random.choice((-1, 1)) * 1.4

    def stain(self, x: float, y: float, size: float, wall: bool = False) -> None:
        bank = self.splats_wall if wall else self.splats_floor
        spr = bank[min(len(bank) - 1, int(size / 6))]
        pos = (int(x - spr.get_width() / 2), int(y - spr.get_height() / 2))
        self.stains.blit(spr, pos)
        self.live.blit(spr, pos)

    def step(self, dt: float) -> None:
        self.t += dt
        for lamp in self.lamps:
            lamp.av += (-9.0 * lamp.ang - 0.5 * lamp.av) * dt
            lamp.ang = clamp(lamp.ang + lamp.av * dt, -0.6, 0.6)
        for d in self.dust:
            d[4] += dt
            d[0] += (d[2] + math.sin(d[4] * 0.7) * 8) * dt
            d[1] += (d[3] + math.cos(d[4] * 0.5) * 5) * dt
            if d[0] < WALL_L:
                d[0] = WALL_R
            elif d[0] > WALL_R:
                d[0] = WALL_L
            if d[1] < 20:
                d[1] = FLOOR - 5
            elif d[1] > FLOOR:
                d[1] = 25
        # Las manchas se desvanecen poco a poco
        self.fade_t += dt
        if self.fade_t > 1.0:
            self.fade_t = 0.0
            self.stains.fill((255, 255, 255, 247), special_flags=pygame.BLEND_RGBA_MULT)
            self.live = self.bg.copy()
            self.live.blit(self.stains, (0, 0))

    def cone_sprite(self, ang: float) -> pygame.Surface:
        key = int(round(math.degrees(ang) * 1.5))
        spr = self.cone_cache.get(key)
        if spr is None:
            spr = pygame.transform.rotate(self.cone, key / 1.5)
            if len(self.cone_cache) > 90:
                self.cone_cache.clear()
            self.cone_cache[key] = spr
        return spr

    def draw_back(self, surf: pygame.Surface) -> None:
        surf.blit(self.live, (0, 0))
        for lamp in self.lamps:
            bx, by = lamp.bulb()
            # Charco de luz en el suelo
            fx = bx + math.tan(lamp.ang) * (FLOOR - by)
            blit_add(surf, self.pool, fx, FLOOR + 22)

    def draw_lamps(self, surf: pygame.Surface) -> None:
        for lamp in self.lamps:
            bx, by = lamp.bulb()
            cone = self.cone_sprite(lamp.ang)
            # El cono rota alrededor de la bombilla: su vértice está arriba al centro
            ox = math.sin(lamp.ang) * self.cone.get_height() / 2
            oy = math.cos(lamp.ang) * self.cone.get_height() / 2
            blit_add(surf, cone, bx + ox, by + oy)
            pygame.draw.line(surf, (20, 20, 24), (lamp.x, 0), (bx, by), 2)
            # Pantalla metálica
            ca, sa = math.cos(lamp.ang), math.sin(lamp.ang)

            def rot(px, py):
                return (bx + px * ca + py * sa, by - px * sa + py * ca)

            shade = [rot(-9, -14), rot(9, -14), rot(30, 6), rot(-30, 6)]
            pygame.draw.polygon(surf, (28, 44, 40), shade)
            pygame.draw.polygon(surf, (70, 100, 90), [rot(-9, -14), rot(9, -14), rot(14, -8), rot(-14, -8)])
            pygame.draw.line(surf, (110, 140, 120), rot(-30, 6), rot(30, 6), 2)
            blit_add(surf, glow(60, (120, 90, 50), 2.2), *rot(0, 10))
            pygame.draw.circle(surf, (255, 246, 220), rot(0, 9), 6)

    def draw_dust(self, surf: pygame.Surface) -> None:
        bulbs = [(lp.bulb(), lp.ang) for lp in self.lamps]
        for x, y, _vx, _vy, ph in self.dust:
            lit = 0.0
            for (bx, by), ang in bulbs:
                dx, dy = x - bx, y - by
                if dy <= 0:
                    continue
                rel = math.atan2(dx, dy) + ang
                if abs(rel) < 0.36:
                    lit = max(lit, (1 - abs(rel) / 0.36) * (1 - min(1.0, dy / 700)))
            v = int(18 + 200 * lit * (0.6 + 0.4 * math.sin(ph * 2)))
            if v > 25:
                surf.fill((v, int(v * 0.9), int(v * 0.7)), (int(x), int(y), 2, 2), special_flags=pygame.BLEND_ADD)


def build_background(rng: random.Random) -> pygame.Surface:
    bg = pygame.Surface((W, H))
    # Pared: degradado frío arriba, cálido abajo
    ys = np.linspace(0, 1, FLOOR)[None, :, None]
    top, mid, low = np.array([10, 12, 22]), np.array([22, 22, 34]), np.array([46, 34, 36])
    grad = np.where(ys < 0.6, top + (mid - top) * (ys / 0.6), mid + (low - mid) * ((ys - 0.6) / 0.4))
    wall = pygame.surfarray.make_surface(np.broadcast_to(grad, (W, FLOOR, 3)).astype(np.uint8))
    # Ladrillo apenas insinuado
    for row in range(0, FLOOR, 26):
        off = 0 if (row // 26) % 2 else 40
        for col in range(-80, W, 80):
            k = rng.uniform(0.9, 1.15)
            c = scale_c((26, 24, 34), k * (0.7 + 0.6 * row / FLOOR))
            pygame.draw.rect(wall, c, (col + off + 1, row + 1, 78, 24), border_radius=2)
    # Estanterías al fondo (luego se desenfocan: profundidad de campo)
    shelves = wall.copy()
    for ux in (60, 470, 880):
        uw = 340
        pygame.draw.rect(shelves, (40, 32, 30), (ux, 70, 10, FLOOR - 70))
        pygame.draw.rect(shelves, (40, 32, 30), (ux + uw, 70, 10, FLOOR - 70))
        for sy in (170, 300, 430, 560):
            pygame.draw.rect(shelves, (70, 52, 40), (ux, sy, uw + 10, 10))
            x = ux + 14
            while x < ux + uw - 30:
                kind = rng.random()
                if kind < 0.35:  # tarro de conserva
                    w_, h_ = rng.randint(26, 40), rng.randint(40, 70)
                    fill = rng.choice([(180, 40, 30), (200, 120, 40), (90, 140, 60), (150, 30, 40), (220, 180, 80)])
                    pygame.draw.rect(shelves, scale_c(fill, 0.75), (x, sy - h_, w_, h_), border_radius=6)
                    pygame.draw.rect(shelves, (150, 150, 160), (x + 2, sy - h_ - 6, w_ - 4, 8), border_radius=2)
                    pygame.draw.rect(shelves, scale_c(fill, 1.25), (x + 4, sy - h_ + 6, 5, h_ - 14), border_radius=3)
                elif kind < 0.6:  # latas
                    w_, h_ = rng.randint(22, 30), rng.randint(30, 46)
                    c = rng.choice([(200, 30, 30), (220, 200, 180), (40, 90, 160), (230, 160, 30)])
                    pygame.draw.rect(shelves, c, (x, sy - h_, w_, h_))
                    pygame.draw.rect(shelves, scale_c(c, 0.5), (x, sy - h_ * 0.6, w_, h_ * 0.25))
                elif kind < 0.8:  # botellas
                    w_, h_ = rng.randint(14, 20), rng.randint(60, 90)
                    c = rng.choice([(40, 90, 50), (90, 50, 30), (160, 120, 60)])
                    pygame.draw.rect(shelves, c, (x, sy - h_ * 0.7, w_, h_ * 0.7), border_radius=4)
                    pygame.draw.rect(shelves, c, (x + w_ // 3, sy - h_, w_ // 3 + 1, h_ * 0.35))
                else:  # cajas y sacos
                    w_, h_ = rng.randint(50, 80), rng.randint(36, 60)
                    c = rng.choice([(120, 90, 60), (150, 130, 100), (100, 70, 50)])
                    pygame.draw.rect(shelves, c, (x, sy - h_, w_, h_), border_radius=3)
                    pygame.draw.line(shelves, scale_c(c, 0.7), (x, sy - h_ / 2), (x + w_, sy - h_ / 2), 2)
                x += w_ + rng.randint(4, 16)
    shelves = blur(blur(blur(shelves, 7), 4), 2)
    shelves.fill((150, 148, 182), special_flags=pygame.BLEND_MULT)
    bg.blit(shelves, (0, 0))
    # Bokeh: luces lejanas desenfocadas
    for _ in range(26):
        c = rng.choice([(60, 40, 18), (40, 30, 50), (20, 40, 50), (70, 50, 20)])
        blit_add(bg, glow(rng.uniform(10, 34), c, 0.8), rng.uniform(60, W - 60), rng.uniform(60, FLOOR - 120))
    # Claraboya con luz de luna
    for sx in (150, 1010):
        pygame.draw.rect(bg, (20, 30, 52), (sx, 14, 120, 34), border_radius=3)
        pygame.draw.rect(bg, (60, 80, 120), (sx, 14, 120, 34), 2, border_radius=3)
        pygame.draw.line(bg, (60, 80, 120), (sx + 60, 14), (sx + 60, 48), 2)
    beam = pygame.Surface((W, FLOOR))
    beam.fill((0, 0, 0))
    for sx in (150, 1010):
        pygame.draw.polygon(beam, (14, 20, 34), [(sx, 48), (sx + 120, 48), (sx + 300, FLOOR), (sx + 120, FLOOR)])
    bg.blit(blur(beam, 8), (0, 0), special_flags=pygame.BLEND_ADD)
    # Oclusión ambiental junto al suelo y zócalo
    occl = pygame.Surface((W, 90), pygame.SRCALPHA)
    for i in range(90):
        pygame.draw.line(occl, (0, 0, 0, int(150 * (i / 90) ** 2)), (0, i), (W, i))
    bg.blit(occl, (0, FLOOR - 90))
    pygame.draw.rect(bg, (34, 26, 28), (0, FLOOR - 10, W, 10))
    pygame.draw.line(bg, (90, 70, 66), (0, FLOOR - 10), (W, FLOOR - 10), 1)
    # Suelo de baldosas en perspectiva
    vp = (W / 2, 180.0)
    rows = [FLOOR, FLOOR + 9, FLOOR + 21, FLOOR + 37, FLOOR + 57, FLOOR + 82]
    cols = list(range(-1600, W + 1700, 96))
    for ri in range(len(rows) - 1):
        y0, y1 = rows[ri], rows[ri + 1]
        for ci in range(len(cols) - 1):

            def at(x, y):
                t = (y - vp[1]) / (FLOOR - vp[1])
                return (vp[0] + (x - vp[0]) * t, y)

            poly = [at(cols[ci], y0), at(cols[ci + 1], y0), at(cols[ci + 1], y1), at(cols[ci], y1)]
            dark = (ri + ci) % 2
            base = (64, 44, 42) if dark else (96, 72, 62)
            depth = 0.55 + 0.45 * (ri / 5)
            pygame.draw.polygon(bg, scale_c(base, depth), poly)
            pygame.draw.polygon(bg, scale_c(base, depth * 0.6), poly, 1)
    gloss = pygame.Surface((W, H - FLOOR))
    for i in range(H - FLOOR):
        v = int(26 * math.exp(-i / 14))
        pygame.draw.line(gloss, (v, v, int(v * 1.1)), (0, i), (W, i))
    bg.blit(gloss, (0, FLOOR), special_flags=pygame.BLEND_ADD)
    # Columnas de acero a los lados (las paredes de la arena)
    for x0 in (0, WALL_R):
        for i in range(WALL_L):
            k = 0.5 + 0.5 * math.sin(i / WALL_L * math.pi)
            pygame.draw.line(bg, scale_c((60, 66, 78), 0.5 + 0.6 * k), (x0 + i, 0), (x0 + i, H))
        for ry in range(30, H, 70):
            pygame.draw.circle(bg, (110, 116, 130), (x0 + 10, ry), 3)
            pygame.draw.circle(bg, (110, 116, 130), (x0 + 30, ry), 3)
        for k in range(8):
            c = (230, 180, 30) if k % 2 == 0 else (20, 20, 20)
            y0 = FLOOR - 120 + k * 15
            pygame.draw.polygon(bg, c, [(x0, y0), (x0 + WALL_L, y0 - 15), (x0 + WALL_L, y0), (x0, y0 + 15)])
        edge = WALL_L if x0 == 0 else WALL_R
        pygame.draw.line(bg, (150, 160, 175), (edge, 0), (edge, H), 2)
    return bg.convert() if pygame.display.get_surface() else bg


def make_splat(rng: random.Random, size: int) -> pygame.Surface:
    s = pygame.Surface((size * 3, size * 3), pygame.SRCALPHA)
    c = (size * 1.5, size * 1.5)
    col = (120 + rng.randint(0, 30), 6, 16, 150)
    pygame.draw.circle(s, col, c, size * 0.6)
    for _ in range(7):
        a = rng.uniform(0, math.tau)
        d = rng.uniform(0.5, 1.3) * size
        pygame.draw.circle(s, col, (c[0] + math.cos(a) * d, c[1] + math.sin(a) * d), rng.uniform(0.12, 0.3) * size)
    return s


def build_cone() -> pygame.Surface:
    cw, ch = 420, 560
    xs = np.linspace(-1, 1, cw)[:, None]
    ys = np.linspace(0, 1, ch)[None, :]
    half = 0.07 + 0.62 * ys
    edge = np.clip(1 - np.abs(xs) / half, 0, 1) ** 1.4
    inten = edge * (1 - ys) ** 1.6 * 42
    col = np.stack([inten, inten * 0.82, inten * 0.58], axis=-1)
    return pygame.surfarray.make_surface(col.astype(np.uint8))


def build_vignette() -> pygame.Surface:
    s = pygame.Surface((W, H), pygame.SRCALPHA)
    xs = np.linspace(-1, 1, W)[:, None]
    ys = np.linspace(-1, 1, H)[None, :]
    d = np.sqrt(xs**2 * 0.8 + ys**2)
    a = np.clip((d - 0.62) / 0.7, 0, 1) ** 1.6 * 215
    px = pygame.surfarray.pixels3d(s)
    px[...] = (6, 4, 10)
    del px
    pa = pygame.surfarray.pixels_alpha(s)
    pa[...] = a.astype(np.uint8)
    del pa
    return s


def build_refl_fade() -> pygame.Surface:
    s = pygame.Surface((W, H - FLOOR), pygame.SRCALPHA)
    for i in range(H - FLOOR):
        a = int(255 * 0.32 * (1 - i / (H - FLOOR)) ** 1.5)
        pygame.draw.line(s, (255, 255, 255, a), (0, i), (W, i))
    return s


# ═══════════════════════════════════════════════════════════════════════════
# 9. RENDER DEL TOMATE (sombreado por píxel con numpy, cacheado)
# ═══════════════════════════════════════════════════════════════════════════

TOMATO_TONES = [(226, 36, 26), (206, 30, 26), (178, 24, 28), (138, 12, 24)]
GREEN_TONES = [(84, 172, 50), (76, 156, 46), (68, 138, 44), (60, 120, 40)]
ROT_TONES = [(128, 72, 40), (114, 62, 36), (100, 54, 34), (84, 46, 30)]


def tomato_tone(kind: str, bucket: int, ripe: float) -> np.ndarray:
    if kind == "podrida":
        return np.array(ROT_TONES[bucket], float)
    red = np.array(TOMATO_TONES[bucket], float)
    if kind == "verde":
        green = np.array(GREEN_TONES[bucket], float)
        # Al madurar pasa por naranja antes de llegar al rojo
        mid = np.array([222, 140, 40], float)
        return green + (mid - green) * min(1.0, ripe * 2) if ripe < 0.5 else mid + (red - mid) * (ripe - 0.5) * 2
    return red


def bake_tomato(r: int, bucket: int, kind: str = "roja", ripe: float = 1.0) -> pygame.Surface:
    return arrays_to_surface(*bake_arrays(r, bucket, kind, ripe))


def arrays_to_surface(col: np.ndarray, alpha: np.ndarray) -> pygame.Surface:
    surf = pygame.Surface(col.shape[:2], pygame.SRCALPHA)
    px = pygame.surfarray.pixels3d(surf)
    px[...] = col
    del px
    pa = pygame.surfarray.pixels_alpha(surf)
    pa[...] = alpha
    del pa
    return surf


def bake_arrays(r: int, bucket: int, kind: str = "roja", ripe: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Sombreado por píxel del tomate. Solo numpy: puede correr en otro hilo."""
    rx, ry = r, int(r * TOMATO_ASPECT)
    w, h = 2 * rx + 2, 2 * ry + 2
    xs = (np.arange(w) - w / 2 + 0.5) / rx
    ys = (np.arange(h) - h / 2 + 0.5) / ry
    nx, ny = np.meshgrid(xs, ys, indexing="ij")
    d2 = nx * nx + ny * ny
    nz = np.sqrt(np.clip(1 - d2, 0, 1))
    # Gajos: el normal se ondula alrededor del eje vertical
    lon = np.arctan2(nx, nz + 1e-6)
    lat = np.clip(1 - np.abs(ny), 0, 1)
    bump = 0.09 * np.sin(lon * 7) * lat
    nxp = nx + bump * nz
    nzp = nz - bump * nx * 0.5
    norm = np.sqrt(nxp**2 + ny**2 + nzp**2) + 1e-6
    nxp, nyp, nzp = nxp / norm, ny / norm, nzp / norm
    L = np.array([-0.5, -0.64, 0.58])
    L /= np.linalg.norm(L)
    ndl = nxp * L[0] + nyp * L[1] + nzp * L[2]
    lam = np.clip(ndl, 0, 1)
    base = tomato_tone(kind, bucket, ripe)
    dark = base * np.array([0.26, 0.10, 0.16]) if kind == "roja" or ripe > 0.7 else base * np.array([0.2, 0.22, 0.12])
    col = dark + (base - dark) * (0.14 + 0.86 * lam)[..., None]
    groove = (0.5 + 0.5 * np.cos(lon * 7)) ** 3 * lat * nz
    col *= (1 - 0.16 * groove)[..., None]
    # Moratones de baja frecuencia según el daño
    if bucket:
        rng = np.random.default_rng(r * 7 + bucket)
        m = np.zeros_like(nx)
        for _ in range(6):
            fx, fy, p1, p2 = rng.uniform(2, 6), rng.uniform(2, 6), rng.uniform(0, 6.3), rng.uniform(0, 6.3)
            m += np.sin(nx * fx + p1) * np.sin(ny * fy + p2)
        m = np.clip(m / 3, 0, 1)
        col *= (1 - (0.14 * bucket) * m)[..., None]
        col[..., 1] += 6 * bucket * m * (1 - lam)
    # Podrido: manchas negras y moho
    if kind == "podrida":
        rng3 = np.random.default_rng(r * 3 + bucket + 1)
        spots = np.zeros_like(nx)
        mold = np.zeros_like(nx)
        for _ in range(9):
            cx_, cy_, rr = rng3.uniform(-0.8, 0.8), rng3.uniform(-0.8, 0.8), rng3.uniform(0.08, 0.2)
            spots = np.maximum(spots, np.clip(1 - np.sqrt((nx - cx_) ** 2 + (ny - cy_) ** 2) / rr, 0, 1))
        for _ in range(5):
            cx_, cy_, rr = rng3.uniform(-0.7, 0.7), rng3.uniform(-0.9, 0.2), rng3.uniform(0.1, 0.22)
            d = np.sqrt((nx - cx_) ** 2 + (ny - cy_) ** 2) / rr
            mold = np.maximum(mold, np.clip(1 - d, 0, 1) ** 0.6)
        grain = rng3.random(nx.shape)
        mold *= 0.55 + 0.45 * grain
        col *= (1 - 0.75 * np.clip(spots * 2, 0, 1))[..., None]
        col = col * (1 - mold[..., None] * 0.8) + mold[..., None] * np.array([150, 160, 110]) * (0.4 + 0.6 * lam)[..., None]
    # Translucidez: la luz atraviesa la piel por el borde
    rim = (1 - nz) ** 2.3
    back = np.clip(-(nx * L[0] + ny * L[1]), 0, 1) * 0.65 + 0.35
    rim_col = np.array([255, 115, 25]) if kind == "roja" or ripe > 0.7 else np.array([200, 240, 60])
    if kind == "podrida":
        rim_col = np.array([150, 90, 20])
    col += (rim * back)[..., None] * rim_col * (0.62 - 0.12 * bucket)
    # Rebote cálido del suelo
    col += (np.clip(ny, 0, 1) ** 3 * nz)[..., None] * np.array([110, 40, 18]) * 0.55
    # Especular difuso + punto duro + reflejo frío de la claraboya
    Hv = L + np.array([0, 0, 1.0])
    Hv /= np.linalg.norm(Hv)
    nh = np.clip(nxp * Hv[0] + nyp * Hv[1] + nzp * Hv[2], 0, 1)
    gloss = 0.35 if kind == "podrida" else 1.0
    col += (nh**28)[..., None] * np.array([255, 210, 190]) * 0.36 * gloss
    col += (nh**420)[..., None] * 255 * 1.1 * gloss
    # Piel: motitas
    rng2 = np.random.default_rng(r)
    speck = (rng2.random(nx.shape) > 0.9975) * nz
    col += speck[..., None] * 38
    col = np.clip(col, 0, 255)
    alpha = np.clip((1 - np.sqrt(d2)) * min(rx, ry) * 1.2, 0, 1) * 255
    return col.astype(np.uint8), alpha.astype(np.uint8)


class TomatoArt:
    """Horneado del tomate en un hilo aparte: el combate nunca se congela."""

    def __init__(self):
        self.cache: dict[tuple[int, int, str, int], pygame.Surface] = {}
        self.pending: dict[tuple[int, int, str, int], Future] = {}
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hornea")
        self.sync_bakes = 0  # veces que hubo que esperar a un horneado (tirón)

    def request(self, key: tuple[int, int, str, int]) -> None:
        if key not in self.cache and key not in self.pending:
            r, bucket, kind, q = key
            self.pending[key] = self.pool.submit(bake_arrays, r, bucket, kind, q / 4)

    def poll(self) -> None:
        for key in [k for k, f in self.pending.items() if f.done()]:
            self.cache[key] = arrays_to_surface(*self.pending.pop(key).result())

    def prefetch(self, level: int) -> None:
        """Encarga todo lo que necesitará el tomate de ese nivel."""
        r, kind = tomato_radius(level), tomato_kind(level)
        for q in (0, 1, 2, 3, 4) if kind == "verde" else (4,):
            for b in range(4):
                self.request((r, b, kind, q))

    def trim(self, levels: tuple[int, ...]) -> None:
        keep = {(tomato_radius(lv), tomato_kind(lv)) for lv in levels} | {(CHERRY_R, "roja")}
        for key in [k for k in self.cache if (k[0], k[2]) not in keep]:
            del self.cache[key]

    def base(self, r: int, bucket: int, kind: str = "roja", ripe_q: int = 4) -> pygame.Surface:
        key = (r, bucket, kind, ripe_q)
        self.poll()
        s = self.cache.get(key)
        if s is not None:
            return s
        self.request(key)
        # Mientras se hornea, el tramo más parecido ya listo
        near = [k for k in self.cache if k[0] == r and k[2] == kind]
        if near:
            return self.cache[min(near, key=lambda k: abs(k[1] - bucket) + abs(k[3] - ripe_q))]
        # Nada parecido (primer fotograma del juego): se hornea aquí mismo, sin esperar a la cola
        fut = self.pending.pop(key)
        self.sync_bakes += 1
        s = arrays_to_surface(*fut.result()) if fut.done() or not fut.cancel() else bake_tomato(r, bucket, kind, ripe_q / 4)
        self.cache[key] = s
        return s

    def warm(self, t: "Tomato") -> None:
        self.trim((t.level, t.level + 1))
        self.prefetch(t.level)
        self.prefetch(t.level + 1)  # el siguiente, mientras se juega este

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)

    def cherry(self) -> pygame.Surface:
        key = (CHERRY_R, 0, "roja", 4)
        if key not in self.cache:
            self.cache[key] = bake_tomato(CHERRY_R, 0)
        return self.cache[key]

    def render(self, t: Tomato) -> tuple[pygame.Surface, float, float]:
        """Compone el tomate del fotograma. Devuelve la capa y su origen."""
        sx, sy = t.scale()
        base = self.base(t.r, t.bucket(), *t.art_key())
        bw, bh = max(4, int(base.get_width() * sx)), max(4, int(base.get_height() * sy))
        body = pygame.transform.smoothscale(base, (bw, bh))
        pad = int(t.r * 0.42)
        layer = pygame.Surface((bw + pad * 2, bh + pad * 2), pygame.SRCALPHA)
        layer.blit(body, (pad, pad))
        cx, cy = layer.get_width() / 2, layer.get_height() / 2
        rx, ry = t.radii()
        ct, st = math.cos(t.theta), math.sin(t.theta)

        def P(u, v):  # disco unidad local (rotado con el tomate) → capa
            return (cx + (u * ct - v * st) * rx, cy + (u * st + v * ct) * ry)

        k = t.r / 220
        # Moratones y grietas
        for c in t.cracks:
            if c.bruise and t.bucket() >= 1:
                u, v = c.pts[2]
                b = soft_blob(18 * k * c.width + 6, (60, 0, 20), 90 + 30 * t.bucket(), 1.2)
                blit_center(layer, b, *P(u, v))
        if t.kind == "podrida":
            rim_c, flesh, hi = (40, 20, 6), (96, 56, 22), (150, 110, 50)
        elif t.armor > 0:
            rim_c, flesh, hi = (40, 70, 20), (190, 220, 130), (240, 255, 200)
        else:
            rim_c, flesh, hi = (70, 0, 12), (176, 18, 30), (250, 96, 72)
        for c in t.cracks:
            pts = [P(u, v) for u, v in c.pts]
            grow = min(1.0, c.age / 0.12)
            n = max(2, int(len(pts) * grow))
            pts = pts[:n]
            w0 = (4 + 3 * c.width) * k
            outer = crack_wedge(pts, w0 * 1.5 + 2)
            pygame.draw.polygon(layer, rim_c, outer)
            pygame.draw.polygon(layer, flesh, crack_wedge(pts, w0))
            pygame.draw.lines(layer, hi, False, pts[: max(2, n - 1)], max(1, int(w0 / 3)))
            for i in range(1, n - 1):
                pygame.draw.circle(layer, (250, 228, 160), pts[i], max(1.5, 2.0 * k))
            pygame.draw.circle(layer, (255, 240, 230), pts[0], max(1.5, 1.8 * k))  # brillo húmedo
            # rama secundaria
            if n >= 4:
                a = c.ang + 0.6
                tip = (c.pts[2][0] + math.cos(a) * 0.08, c.pts[2][1] + math.sin(a) * 0.08)
                pygame.draw.polygon(layer, rim_c, crack_wedge([pts[2], P(*tip)], w0 * 0.6 + 1))
        # Punto débil: pulso luminoso
        if t.state != "intro":
            a = t.weak
            u, v = math.cos(a) * 0.86, math.sin(a) * 0.86
            wx, wy = P(u, v)
            pulse = 0.55 + 0.45 * math.sin(t.t * 7)
            big = 2.2 if t.big_weak else 1.0
            blit_add(layer, glow((34 * k + 10 * pulse) * big, scale_c((255, 170, 60), 0.5 + 0.5 * pulse), 1.6), wx, wy)
            blit_add(layer, glow(10 * k + 4, (255, 240, 200), 2.0), wx, wy)
        # Bulto del chorro de jugo
        if t.state == "tele" and t.attack == "jet":
            p = clamp(t.timer / t.tele("jet"), 0, 1)
            jy = t.jet_y() - t.y
            bx = cx + t.dir * t.rim_dx(t.jet_y()) * 0.93
            rad = (14 + 30 * ease_out(p)) * k
            pygame.draw.circle(layer, (120, 8, 18), (bx, cy + jy), rad + 2)
            pygame.draw.circle(layer, (220, 40, 30), (bx, cy + jy), rad)
            pygame.draw.circle(layer, (255, 170, 140), (bx - rad * 0.3, cy + jy - rad * 0.35), rad * 0.3)
        draw_calyx(layer, P, rx, ry, t.r, t.theta, 3 if t.kind == "podrida" else t.bucket())
        # Destello de impacto y furia
        if t.flash > 0:
            v = int(150 * t.flash)
            layer.fill((v, v, v), special_flags=pygame.BLEND_RGB_ADD)
        if t.rainbow:
            h = t.t * 0.6
            tint = tuple(int(150 + 105 * (0.5 + 0.5 * math.sin(h + o))) for o in (0.0, 2.1, 4.2))
            layer.fill(tint, special_flags=pygame.BLEND_RGB_MULT)
            layer.fill(tuple(int(60 * (0.5 + 0.5 * math.sin(h + o))) for o in (3.0, 5.1, 1.0)), special_flags=pygame.BLEND_RGB_ADD)
        if t.fury() and t.state != "dead":
            v = 0.5 + 0.5 * math.sin(t.t * 14)
            layer.fill((int(190 + 50 * v), int(120 + 40 * v), int(130 + 40 * v)), special_flags=pygame.BLEND_RGB_MULT)
        ox = random.uniform(-t.tremble, t.tremble)
        oy = random.uniform(-t.tremble, t.tremble) * 0.5
        return layer, t.x - cx + ox, t.y - cy + oy


def crack_wedge(pts: list[tuple[float, float]], w0: float) -> list[tuple[float, float]]:
    """Polígono en cuña a lo largo de una polilínea: ancho en el borde, afilado dentro."""
    n = len(pts)
    left, right = [], []
    for i, (x, y) in enumerate(pts):
        ax, ay = pts[max(0, i - 1)]
        bx, by = pts[min(n - 1, i + 1)]
        dx, dy = bx - ax, by - ay
        d = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / d, dx / d
        w = w0 * (1 - i / max(1, n - 1)) ** 0.8 / 2
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
    return left + right[::-1]


def draw_calyx(layer: pygame.Surface, P, rx: float, ry: float, r: int, theta: float, bucket: int) -> None:
    """Cáliz de seis hojas en perspectiva con su tallo."""
    top_v = -0.93
    green = mix((70, 150, 50), (90, 100, 40), bucket / 3)
    dark = scale_c(green, 0.45)
    L = 0.36
    leaves = []
    for i in range(6):
        a = i * math.pi / 3 + 0.35
        depth = math.sin(a)  # >0: hacia el espectador
        leaves.append((depth, a))
    leaves.sort()
    for depth, a in leaves:
        tipx = math.cos(a) * L
        tipy = top_v + depth * L * 0.32 + abs(math.cos(a)) * 0.1
        perp = 0.07
        mx_, my_ = tipx * 0.5, top_v + (tipy - top_v) * 0.5
        nxx, nyy = -math.sin(a) * perp, math.cos(a) * perp * 0.4
        pts = [P(0.02 * math.sin(a), top_v), P(mx_ + nxx, my_ + nyy), P(tipx, tipy), P(mx_ - nxx, my_ - nyy)]
        shade = 0.7 + 0.35 * depth
        pygame.draw.polygon(layer, dark, pts)
        inner = [lerp2(pts[0], pts[2], 0.0), lerp2(pts[1], pts[2], 0.15), pts[2], lerp2(pts[3], pts[2], 0.15)]
        pygame.draw.polygon(layer, scale_c(green, shade), inner)
        pygame.draw.line(layer, scale_c(green, shade * 1.35), pts[0], lerp2(pts[0], pts[2], 0.85), 2)
    # Tallo curvado
    base_pt = P(0, top_v)
    tip = P(0.06, top_v - 0.15)
    mid = P(0.0, top_v - 0.09)
    w = max(4, int(r * 0.05))
    pygame.draw.line(layer, scale_c(green, 0.5), base_pt, mid, w + 3)
    pygame.draw.line(layer, scale_c(green, 0.5), mid, tip, w + 2)
    pygame.draw.line(layer, scale_c(green, 0.95), base_pt, mid, w)
    pygame.draw.line(layer, scale_c(green, 0.95), mid, tip, w - 1)
    pygame.draw.circle(layer, scale_c(green, 1.3), tip, w * 0.6)


# ═══════════════════════════════════════════════════════════════════════════
# 10. RENDER DE RUFO (vectorial, supermuestreado ×2)
# ═══════════════════════════════════════════════════════════════════════════

SS = 2  # supermuestreo
CANVAS = (190, 220)  # tamaño final del sprite
ANCHOR = (95, 180)  # pies dentro del sprite
OUT = (24, 18, 26)
SKIN = (240, 192, 152)
JACKET = (244, 242, 236)
APRON = (228, 214, 188)
PANTS = (74, 80, 108)
GLOVE = (222, 30, 38)


class RufoArt:
    def __init__(self):
        self.big = pygame.Surface((CANVAS[0] * SS, CANVAS[1] * SS), pygame.SRCALPHA)

    def render(self, r: Rufo) -> pygame.Surface:
        cv = self.big
        cv.fill((0, 0, 0, 0))
        pose = glove_pose(r)
        fc = r.facing
        s = clamp(r.sq.x, -0.3, 0.35)
        sxk, syk = 1 + s * 0.8, 1 - s
        lean = pose["lean"] * fc
        if r.state == "dead":
            lean = -1.45 * fc
        ca, sa = math.cos(lean), math.sin(lean)
        ax, ay = ANCHOR[0] * SS, ANCHOR[1] * SS
        cr = pose["cr"]

        def P(x, y):
            x *= fc * sxk
            y *= syk
            return (ax + (x * ca - y * sa) * SS, ay + (x * sa + y * ca) * SS)

        def circ(c, rad, col, ol=True):
            rr = rad * SS * (sxk + 1) / 2
            if ol:
                pygame.draw.circle(cv, OUT, c, rr + 2.5)
            pygame.draw.circle(cv, col, c, rr)

        def limb(a, b, w, col):
            pygame.draw.line(cv, OUT, a, b, int(w * SS + 5))
            pygame.draw.circle(cv, OUT, a, (w * SS + 5) / 2)
            pygame.draw.circle(cv, OUT, b, (w * SS + 5) / 2)
            pygame.draw.line(cv, col, a, b, int(w * SS))
            pygame.draw.circle(cv, col, a, w * SS / 2)
            pygame.draw.circle(cv, col, b, w * SS / 2)

        hip_y = -18 + cr * 13
        sh_y = pose["sh_y"]
        # Piernas
        on_floor = r.on_ground or r.state == "dead"
        legs = []
        for side, ph in ((-1, 0.0), (1, math.pi)):
            hx = side * 4.5
            if on_floor and abs(r.vx) > 40 and r.state in ("normal", "attack"):
                q = math.sin(r.run_phase * 2 + ph)
                fx, fy = hx + q * 9, -max(0.0, math.cos(r.run_phase * 2 + ph)) * 6
            elif not on_floor:
                fx, fy = hx + (5 if side > 0 else -3), -9 if r.vy < 0 else -3
            else:
                fx, fy = hx * (1 + cr * 0.8), 0.0
            knee = ((hx + fx) / 2 + 3 + cr * 7, (hip_y + fy) / 2 - cr * 2)
            legs.append((side, (hx, hip_y), knee, (fx, fy)))
        for side, hip, knee, foot in legs:
            k = 0.78 if side < 0 else 1.0
            limb(P(*hip), P(*knee), 9, scale_c(PANTS, k))
            limb(P(*knee), P(*foot), 8, scale_c(PANTS, k))
            fp = P(foot[0] + 3, foot[1] - 2)
            sh = pygame.Rect(0, 0, 17 * SS, 9 * SS)
            sh.center = (int(fp[0]), int(fp[1]))
            pygame.draw.ellipse(cv, OUT, sh.inflate(5, 5))
            pygame.draw.ellipse(cv, scale_c((38, 32, 34), k), sh)
        # Brazo y guante traseros
        sh_b = (-5, sh_y - 1)
        gb = (sh_b[0] + pose["gb"][0], sh_b[1] + pose["gb"][1])
        limb(P(*sh_b), P(*gb), 6.5, scale_c(JACKET, 0.8))
        self._glove(cv, P(*gb), 0.8, sxk, circ)
        # Cuerpo (chaquetilla)
        body_top, body_bot = sh_y - 2, hip_y + 3
        torso = [P(x, y) for x, y in rounded_box(-14, body_top, 13, body_bot, 7, 2)]
        pygame.draw.polygon(cv, OUT, torso, 5)
        pygame.draw.polygon(cv, JACKET, torso)
        pygame.draw.polygon(cv, (214, 214, 226), [P(x, y) for x, y in rounded_box(-13, body_top + 3, -6, body_bot - 2, 3, 0)])
        pygame.draw.line(cv, WHITE, P(7, body_bot - 5), P(7, body_top + 4), 3 * SS)
        for by in (body_top + 5, body_top + 11):
            pygame.draw.circle(cv, (150, 150, 165), P(10, by), 1.6 * SS)
        # Delantal con sus manchas
        ap = [P(-12, body_top + 11), P(12, body_top + 11), P(15, hip_y + 2), P(-15, hip_y + 2)]
        pygame.draw.polygon(cv, OUT, ap, 5)
        pygame.draw.polygon(cv, APRON, ap)
        pygame.draw.line(cv, (200, 186, 160), P(-13, hip_y), P(13, hip_y), 2 * SS)
        for u, v, rad in r.stains:
            pygame.draw.circle(cv, (176, 26, 34), P(u * 12, lerp(body_top + 13, hip_y, v)), rad * SS)
        # Cabeza
        hs = 1.55 if r.bighead else 1.0  # truco: Rufo cabezón
        hc = (2, sh_y - 14 - 13 * (hs - 1))

        def Hd(dx, dy):  # punto de la cara, escalado con la cabeza
            return P(hc[0] + dx * hs, hc[1] + dy * hs)

        circ(P(*hc), 13 * hs, SKIN)
        pygame.draw.circle(cv, (255, 222, 196), Hd(-4, -4), 5 * SS * hs)
        circ(Hd(-9, 1), 3.6 * hs, scale_c(SKIN, 0.9))  # oreja
        pygame.draw.circle(cv, (245, 140, 130), Hd(6, 4), 3 * SS * hs)  # mejilla
        blink = r.blink_t < 0
        for ex in (6.5, 12.0):
            e = Hd(ex - 2, -1)
            if blink or r.state == "dead":
                pygame.draw.line(cv, OUT, (e[0] - 4, e[1]), (e[0] + 4, e[1]), 3)
            else:
                pygame.draw.ellipse(cv, OUT, (e[0] - 2.4 * SS * hs, e[1] - 3.2 * SS * hs, 4.8 * SS * hs, 6.4 * SS * hs))
                pygame.draw.circle(cv, WHITE, (e[0] - SS * 0.8 * fc * -1, e[1] - SS * 1.2), SS * hs)
        # Cejas testarudas: bajan hacia la nariz
        pygame.draw.line(cv, OUT, Hd(1.5, -7), Hd(7.5, -5), 3 * SS // 2 + 1)
        pygame.draw.line(cv, OUT, Hd(9, -5.5), Hd(14, -6.5), 3 * SS // 2 + 1)
        pygame.draw.circle(cv, scale_c(SKIN, 0.86), Hd(13.5, 2), 2.6 * SS * hs)
        m = pose["mouth"]
        if m == "o":
            pygame.draw.circle(cv, OUT, Hd(9, 7), 2.3 * SS * hs)
        elif m == "grit":
            pygame.draw.line(cv, OUT, Hd(6, 7), Hd(12, 7), 4 * SS // 2 + 2)
            pygame.draw.line(cv, WHITE, Hd(7, 7), Hd(11, 7), 2)
        else:
            pygame.draw.line(cv, OUT, Hd(7, 7.5), Hd(12, 6.8), 3)
        # Gorro de chef demasiado alto (con su propio muelle)
        hb = (hc[0], hc[1] - 11 * hs)
        hang = r.hat.x * fc

        c2, s2 = math.cos(hang), math.sin(hang)

        def Q(x, y):  # desplazamiento relativo a la base del gorro
            x, y = x * hs, y * hs
            return P(hb[0] + x * c2 - y * s2, hb[1] + x * s2 + y * c2)

        col = [Q(-12, -2), Q(-15, -38), Q(15, -38), Q(12, -2)]
        pygame.draw.polygon(cv, OUT, col, 6)
        pygame.draw.polygon(cv, (250, 250, 252), col)
        for px_, py_, pr in ((-9, -38, 9.5), (0, -42, 10.5), (9, -38, 9.5)):
            circ(Q(px_, py_), pr * hs, (250, 250, 252))
        for px_, py_, pr in ((-9, -38, 9.5), (0, -42, 10.5), (9, -38, 9.5)):
            pygame.draw.circle(cv, (250, 250, 252), Q(px_, py_ + 3), pr * SS * hs)
        pygame.draw.polygon(cv, (250, 250, 252), [Q(-13, -3), Q(-15, -38), Q(15, -38), Q(13, -3)])
        pygame.draw.line(cv, (214, 214, 226), Q(-5, -5), Q(-6, -34), 2 * SS)
        pygame.draw.line(cv, (214, 214, 226), Q(5, -5), Q(6, -34), 2 * SS)
        pygame.draw.circle(cv, WHITE, Q(-4, -45), 4 * SS * hs)
        band = [Q(-13, -1), Q(13, -1), Q(13, -8), Q(-13, -8)]
        pygame.draw.polygon(cv, OUT, band, 5)
        pygame.draw.polygon(cv, (232, 232, 240), band)
        # Brazo y guante delanteros
        sh_f = (3, sh_y)
        gf = (sh_f[0] + pose["gf"][0], sh_f[1] + pose["gf"][1])
        limb(P(*sh_f), P(*gf), 7, JACKET)
        self._glove(cv, P(*gf), 1.0, sxk, circ)

        spr = pygame.transform.smoothscale(cv, CANVAS)
        if r.juice > 0:
            k = clamp(r.juice / 1.5, 0, 1)
            spr.fill(mix((255, 255, 255), (255, 120, 110), k), special_flags=pygame.BLEND_RGB_MULT)
        if r.flash > 0:
            v = int(255 * r.flash)
            spr.fill((v, v, v), special_flags=pygame.BLEND_RGB_ADD)
        if r.state == "charge":
            v = int(35 + 30 * math.sin(r.time * 30))
            spr.fill((v, int(v * 0.75), 0), special_flags=pygame.BLEND_RGB_ADD)
        return spr

    def _glove(self, cv, c, k, sxk, circ) -> None:
        circ(c, 11.5, scale_c(GLOVE, k))
        rr = 11.5 * SS
        pygame.draw.circle(cv, scale_c((255, 120, 110), k), (c[0] - rr * 0.32, c[1] - rr * 0.35), rr * 0.42)
        pygame.draw.circle(cv, (255, 235, 230), (c[0] - rr * 0.38, c[1] - rr * 0.45), rr * 0.13)
        pygame.draw.circle(cv, scale_c((150, 14, 24), k), (c[0] + rr * 0.35, c[1] + rr * 0.35), rr * 0.3)


# ═══════════════════════════════════════════════════════════════════════════
# 11. TEXTO E INTERFAZ
# ═══════════════════════════════════════════════════════════════════════════


class TextKit:
    def __init__(self):
        self.fonts: dict[int, pygame.font.Font] = {}
        self.cache: dict[tuple, pygame.Surface] = {}

    def font(self, size: int) -> pygame.font.Font:
        f = self.fonts.get(size)
        if f is None:
            f = pygame.font.Font(None, size)
            self.fonts[size] = f
        return f

    def plain(self, s: str, size: int, color) -> pygame.Surface:
        key = ("p", s, size, tuple(color))
        img = self.cache.get(key)
        if img is None:
            img = self.font(size).render(s, True, color)
            self._store(key, img)
        return img

    def outlined(self, s: str, size: int, color, outline=OUT, w: int = 3) -> pygame.Surface:
        key = ("o", s, size, tuple(color), tuple(outline), w)
        img = self.cache.get(key)
        if img is None:
            f = self.font(size)
            fg = f.render(s, True, color)
            bgc = f.render(s, True, outline)
            img = pygame.Surface((fg.get_width() + 2 * w, fg.get_height() + 2 * w + 2), pygame.SRCALPHA)
            for dx in range(-w, w + 1):
                for dy in range(-w, w + 1):
                    if dx * dx + dy * dy <= w * w + 1:
                        img.blit(bgc, (w + dx, w + dy + 2))
            img.blit(fg, (w, w))
            self._store(key, img)
        return img

    def _store(self, key, img) -> None:
        if len(self.cache) > 600:
            self.cache.clear()
        self.cache[key] = img


def heart_points(cx: float, cy: float, s: float) -> list[tuple[float, float]]:
    pts = []
    for i in range(32):
        t = i / 32 * math.tau
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((cx + x * s / 16, cy - y * s / 16))
    return pts


_heart_cache: dict = {}


def draw_heart(surf, cx, cy, s, full: bool, pulse: float = 0.0) -> None:
    """Corazón supermuestreado ×4 (bordes suaves), cacheado por tamaño."""
    s = round(s * (1 + pulse), 1)
    key = (s, full)
    img = _heart_cache.get(key)
    if img is None:
        k = 4
        size = int((s + 6) * 2.4 * k)
        big = pygame.Surface((size, size), pygame.SRCALPHA)
        c = size / 2
        pygame.draw.polygon(big, OUT, heart_points(c, c + k, (s + 3) * k))
        if full:
            pygame.draw.polygon(big, (225, 34, 48), heart_points(c, c, s * k))
            pygame.draw.polygon(big, (180, 18, 36), heart_points(c + s * k * 0.12, c + s * k * 0.16, s * k * 0.78))
            pygame.draw.polygon(big, (232, 44, 56), heart_points(c - s * k * 0.05, c - s * k * 0.05, s * k * 0.8))
            pygame.draw.circle(big, (255, 160, 160), (c - s * k * 0.42, c - s * k * 0.38), s * k * 0.22)
        else:
            pygame.draw.polygon(big, (70, 40, 50), heart_points(c, c, s * k))
        img = pygame.transform.smoothscale(big, (size // k, size // k))
        _heart_cache[key] = img
    blit_center(surf, img, cx, cy)


def panel(size, alpha=170, radius=14) -> pygame.Surface:
    p = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.rect(p, (14, 10, 18, alpha), p.get_rect(), border_radius=radius)
    pygame.draw.rect(p, (255, 255, 255, 40), p.get_rect(), 2, border_radius=radius)
    return p


def build_title(txt: TextKit) -> pygame.Surface:
    f = txt.font(170)
    word = "TOMATOES"
    fg = f.render(word, True, WHITE)
    w, h = fg.get_size()
    grad = pygame.Surface((w, h), pygame.SRCALPHA)
    for y in range(h):
        pygame.draw.line(grad, mix((255, 226, 120), (232, 32, 30), (y / h) ** 0.9) + (255,), (0, y), (w, y))
    fg.blit(grad, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    out = pygame.Surface((w + 40, h + 40), pygame.SRCALPHA)
    dark = f.render(word, True, (40, 6, 12))
    for dx in range(-6, 7, 2):
        for dy in range(-6, 9, 2):
            if dx * dx + dy * dy <= 50:
                out.blit(dark, (20 + dx, 20 + dy + 4))
    out.blit(fg, (20, 20))
    shine = f.render(word, True, (255, 255, 255))
    shine.set_alpha(70)
    out.blit(shine, (18, 17))
    out.blit(fg, (20, 20))
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 12. EL JUEGO
# ═══════════════════════════════════════════════════════════════════════════


class Game:
    def __init__(self, screen: pygame.Surface, audio: Audio, keymap: dict[str, list[str]], opts: dict | None = None):
        self.screen = screen
        self.audio = audio
        self.keymap = keymap
        self.inp = Input(keymap)
        self.txt = TextKit()
        self.scene = Scene()
        self.fx = FX(self.scene)
        self.tart = TomatoArt()
        self.tart.prefetch(1)  # el tomate del nivel 1 se hornea mientras estás en el título
        self.rart = RufoArt()
        self.world = pygame.Surface((W, H)).convert()
        self.refl = pygame.Surface((W, H - FLOOR), pygame.SRCALPHA)
        self.title_img = build_title(self.txt)
        self.top = load_records()
        self.best = self.top[0]["score"] if self.top else 0
        self.bloom = True
        self.debug = False
        self.paused = False
        self.running = True
        self.fps = 0.0
        self.buf: dict[str, float] = {}
        self.t = 0.0
        self.acc = 0.0
        self.real_t = 0.0
        self.trauma = 0.0
        self.hitstop = 0.0
        self.slow_t = 0.0
        self.slow_k = 1.0
        self.zoom_t = 0.0
        self.zoom_at = (W / 2, H / 2)
        self.ab_t = 0.0
        self.flash = 0.0
        self.red = 0.0
        self.dash_overlap = False
        self.jets: list[dict] = []
        self.seeds: list[list] = []
        self.cherries: list[dict] = []
        self.puddles: list[list[float]] = []
        self.slipping = False
        self.diff_name = "Normal"
        self.dodged: set[str] = set()
        self.hit_by: set[str] = set()
        self.banner: tuple[str, str, float, float] | None = None
        self.combo_pop: tuple[str, float] | None = None
        self.opts: dict = dict(OPT_DEFAULT) | (opts or {})
        self.cheats: dict = dict(CHEAT_DEFAULT) | (self.opts.get("cheats") or {})
        self.cheated = False  # la partida actual usó trucos
        self.diff_name = self.opts["difficulty"] if self.opts["difficulty"] in DIFFICULTY else "Normal"
        self.bloom = self.opts["bloom"]
        audio.set_volumes(self.opts["music"], self.opts["sfx"])
        self.menu = "main"
        self.cursor = 0
        self.idle_t = 0.0
        self.demo = False
        self.bot: Bot | None = None
        self.entering = False
        self.name = ["A", "A", "A"]
        self.name_i = 0
        self.rank = -1
        self.tip: tuple[str, float] | None = None
        self.tips_seen: set[str] = set()
        self.alpha = 0.0
        self.shown_score = 0.0
        self.state = "title"
        self.over_t = 0.0
        self.new_record = False
        self.to_title()
        audio.start_music()

    # ── estados ─────────────────────────────────────────────────────────
    def to_title(self) -> None:
        self.state = "title"
        self.menu = "main"
        self.cursor = 0
        self.idle_t = 0.0
        self.demo = False
        self.paused = False
        self.inp.virtual = set()
        self.banner = None
        self.tip = None
        self.flash = self.red = self.trauma = 0.0
        self.fx.clear()
        self.scene.reset()
        self.rufo = Rufo(590)
        self.rufo.bighead = self.cheats["bighead"]
        self.tomato: Tomato | None = Tomato(1, x=940)
        self.tomato.sleeping = True
        self.tomato.state = "idle"
        self.tomato.y = FLOOR - self.tomato.radii()[1]
        self.title_t = 0.0
        self.demo_t = 0.0
        self.jets.clear()
        self.seeds.clear()
        self.cherries.clear()
        self.puddles.clear()

    def new_game(self, demo: bool = False) -> None:
        self.state = "play"
        self.demo = demo  # en la demo no hay trucos
        self.sub = "fight"
        self.sub_t = 0.0
        self.fx.clear()
        self.scene.reset()
        self.hearts = MAX_HEARTS
        self.time_left = ROUND_TIME
        self.score = 0
        self.combo = 0
        self.last_hit = -9.0
        self.level = self.cheat("start_level")
        self.cheated = not demo and self.cheats_on()
        self.stats = {"tomatoes": 0, "max_combo": 0, "crits": 0, "perfect": 0}
        self.rufo = Rufo(300)
        self.rufo.bighead = self.cheat("bighead")
        self.tomato = Tomato(self.level, diff=self.diff())
        self.dress(self.tomato)
        self.tart.warm(self.tomato)
        self.jets.clear()
        self.seeds.clear()
        self.cherries.clear()
        self.puddles.clear()
        self.buf.clear()
        self.dodged.clear()
        self.hit_by.clear()
        self.paused = False
        self.slow_t = self.hitstop = 0.0
        self.flash = self.red = self.trauma = self.zoom_t = self.ab_t = 0.0
        self.combo_pop = None
        self.new_record = False
        self.entering = False
        self.tip = None
        self.tips_seen = set()
        self.shown_score = 0.0
        self.show_banner(f"NIVEL {self.level}", "Con trucos: la puntuación no entra en la tabla" if self.cheated else "¡Revienta el tomate!", 1.8)
        self.audio.play("select")

    def game_over(self) -> None:
        self.rank = -1
        if self.demo:
            self.to_title()
            return
        self.state = "over"
        self.over_t = 0.0
        self.inp.virtual = set()
        self.new_record = self.score > self.best
        self.entering = not self.cheated and self.score > 0 and (len(self.top) < 10 or self.score > self.top[-1]["score"])
        self.new_record = self.new_record and not self.cheated
        self.name, self.name_i = list(self.opts.get("last_name", "AAA")[:3].ljust(3, "A")), 0
        self.audio.play("over")

    def start_demo(self) -> None:
        """Modo demo: el bot juega solo hasta que alguien toque algo (sin trucos)."""
        self.new_game(demo=True)
        self.bot = Bot()
        self.show_banner("DEMO", "Pulsa cualquier tecla", 2.0)

    def commit_name(self) -> None:
        name = "".join(self.name)
        entry = {"name": name, "score": self.score, "level": self.level, "diff": self.diff_name}
        self.top.append(entry)
        self.top.sort(key=lambda e: -e["score"])
        self.top = self.top[:10]
        self.rank = self.top.index(entry)
        self.best = self.top[0]["score"]
        self.entering = False
        self.opts["last_name"] = name
        save_records(self.top)
        self.save_opts()
        self.audio.play("level")

    def save_opts(self) -> None:
        self.opts["cheats"] = dict(self.cheats)
        save_json(CFG_DIR / "config.json", {"keys": self.keymap, "options": self.opts})

    def cheat(self, key: str):
        """Valor de un truco; en la demo no hay trucos."""
        return CHEAT_DEFAULT[key] if self.demo else self.cheats[key]

    def dress(self, t: "Tomato") -> None:
        t.big_weak = self.cheat("bigweak")
        t.rainbow = self.cheat("rainbow")

    def cheats_on(self) -> bool:
        return any(self.cheats[k] != CHEAT_DEFAULT[k] for k in self.cheats if k not in COSMETIC_CHEATS)

    def cheat_value(self, label: str) -> str:
        key = dict(CHEATS).get(label)
        if key is None:
            return ""
        v = self.cheats[key]
        if key == "start_level":
            return f"{v}  ({KIND_NAMES[tomato_kind(v)].lower()})"
        if key == "speed":
            return f"{v} %"
        return "Sí" if v else "No"

    def change_cheat(self, label: str, d: int) -> None:
        key = dict(CHEATS)[label]
        c = self.cheats
        if key == "start_level":
            c[key] = int(clamp(c[key] + d, 1, 16))
        elif key == "speed":
            steps = [50, 75, 100, 125, 150]
            c[key] = steps[int(clamp(steps.index(c[key]) + d if c[key] in steps else 2, 0, len(steps) - 1))]
        else:
            c[key] = not c[key]
        self.audio.play("ready" if c[key] else "select")
        self.save_opts()

    # ── menús ───────────────────────────────────────────────────────────
    def option_value(self, item: str) -> str:
        o = self.opts
        return {
            "DIFICULTAD": f"<  {self.diff_name}  >",
            "Dificultad": self.diff_name,
            "Música": f"{o['music']} / 10",
            "Efectos": f"{o['sfx']} / 10",
            "Sacudida de cámara": f"{o['shake']} %",
            "Destellos": "Normales" if o["flashes"] else "Reducidos",
            "Bloom": "Sí" if self.bloom else "No",
            "Vibración del mando": "Sí" if o["rumble"] else "No",
            "Pantalla completa": "Sí" if o["fullscreen"] else "No",
            "Tutorial": "Sí" if o["tutorial"] else "No",
        }.get(item, "") or self.cheat_value(item)

    def change_option(self, item: str, d: int) -> None:
        o = self.opts
        if item in ("DIFICULTAD", "Dificultad"):
            self.diff_name = DIFF_ORDER[(DIFF_ORDER.index(self.diff_name) + d) % len(DIFF_ORDER)]
            o["difficulty"] = self.diff_name
        elif item in ("Música", "Efectos"):
            key = "music" if item == "Música" else "sfx"
            o[key] = int(clamp(o[key] + d, 0, 10))
            self.audio.set_volumes(o["music"], o["sfx"])
        elif item == "Sacudida de cámara":
            o["shake"] = int(clamp(o["shake"] + 25 * d, 0, 100))
            self.shake(0.5 * o["shake"] / 100)
        elif item == "Destellos":
            o["flashes"] = not o["flashes"]
        elif item == "Bloom":
            self.bloom = o["bloom"] = not self.bloom
        elif item == "Vibración del mando":
            o["rumble"] = not o["rumble"]
            self.rumble(0.6, 0.6, 200)
        elif item == "Pantalla completa":
            o["fullscreen"] = not o["fullscreen"]
            try:
                pygame.display.toggle_fullscreen()
            except pygame.error:
                pass
        elif item == "Tutorial":
            o["tutorial"] = not o["tutorial"]
        elif item in dict(CHEATS):
            self.change_cheat(item, d)
            if self.state == "title":
                self.rufo.bighead = self.cheats["bighead"]
            return
        self.audio.play("select")
        self.save_opts()

    def menu_input(self, acts: list[str]) -> None:
        if self.menu == "records":
            if "confirm" in acts or "pause" in acts:
                self.menu, self.cursor = "main", MENU_MAIN.index("RÉCORDS")
                self.audio.play("select")
            return
        items = {"main": MENU_MAIN, "options": MENU_OPTIONS, "cheats": MENU_CHEATS}[self.menu]
        if "up" in acts:
            self.cursor = (self.cursor - 1) % len(items)
            self.audio.play("select", 0.5)
        if "down" in acts:
            self.cursor = (self.cursor + 1) % len(items)
            self.audio.play("select", 0.5)
        item = items[self.cursor]
        for a, d in (("left", -1), ("right", 1)):
            if a in acts and self.option_value(item):
                self.change_option(item, d)
        if "confirm" in acts:
            if item == "JUGAR":
                self.new_game()
            elif item == "OPCIONES":
                self.menu, self.cursor = "options", 0
                self.audio.play("select")
            elif item == "TRUCOS":
                self.menu, self.cursor = "cheats", 0
                self.audio.play("select")
            elif item == "Desactivar todos":
                self.cheats = dict(CHEAT_DEFAULT)
                self.rufo.bighead = False
                self.save_opts()
                self.audio.play("select")
            elif item == "RÉCORDS":
                self.menu = "records"
                self.audio.play("select")
            elif item == "SALIR":
                self.running = False
            elif item == "Volver":
                self.menu, self.cursor = "main", MENU_MAIN.index("TRUCOS" if self.menu == "cheats" else "OPCIONES")
                self.audio.play("select")
            else:
                self.change_option(item, 1)
        elif "pause" in acts:
            if self.menu in ("options", "cheats"):
                self.menu, self.cursor = "main", MENU_MAIN.index("TRUCOS" if self.menu == "cheats" else "OPCIONES")
            else:
                self.running = False

    def name_input(self, e: pygame.event.Event, acts: list[str]) -> None:
        ch = getattr(e, "unicode", "") if e.type == pygame.KEYDOWN else ""
        if ch and ch.isascii() and ch.isalnum():
            self.name[self.name_i] = ch.upper()
            self.name_i = min(2, self.name_i + 1)
            self.audio.play("select", 0.5)
        elif e.type == pygame.KEYDOWN and e.key == pygame.K_BACKSPACE:
            self.name_i = max(0, self.name_i - 1)
        elif e.type == pygame.KEYDOWN and e.key == pygame.K_RETURN or "confirm" in acts:
            self.commit_name()
        else:
            letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            for a, d in (("up", 1), ("down", -1)):
                if a in acts:
                    cur = letters.find(self.name[self.name_i])
                    self.name[self.name_i] = letters[(cur + d) % len(letters)]
            if "left" in acts:
                self.name_i = max(0, self.name_i - 1)
            if "right" in acts:
                self.name_i = min(2, self.name_i + 1)

    # ── tutorial contextual ────────────────────────────────────────────
    def show_tip(self, key: str, text: str) -> None:
        if key not in self.tips_seen:
            self.tips_seen.add(key)
            self.tip = (text, 4.5)

    def tutorial(self) -> None:
        t = self.tomato
        if self.demo or not self.opts["tutorial"] or self.level != 1 or t is None or self.sub != "fight":
            return
        if self.tip is not None and self.tip[1] > 1.2:
            return  # deja leer el consejo actual
        if self.sub_t > 1.0:
            self.show_tip("hit", "Acércate y golpea:  J jab  ·  K gancho  ·  Abajo+J jab bajo")
        if t.state == "tele" and t.attack == "roll":
            self.show_tip("roll", "¡Va a rodar! Shift lo atraviesa con la esquiva (o salta encima)")
        elif t.state == "tele" and t.attack == "bounce":
            self.show_tip("bounce", "¡Va a botar! Sal de la sombra antes de que caiga")
        elif t.state == "stun":
            self.show_tip("stun", "¡Aturdido! Castígalo ahora: puntos ×2 y combo doble")
        elif self.sub_t > 16 and self.stats["crits"] == 0:
            self.show_tip("weak", "Golpea el punto que brilla: crítico ×2 (luego cambia de sitio)")
        elif self.sub_t > 26:
            self.show_tip("climb", "Doble salto + golpe en lo alto = rebote. Así se trepa")
        elif self.sub_t > 34:
            self.show_tip("charge", "Mantén J para cargar un golpe de hasta 6 de daño")

    def diff(self) -> dict[str, float]:
        return DIFFICULTY[self.diff_name]

    def show_banner(self, title: str, sub: str, dur: float) -> None:
        self.banner = (title, sub, dur, dur)

    # ── entrada ────────────────────────────────────────────────────────
    def press(self, action: str) -> None:
        self.buf[action] = self.t

    def peek(self, action: str) -> bool:
        ts = self.buf.get(action)
        return ts is not None and self.t - ts <= BUFFER

    def consume(self, action: str) -> bool:
        if self.peek(action):
            del self.buf[action]
            return True
        return False

    def handle(self, e: pygame.event.Event) -> None:
        if e.type == pygame.QUIT:
            self.running = False
            return
        if e.type == pygame.WINDOWFOCUSLOST and self.state == "play" and not self.demo:
            self.paused = True
            self.inp.clear()
            return
        acts = self.inp.event(e)
        if self.state == "over" and self.entering:
            if e.type in (pygame.KEYDOWN, pygame.JOYBUTTONDOWN, pygame.JOYHATMOTION, pygame.JOYAXISMOTION) and self.over_t > 0.6:
                self.name_input(e, acts)
            return
        if self.demo and self.state == "play":
            if e.type in (pygame.KEYDOWN, pygame.JOYBUTTONDOWN):
                self.to_title()
            return
        if "pad_lost" in acts and self.state == "play":
            self.paused = True
        for a in acts:
            if a == "fullscreen":
                self.change_option("Pantalla completa", 1)
            elif a == "bloom":
                self.change_option("Bloom", 1)
            elif a == "mute":
                self.audio.toggle_mute()
            elif a == "debug":
                self.debug = not self.debug
        if self.state == "title":
            if acts:
                self.idle_t = 0.0
                self.menu_input(acts)
        elif self.state == "play":
            if "pause" in acts:
                self.paused = not self.paused
                self.audio.play("select")
                return
            if self.paused:
                if e.type == pygame.KEYDOWN and e.key == pygame.K_q:
                    self.to_title()
                elif "confirm" in acts:
                    self.paused = False
                return
            for a in acts:
                if a in ("jump", "jab", "hook", "dash"):
                    self.press(a)
        elif self.state == "over" and self.over_t > 0.8:
            if "confirm" in acts:
                self.new_game()
            elif "pause" in acts:
                self.to_title()

    # ── game feel ──────────────────────────────────────────────────────
    def shake(self, amount: float) -> None:
        self.trauma = min(1.0, self.trauma + amount)

    def slowmo(self, k: float, dur: float) -> None:
        self.slow_k = k
        self.slow_t = max(self.slow_t, dur)

    # ── bucle ──────────────────────────────────────────────────────────
    def update(self, dt: float) -> None:
        dt = min(dt, 0.05)
        self.real_t += dt
        self.trauma = max(0.0, self.trauma - dt * 1.6)
        self.zoom_t = max(0.0, self.zoom_t - dt)
        self.ab_t = max(0.0, self.ab_t - dt)
        self.flash = max(0.0, self.flash - dt * 2.5)
        self.red = max(0.0, self.red - dt * 2)
        if self.tip:
            text, life = self.tip
            self.tip = (text, life - dt) if life - dt > 0 else None
        if self.state == "play":
            self.shown_score = approach(self.shown_score, self.score, max(60.0, (self.score - self.shown_score) * 6) * dt)
        if self.combo_pop:
            word, life = self.combo_pop
            self.combo_pop = (word, life - dt) if life - dt > 0 else None
        if self.banner:
            title, sub, life, mx = self.banner
            life -= dt
            self.banner = (title, sub, life, mx) if life > 0 else None
        if self.state == "title":
            self.title_update(dt)
            return
        if self.state == "over":
            self.over_t += dt
            self.scene.step(dt)
            self.fx.step(dt)
            return
        if self.paused:
            return
        if self.demo and self.bot is not None:
            held, presses = self.bot.act(self)
            self.inp.virtual = held
            for a in presses:
                self.press(a)
        if self.hitstop > 0:
            self.hitstop -= dt
            return
        k = 1.0
        if self.slow_t > 0:
            self.slow_t -= dt
            k = self.slow_k
        self.acc += dt * k * self.cheat("speed") / 100
        while self.acc >= DT:
            self.acc -= DT
            self.step(DT)
            if self.state != "play" or self.hitstop > 0:
                self.acc = 0.0
                break
        self.alpha = clamp(self.acc / DT, 0, 1)

    def title_update(self, dt: float) -> None:
        self.title_t += dt
        self.idle_t += dt
        if self.idle_t > DEMO_IDLE and self.menu == "main":
            self.start_demo()
            return
        self.acc += dt
        while self.acc >= DT:
            self.acc -= DT
            self.t += DT
            # Rufo calienta: sombra de boxeo delante del tomate dormido
            self.demo_t -= DT
            r = self.rufo
            if self.demo_t <= 0 and r.state == "normal":
                self.demo_t = random.uniform(0.35, 0.9)
                r.facing = 1
                r.start_attack(self, random.choice(["jab", "jab", "hook", "upper"]))
            r.step(self, DT)
            r.x = approach(r.x, 590, 200 * DT)
            self.tomato.step(self, DT)
            self.scene.step(DT)
            self.fx.step(DT)
            if random.random() < 0.004:
                self.fx.text(self.tomato.x + 120, self.tomato.y - 200, "z", (220, 220, 255), 40, 1.8, -50)
        self.alpha = clamp(self.acc / DT, 0, 1)

    def step(self, dt: float) -> None:
        self.t += dt
        r, t = self.rufo, self.tomato
        r.prev = (r.x, r.y)
        if t is not None:
            t.prev = (t.x, t.y)
        self.sub_t += dt
        self.tutorial()
        # Reloj (congelado mientras entra un tomate o revienta)
        if self.sub == "fight" and t is not None and t.state != "intro" and not self.cheat("freeze"):
            before = self.time_left
            self.time_left -= dt
            if self.time_left < 10 and math.ceil(self.time_left) != math.ceil(before) and self.time_left > 0:
                self.audio.play("tick")
            if self.time_left <= 0:
                self.time_left = 0.0
                self.sub, self.sub_t = "timeup", 0.0
                self.show_banner("¡TIEMPO!", "", 1.8)
                self.audio.play("slam", 0.6)
        if self.sub == "fight" and self.combo and self.t - self.last_hit > COMBO_WINDOW:
            self.combo = 0
        # Rufo: lleva el movimiento del tomate si está encima
        if r.on_tomato and t is not None:
            r.x += t.vx * dt
        self.dash_overlap = bool(
            t is not None and r.state == "dash" and t.state == "atk" and t.attack == "roll" and rect_ellipse(r.hurtbox(), t.x, t.y, *t.radii())
        )
        r.step(self, dt)
        if t is not None and self.sub in ("fight", "timeup", "ko"):
            t.step(self, dt)
            self.resolve(r, t, dt)
            if self.sub == "fight":
                self.combat(r, t)
                # Encima del tomate (cabalgando la rodada) no hay daño: saltar encima es esquivar
                above = r.on_tomato or r.y < t.y - t.radii()[1] * 0.7
                if t.body_dangerous() and not above and rect_ellipse(r.hurtbox(), t.x, t.y, *t.radii()):
                    self.hazard_touch(t.hazard_id(), t.x)
        self.step_jets(dt)
        self.step_seeds(dt)
        self.step_cherries(dt)
        self.step_puddles(dt)
        self.scene.step(dt)
        self.fx.step(dt)
        # Sub-estados
        if self.sub == "burst" and self.sub_t > 2.2:
            self.level += 1
            self.tomato = Tomato(self.level, x=clamp(W - r.x, 420, 860), diff=self.diff())
            self.dress(self.tomato)
            self.tart.warm(self.tomato)
            self.sub, self.sub_t = "fight", 0.0
            if self.level == 2 and self.opts["tutorial"] and not self.demo:
                self.opts["tutorial"] = False  # tutorial superado
                self.save_opts()
            self.show_banner(f"NIVEL {self.level}", self.level_hint(), 1.6)
            self.audio.play("level")
        elif self.sub == "ko" and self.sub_t > 1.8:
            self.game_over()
        elif self.sub == "timeup" and self.sub_t > 1.8:
            self.game_over()

    def level_hint(self) -> str:
        kind = tomato_kind(self.level)
        if kind == "verde":
            return "Blindado: los jabs rebotan · rompe la coraza con ganchos, cargados y críticos"
        if kind == "podrida":
            return "Podrido: deja charcos que resbalan · cuidado al frenar"
        if self.level == 7:
            return "Nuevo ataque: enjambre de cherrys · revientan de un golpe"
        if self.level == 3:
            return "Nuevo ataque: chorro de jugo · agáchate o salta"
        if self.level == 5:
            return "Nuevo ataque: lluvia de pepitas"
        return f"Más grande y con peor carácter · vida {30 + 10 * (self.level - 1)}"

    # ── colisión Rufo ↔ tomate ─────────────────────────────────────────
    def resolve(self, r: Rufo, t: Tomato, dt: float) -> None:
        if t.offscreen() or t.state == "intro" or r.state == "dead":
            return
        if self.dash_overlap:
            return  # la esquiva atraviesa al tomate que rueda
        rx, ry = t.radii()
        hh = r.height() / 2
        erx, ery = rx + RUFO_W / 2, ry + hh
        px, py = r.x, r.y - hh
        dx, dy = (px - t.x) / erx, (py - t.y) / ery
        d2 = dx * dx + dy * dy
        if d2 >= 1.0:
            return
        ang = math.atan2(dy, dx)
        if math.sin(ang) < -0.55 and r.vy < t.vy - 60:
            return  # despegando desde la corona
        if math.sin(ang) < -0.55:
            # De pie sobre la corona
            k = clamp((px - t.x) / erx, -1, 1)
            top = t.y - ery * math.sqrt(max(0.0, 1 - k * k))
            was = r.on_ground
            r.y = top + hh
            if r.vy > 0:
                r.land(self, r.vy)
            r.vy = 0.0
            r.on_ground = r.on_tomato = True
            r._ground_flags(was, dt)
            return
        if math.sin(ang) > 0.45:
            # Debajo (el tomate le ha caído encima): fuera por el lado
            side = 1 if px >= t.x else -1
            k = clamp((py - t.y) / ery, -1, 1)
            r.x = t.x + side * (erx * math.sqrt(max(0.0, 1 - k * k)) + 2)
        else:
            r.x = t.x + math.cos(ang) * erx
            r.y = t.y + math.sin(ang) * ery + hh
            if r.y > FLOOR:
                r.y = float(FLOOR)
            nx = math.cos(ang)
            if r.vx * nx < 0:
                r.vx = 0.0
        # Atrapado entre pared y tomate: sale despedido hacia arriba
        if r.x - RUFO_W / 2 < WALL_L or r.x + RUFO_W / 2 > WALL_R:
            r.x = clamp(r.x, WALL_L + RUFO_W / 2, WALL_R - RUFO_W / 2)
            if rect_ellipse(r.hurtbox().inflate(-6, -6), t.x, t.y, rx, ry):
                r.vy = -900.0
                r.y = min(r.y, t.y)
                r.on_ground = False

    def shrug_rufo(self, t: Tomato) -> None:
        r = self.rufo
        side = 1 if r.x >= t.x else -1
        r.vy = -820.0
        r.vx = side * 420.0
        r.on_ground = r.on_tomato = False
        r.air_jumps = 1
        if r.state in ("charge", "attack"):
            r.state = "normal"
        self.fx.text(r.x, r.y - 90, "¡FUERA!", (255, 240, 200), 26)

    # ── combate ─────────────────────────────────────────────────────────
    def combat(self, r: Rufo, t: Tomato) -> None:
        box = r.hitbox()
        if box is None or t.offscreen() or t.state in ("intro", "dead"):
            return
        rx, ry = t.radii()
        if not rect_ellipse(box, t.x, t.y, rx, ry):
            return
        r.atk_hit = True
        a = ATTACKS[r.atk]
        bx, by = box.center
        ang = math.atan2((by - t.y) / ry, (bx - t.x) / rx)
        hx, hy = t.x + math.cos(ang) * rx, t.y + math.sin(ang) * ry
        wx, wy = t.weak_pos()
        reach = 150 if self.cheat("bigweak") else 52
        crit = box.inflate(reach, reach).collidepoint(wx, wy)
        stunned = t.state == "stun"
        dmg = max(1, round(r.atk_dmg * (2 if crit else 1) * self.diff()["dmg"] * (3 if self.cheat("titan") else 1)))
        dmg, event = t.take_hit(ang, dmg, a["knock"], crit, heavy=r.atk != "jab")
        # Puntuación y combo
        base = 15 * r.atk_dmg if r.atk == "charge" else a["pts"]
        if event == "clonk":
            base = max(2, base // 4)
        pts = self.add_hit(base * (2 if crit else 1) * (2 if stunned else 1), stunned)
        # Rebote: golpe aéreo sobre la mitad alta → encadenar sin tocar el suelo
        if not r.on_ground and math.sin(ang) < -0.2:
            r.vy = -BOUNCE_V
            r.air_jumps = 1
            r.air_dash = True
            r.jumping = False
            if r.atk == "hammer":
                r.atk_t = sum(ATTACKS["hammer"]["f"][:2]) * FRAME
        # Sensaciones
        stop = 0.06 if crit else a["stop"]
        if r.atk == "charge":
            stop = 0.05 + 0.01 * r.atk_dmg
        self.hitstop = stop
        self.shake(a["shake"] + (0.25 if crit else 0))
        out = ang
        self.rumble(0.25 + 0.1 * dmg, 0.35, 90 + 20 * dmg)
        if event == "clonk":
            self.fx.sparks(hx, hy, 14, 650, (220, 235, 255), 0.3)
            self.fx.ring(hx, hy, 40, (200, 220, 255), 0.2, 4)
            self.audio.play("clonk")
            self.fx.text(hx, hy - 60, "¡CLONK!", (200, 230, 255), 34, 0.8)
            if dmg:
                self.fx.squirt(hx, hy, out, 6, 380, color=t.juice())
        else:
            self.fx.squirt(hx, hy, out, 10 + dmg * 5, 420 + dmg * 120, color=t.juice())
            self.fx.sparks(hx, hy, 6 + dmg * 2, 500)
            self.fx.ring(hx, hy, 30 + dmg * 12, (255, 200, 150), 0.22, 4)
            if dmg >= 3:
                self.fx.pulp(hx, hy, dmg, 500)
            self.audio.play(a["snd"])
        if event == "ripe":
            self.audio.play("ripe")
            self.flash = max(self.flash, 0.5)
            self.shake(0.5)
            self.fx.ring(t.x, t.y, t.r * 1.3, (120, 255, 120), 0.5, 8)
            self.fx.sparks(t.x, t.y - t.radii()[1] * 0.5, 40, 900, (180, 255, 140), 0.45)
            self.fx.text(t.x, t.y - t.radii()[1] - 20, "¡CORAZA ROTA! ¡MADURO!", (170, 255, 140), 48, 1.6, -40)
        if t.kind == "podrida" and dmg >= 2 and random.random() < 0.6:
            self.add_puddle(hx + random.uniform(-40, 40), 34)
        col = (255, 255, 255) if not stunned else (255, 230, 120)
        self.fx.text(hx, hy - 30, f"+{pts}", col, 28 if pts < 100 else 36)
        if crit:
            self.stats["crits"] += 1
            self.audio.play("crit")
            self.zoom_t = 0.28
            self.zoom_at = (r.x, r.y - 50)
            self.ab_t = 0.2
            self.fx.text(hx, hy - 75, "¡JUGOSO!", (255, 200, 60), 46, 1.1)
            self.fx.ring(wx, wy, 120, (255, 160, 60), 0.35, 6)
            self.fx.squirt(hx, hy, out, 30, 900, 0.5)
        if t.hp <= 0:
            self.burst(t)

    def add_hit(self, base: float, stunned: bool = False) -> int:
        """Suma un golpe al combo y devuelve los puntos ganados."""
        before = self.combo
        step = 2 if stunned else 1
        self.combo = self.combo + step if self.t - self.last_hit <= COMBO_WINDOW else step
        self.last_hit = self.t
        self.stats["max_combo"] = max(self.stats["max_combo"], self.combo)
        mult = min(5.0, 1 + 0.1 * (self.combo - 1))
        pts = int(base * mult * self.diff()["score"])
        self.score += pts
        for mark, word in ((10, "¡BIEN!"), (20, "¡BRUTAL!"), (30, "¡SALVAJE!"), (41, "¡×5 MÁXIMO!")):
            if before < mark <= self.combo:
                self.combo_pop = (word, 1.2)
                self.audio.play("perfect", 0.6)
        return pts

    def rumble(self, low: float, high: float, ms: int) -> None:
        pad = self.inp.pad
        if pad is not None and self.opts.get("rumble", True):
            try:
                pad.rumble(low, high, ms)
            except (pygame.error, AttributeError):
                pass

    # ── charcos (tomate podrido) ───────────────────────────────────────
    def add_puddle(self, x: float, hw: float) -> None:
        x = clamp(x, WALL_L + hw, WALL_R - hw)
        for p in self.puddles:
            if abs(p[0] - x) < p[1] + hw * 0.5:
                lo, hi = min(p[0] - p[1], x - hw), max(p[0] + p[1], x + hw)
                p[0], p[1] = (lo + hi) / 2, min(170.0, (hi - lo) / 2)
                p[2] = p[3] = 9.0
                return
        if len(self.puddles) < 10:
            self.puddles.append([x, hw, 9.0, 9.0])

    def step_puddles(self, dt: float) -> None:
        for p in self.puddles:
            p[2] -= dt
        self.puddles = [p for p in self.puddles if p[2] > 0]
        r = self.rufo
        slip = r.on_ground and not r.on_tomato and any(abs(r.x - p[0]) < p[1] and p[2] > 0.5 for p in self.puddles)
        if slip and not self.slipping and abs(r.vx) > 120:
            self.fx.text(r.x, r.y - 100, "¡RESBALA!", (190, 210, 120), 24, 0.7)
        self.slipping = slip

    # ── cherrys ────────────────────────────────────────────────────────
    def spawn_cherries(self, t: Tomato) -> None:
        r = self.rufo
        rx, ry = t.radii()
        n = 2 + t.level // 4
        for i in range(n):
            tx = clamp(r.x + (i - (n - 1) / 2) * 150 + random.uniform(-40, 40), WALL_L + 30, WALL_R - 30)
            x0, y0 = t.x + random.uniform(-0.3, 0.3) * rx, t.y - ry * 0.85
            vy = -random.uniform(650, 850)
            gr = 2000.0
            tt = (-vy + math.sqrt(vy * vy + 2 * gr * (FLOOR - CHERRY_R - y0))) / gr
            self.cherries.append({"x": x0, "y": y0, "vx": (tx - x0) / tt, "vy": vy, "t": 0.0, "hop": random.uniform(0.35, 0.7), "id": f"{t.hazard_id()}:c{i}", "sq": Spring(260, 10), "face": -1})

    def pop_cherry(self, c: dict, scored: bool) -> None:
        c["dead"] = True
        self.fx.squirt(c["x"], c["y"], -math.pi / 2, 18, 420, 1.4)
        self.fx.seeds(c["x"], c["y"], 5, 300)
        self.fx.ring(c["x"], c["y"], 46, (255, 150, 120), 0.25, 4)
        self.scene.stain(c["x"], FLOOR + random.uniform(6, 40), 14)
        self.audio.play("pop")
        if scored:
            pts = self.add_hit(30)
            self.fx.text(c["x"], c["y"] - 40, f"+{pts}", WHITE, 26)

    def step_cherries(self, dt: float) -> None:
        r = self.rufo
        box = r.active_box()
        hb = r.hurtbox()
        for c in self.cherries:
            c["t"] += dt
            c["sq"].step(dt)
            c["vy"] = min(c["vy"] + 2000 * dt, 1400)
            c["x"] += c["vx"] * dt
            c["y"] += c["vy"] * dt
            c["face"] = 1 if r.x > c["x"] else -1
            if c["y"] >= FLOOR - CHERRY_R:
                c["y"] = FLOOR - CHERRY_R
                if c["vy"] > 200:
                    c["sq"].kick(c["vy"] * 0.004)
                c["vy"] = 0.0
                c["vx"] = approach(c["vx"], 0, 1600 * dt)
                c["hop"] -= dt
                if c["hop"] <= 0 and self.sub == "fight":
                    c["hop"] = random.uniform(0.5, 0.8)
                    c["vx"] = c["face"] * random.uniform(200, 300) * self.diff()["speed"]
                    c["vy"] = -random.uniform(520, 680)
                    c["sq"].kick(-3)
            if c["x"] < WALL_L + CHERRY_R or c["x"] > WALL_R - CHERRY_R:
                c["x"] = clamp(c["x"], WALL_L + CHERRY_R, WALL_R - CHERRY_R)
                c["vx"] = -c["vx"] * 0.6
            near = pygame.Rect(int(c["x"] - CHERRY_R), int(c["y"] - CHERRY_R), CHERRY_R * 2, CHERRY_R * 2)
            if box is not None and box.colliderect(near.inflate(14, 22)) and self.sub == "fight":
                self.pop_cherry(c, True)
                self.hitstop = max(self.hitstop, 0.03)
                if not r.on_ground and c["y"] > r.y - 10:
                    r.vy = -BOUNCE_V * 0.8
                    r.air_jumps = 1
                continue
            if near.inflate(-8, -8).colliderect(hb) and self.sub == "fight":
                self.hazard_touch(c["id"], c["x"])
            if c["t"] > 7.5 or (self.sub != "fight" and c["t"] > 0.3):
                self.pop_cherry(c, False)
        self.cherries = [c for c in self.cherries if not c.get("dead")]

    def hammer_ground(self, r: Rufo) -> None:
        self.shake(0.2)
        self.fx.puff(r.x, r.y, 10)
        self.fx.ring(r.x, r.y + 4, 90, (200, 190, 180), 0.3, 3, flat=0.25)
        r.atk_t = max(r.atk_t, sum(ATTACKS["hammer"]["f"][:2]) * FRAME)

    def hazard_touch(self, hid: str, from_x: float, juice: bool = False) -> None:
        r = self.rufo
        if r.state == "dead":
            return
        if r.state == "dash":
            if hid not in self.dodged:
                self.dodged.add(hid)
                if self.t - r.dash_start <= PERFECT_WINDOW + 1e-6:
                    self.perfect_dodge()
            return
        if r.inv > 0 or hid in self.hit_by or hid in self.dodged:
            return
        self.hit_by.add(hid)
        self.hurt_rufo(from_x, juice)

    def perfect_dodge(self) -> None:
        r = self.rufo
        self.score += 100
        self.stats["perfect"] += 1
        self.audio.play("perfect")
        self.slowmo(0.3, 0.35)
        self.fx.text(r.x, r.y - 110, "¡ESQUIVA PERFECTA!", (120, 230, 255), 34, 1.2)
        self.fx.text(r.x, r.y - 75, "+100", WHITE, 26)
        self.fx.ring(r.x, r.y - 35, 90, (120, 200, 255), 0.35, 4)
        r.inv = max(r.inv, 0.3)

    def hurt_rufo(self, from_x: float, juice: bool = False) -> None:
        r = self.rufo
        if not self.cheat("infinite"):
            self.hearts -= 1
        self.combo = 0
        r.inv = INV_HURT
        r.state = "hurt"
        r.hurt_t = 0.35
        r.j_armed = False
        side = 1 if r.x >= from_x else -1
        r.vx = side * 540.0
        r.vy = -560.0
        r.on_ground = r.on_tomato = False
        if juice:
            r.juice = 2.5
        self.audio.play("hurt")
        self.rumble(0.9, 0.9, 300)
        r.flash = 1.0
        self.shake(0.55)
        self.red = 0.6
        self.hitstop = 0.07
        self.fx.squirt(r.x, r.y - 40, -math.pi / 2, 12, 400, 1.2)
        self.fx.sparks(r.x, r.y - 40, 8, 400, (255, 255, 255))
        if self.hearts <= 0:
            self.hearts = 0
            r.state = "dead"
            r.vy = -700.0
            self.sub, self.sub_t = "ko", 0.0
            self.slowmo(0.35, 1.0)
            self.show_banner("¡K.O.!", "El tomate gana esta vez", 1.8)

    def burst(self, t: Tomato) -> None:
        """¡SPLASH! El tomate revienta."""
        r = self.rufo
        t.state = "dead"
        self.sub, self.sub_t = "burst", 0.0
        rx, ry = t.radii()
        jc = t.juice()
        hi = (255, 70, 50) if jc == JUICE else scale_c(jc, 1.5)
        for _ in range(300):
            a = random.uniform(-math.pi, math.pi)
            s = random.uniform(200, 1500) * (1.2 if math.sin(a) < 0 else 0.7)
            d = random.uniform(0, 0.8)
            self.fx.drop(t.x + math.cos(a) * rx * d, t.y + math.sin(a) * ry * d, math.cos(a) * s, math.sin(a) * s - 200, random.uniform(2, 7), mix(scale_c(jc, 0.75), hi, random.random()))
        self.fx.pulp(t.x, t.y, 36, 1100)
        self.fx.seeds(t.x, t.y, 40, 900)
        self.fx.sparks(t.x, t.y, 50, 1100, (255, 200, 140), 0.5)
        for i in range(3):
            self.fx.ring(t.x, t.y, rx * (1.4 + i * 0.7), (255, 150 - i * 40, 100), 0.5 + i * 0.2, 10 - i * 3)
        self.fx.ring(t.x, FLOOR + 6, rx * 2.4, (255, 120, 90), 0.6, 6, flat=0.18)
        for _ in range(26):
            self.scene.stain(random.uniform(t.x - rx * 1.8, t.x + rx * 1.8), FLOOR + random.uniform(4, 76), random.uniform(18, 34))
        for side in (WALL_L, WALL_R):
            if abs(t.x - side) < rx * 2.2:
                self.fx.wall_splat(side, t.y)
        self.slowmo(0.25, 0.7)
        self.flash = 1.0
        self.shake(1.0)
        self.rumble(1.0, 1.0, 600)
        for c in self.cherries:
            c["t"] = 99.0
        self.scene.kick(1.6)
        self.audio.play("burst")
        bonus = 500 * self.level
        self.score += bonus
        self.time_left += 10
        self.hearts = min(MAX_HEARTS, self.hearts + 1)
        self.stats["tomatoes"] += 1
        r.juice = 3.5
        for _ in range(random.randint(2, 4)):
            r.stains.append((random.uniform(-0.8, 0.8), random.uniform(0.1, 0.9), random.uniform(1.6, 3.2)))
        r.stains = r.stains[-14:]
        self.tomato = None
        self.jets.clear()
        self.fx.text(t.x, t.y - 40, "¡SPLASH!", (255, 90, 70), 96, 1.8, -40)
        self.fx.text(t.x, t.y + 40, f"+{bonus}", (255, 230, 140), 44, 1.8, -50)
        self.fx.text(t.x - 120, t.y + 100, "+10 s", (160, 230, 255), 36, 1.8, -50)
        self.fx.text(t.x + 120, t.y + 100, "+1 VIDA", (255, 140, 150), 36, 1.8, -50)

    def slam(self, t: Tomato, power: float) -> None:
        rx, _ = t.radii()
        self.shake(0.65 * power)
        self.scene.kick(power)
        self.audio.play("slam", power)
        self.fx.puff(t.x - rx * 0.7, FLOOR, int(10 * power))
        self.fx.puff(t.x + rx * 0.7, FLOOR, int(10 * power))
        self.fx.ring(t.x, FLOOR + 6, rx * 2.2, (230, 200, 170), 0.5, 6, flat=0.16)
        self.rumble(0.8 * power, 0.3, 250)
        if t.kind == "podrida":
            self.add_puddle(t.x - rx * 0.9, 60)
            self.add_puddle(t.x + rx * 0.9, 60)
        r = self.rufo
        if r.on_ground and not r.on_tomato and abs(r.x - t.x) < rx + 260 and r.state not in ("dead", "dash"):
            r.vy = -260.0 * power  # el suelo da un respingo
            r.on_ground = False

    def slam_hazard(self, t: Tomato) -> None:
        r = self.rufo
        rx, ry = t.radii()
        if abs(r.x - t.x) < rx * 0.96 + RUFO_W / 2 and r.y > t.y - ry:
            self.hazard_touch(t.hazard_id(), t.x)

    # ── ataques a distancia ────────────────────────────────────────────
    def spawn_jet(self, x0: float, y: float, d: int, hid: str) -> None:
        self.jets.append({"x0": x0, "y": y, "d": d, "front": x0, "tail": x0, "t": 0.0, "hid": hid})

    def step_jets(self, dt: float) -> None:
        keep = []
        r = self.rufo
        for j in self.jets:
            j["t"] += dt
            limit = WALL_R if j["d"] > 0 else WALL_L
            j["front"] = approach(j["front"], limit, 2400 * dt)
            if j["t"] > 0.3:
                j["tail"] = approach(j["tail"], limit, 3200 * dt)
            if random.random() < 0.8:
                fx = j["front"]
                self.fx.drop(fx, j["y"] + random.uniform(-6, 6), j["d"] * random.uniform(100, 400), random.uniform(-200, 50), random.uniform(2, 4))
            x_lo, x_hi = sorted((j["tail"], j["front"]))
            box = pygame.Rect(int(x_lo), int(j["y"] - 10), int(x_hi - x_lo) + 1, 20)
            if self.sub == "fight" and box.colliderect(r.hurtbox()):
                self.hazard_touch(j["hid"], j["x0"] - j["d"] * 50, juice=True)
            if abs(j["front"] - limit) < 1 and random.random() < 0.5:
                self.scene.stain(limit, j["y"] + random.uniform(-14, 14), random.uniform(8, 16), wall=True)
            if abs(j["tail"] - limit) > 2:
                keep.append(j)
        self.jets = keep

    def spawn_seeds(self, t: Tomato) -> None:
        # Pepitas repartidas por la arena dejando huecos por los que pasar
        slots = list(range(WALL_L + 40, WALL_R - 20, 66))
        for _ in range(3):
            gap = random.randrange(len(slots))
            del slots[gap : gap + 2]
        rx, ry = t.radii()
        for tx in slots:
            x0, y0 = t.x + random.uniform(-rx * 0.4, rx * 0.4), t.y - ry * 0.7
            vy = -random.uniform(780, 960)
            g = 2000.0
            # tiempo hasta caer a la altura de la cabeza de Rufo
            yh = FLOOR - 40
            tt = (-vy + math.sqrt(max(1.0, vy * vy + 2 * g * (yh - y0)))) / g
            vx = (tx - x0) / tt
            self.seeds.append([x0, y0, vx, vy, 0.0, t.hazard_id(), tx])

    def step_seeds(self, dt: float) -> None:
        r = self.rufo
        hb = r.hurtbox()
        keep = []
        for s in self.seeds:
            s[3] += 2000 * dt
            s[0] += s[2] * dt
            s[1] += s[3] * dt
            s[4] += dt
            if s[1] >= FLOOR - 4:
                self.fx.seeds(s[0], FLOOR - 4, 1, 120)
                self.fx.drop(s[0], FLOOR - 2, 0, 50, 2, (230, 200, 130))
                continue
            if hb.collidepoint(s[0], s[1]) and r.state not in ("dash", "dead") and self.sub == "fight":
                r.slow = 1.0
                self.audio.play("seed_hit")
                self.fx.text(r.x, r.y - 95, "¡PEGAJOSO!", (240, 225, 150), 24, 0.7)
                continue
            keep.append(s)
        self.seeds = keep

    # ═══════════════════════════════════════════════════════════════════
    # DIBUJO
    # ═══════════════════════════════════════════════════════════════════
    def draw(self) -> None:
        """Dibuja interpolando entre los dos últimos pasos de física: movimiento
        suave a cualquier tasa de refresco sin tocar la simulación."""
        a = self.alpha if not self.paused and self.hitstop <= 0 else 1.0
        saved = []
        for obj in (self.rufo, self.tomato):
            if obj is not None and hasattr(obj, "prev") and math.hypot(obj.x - obj.prev[0], obj.y - obj.prev[1]) < 120:
                saved.append((obj, obj.x, obj.y))
                obj.x, obj.y = lerp(obj.prev[0], obj.x, a), lerp(obj.prev[1], obj.y, a)
        try:
            self._draw()
        finally:
            for obj, x, y in saved:
                obj.x, obj.y = x, y

    def _draw(self) -> None:
        world = self.world
        add = world  # lo aditivo se mezcla directamente sobre el mundo
        self.scene.draw_back(world)
        t, r = self.tomato, self.rufo
        tomato_img = rufo_img = None
        if t is not None and not t.offscreen():
            tomato_img = self.tart.render(t)
        rufo_img = self.rart.render(r)
        r.last_sprite = rufo_img
        # Reflejos en el suelo pulido
        self.refl.fill((0, 0, 0, 0))
        if tomato_img is not None:
            img, ox, oy = tomato_img
            fl = pygame.transform.flip(img, False, True)
            self.refl.blit(fl, (ox, FLOOR - oy - img.get_height()))
        fr = pygame.transform.flip(rufo_img, False, True)
        self.refl.blit(fr, (r.x - ANCHOR[0], (FLOOR - r.y) - (CANVAS[1] - ANCHOR[1])))
        self.refl.blit(self.scene.refl_fade, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        world.blit(self.refl, (0, FLOOR))
        self.draw_puddles(world)
        self.scene.draw_lamps(add)
        # Sombras de contacto
        if t is not None:
            self.draw_tomato_shadow(world, t)
        if not r.on_tomato:
            h = max(0.0, FLOOR - r.y)
            w = max(10, int(46 * (1 - min(0.7, h / 400))))
            sh = pygame.transform.scale(soft_blob(32, (0, 0, 0), 150, 1.2), (w, max(4, w // 4)))
            blit_center(world, sh, r.x, FLOOR + 3)
        # Avisos de telegrafiado
        if t is not None and t.state == "tele" and t.attack == "jet":
            self.draw_jet_warning(world, t)
        # Jets y pepitas
        for j in self.jets:
            self.draw_jet(world, j)
        for s in self.seeds:
            # Marca en el suelo: dónde caerá (la lluvia se lee antes de llegar)
            k = clamp(s[4] / 0.9, 0, 1)
            mark = pygame.transform.scale(glow(20, scale_c((150, 130, 60), 0.4 + 0.6 * k), 1.2), (int(18 + 22 * k), int(6 + 6 * k)))
            blit_add(world, mark, s[6], FLOOR + 5)
        for s in self.seeds:
            self.draw_seed(world, s)
        # Tomate
        if tomato_img is not None:
            img, ox, oy = tomato_img
            world.blit(img, (ox, oy))
            if t.state == "stun":
                self.draw_stars(world, t)
            if t.kind == "podrida":
                self.draw_flies(world, t)
        for c in self.cherries:
            self.draw_cherry(world, c)
        # Fantasmas de la esquiva
        if r.state == "dash" and r.ghost_t <= 0:
            r.ghost_t = 0.03
            gimg = rufo_img.copy()
            gimg.fill((90, 190, 255), special_flags=pygame.BLEND_RGB_MULT)
            self.fx.ghosts.append([gimg, r.x - ANCHOR[0], r.y - ANCHOR[1], 0.2])
        for gimg, gx, gy, life in self.fx.ghosts:
            gimg.set_alpha(int(200 * life / 0.2))
            world.blit(gimg, (gx, gy))
        # Estela de los guantes
        self.draw_trail(add, r)
        # Aura de carga
        if r.state == "charge":
            k = clamp((r.j_hold - 0.4) / 0.8, 0, 1)
            blit_add(add, glow(50 + 30 * k, scale_c(GOLD, 0.35 + 0.5 * k), 1.5), r.x, r.y - 40)
        # Rufo
        visible = not (r.inv > 0 and r.state != "dash" and int(r.inv * 16) % 2 == 0)
        if visible:
            world.blit(rufo_img, (r.x - ANCHOR[0], r.y - ANCHOR[1]))
        self.fx.draw(world, add)
        self.scene.draw_dust(add)
        self.fx.draw_texts(world, self.txt)
        if self.debug:
            self.draw_debug(world)
        self.post()

    def draw_tomato_shadow(self, world, t: Tomato) -> None:
        rx, ry = t.radii()
        if t.state == "atk" and t.attack == "bounce" and t.phase in ("rise", "hover", "fall"):
            if t.phase == "rise":
                p = 0.1
            elif t.phase == "hover":
                p = 0.15 + 0.6 * (t.timer / HOVER_T)
            else:
                p = 1.0
            w = int(2 * rx * (0.35 + 0.65 * p))
            sh = pygame.transform.smoothscale(soft_blob(64, (10, 0, 0), int(150 + 105 * p), 0.7), (w, max(6, int(w * 0.14))))
            blit_center(world, sh, t.x, FLOOR + 6)
            pulse = 0.5 + 0.5 * math.sin(self.t * (18 + 20 * p))
            rect = pygame.Rect(0, 0, int(2 * rx * 0.96), max(6, int(2 * rx * 0.96 * 0.14)))
            rect.center = (int(t.x), FLOOR + 6)
            pygame.draw.ellipse(world, scale_c((255, 60, 40), 0.35 + 0.6 * pulse), rect, 2 + int(3 * p))
            ex = self.txt.outlined("!", 60, (255, 80, 60))
            blit_center(world, ex, t.x, FLOOR - 60 - 10 * pulse)
            return
        h = max(0.0, FLOOR - (t.y + ry))
        k = 1 - min(0.8, h / 900)
        w = int(2 * rx * 1.05 * k)
        sh = pygame.transform.smoothscale(soft_blob(64, (0, 0, 0), int(190 * k), 1.0), (max(8, w), max(6, int(w * 0.12))))
        blit_center(world, sh, t.x, FLOOR + 4)

    def draw_jet_warning(self, world, t: Tomato) -> None:
        y = int(t.jet_y())
        x0 = t.x + t.dir * t.rim_dx(y)
        end = WALL_R if t.dir > 0 else WALL_L
        p = t.timer / t.tele("jet")
        if int(p * 10) % 2 == 0:
            n = int(abs(end - x0) / 28)
            for i in range(n):
                xa = x0 + t.dir * i * 28
                pygame.draw.line(world, (200, 40, 40), (xa, y), (xa + t.dir * 14, y), 3)
        label = "¡AGÁCHATE!" if t.jet_high else "¡SALTA!"
        img = self.txt.outlined(label, 26, (255, 200, 170))
        blit_center(world, img, x0 + t.dir * 160, y - 34)

    def draw_jet(self, world, j: dict) -> None:
        y = j["y"]
        xa, xb = sorted((j["tail"], j["front"]))
        if xb - xa < 2:
            return
        wob = 3 * math.sin(self.t * 60)
        pygame.draw.rect(world, (110, 4, 16), (xa, y - 12 - wob, xb - xa, 24 + 2 * wob), border_radius=10)
        pygame.draw.rect(world, (215, 30, 32), (xa, y - 9, xb - xa, 18), border_radius=8)
        pygame.draw.rect(world, (255, 120, 100), (xa, y - 6, xb - xa, 4), border_radius=2)
        for i in range(int(xa), int(xb), 40):
            o = (i * 7 + int(self.t * 900)) % 40
            pygame.draw.circle(world, (250, 220, 150), (i + o, y + 2 * math.sin(i + self.t * 30)), 2)

    def draw_seed(self, world, s) -> None:
        x, y = s[0], s[1]
        blit_center(world, soft_blob(10, (255, 240, 200), 70), x, y)
        pygame.draw.ellipse(world, (110, 100, 60), (x - 8, y - 5, 16, 10))
        pygame.draw.ellipse(world, (245, 228, 160), (x - 7, y - 4, 14, 8))
        pygame.draw.circle(world, WHITE, (x - 2, y - 2), 1.5)

    def draw_puddles(self, world) -> None:
        for x, hw, life, mx in self.puddles:
            a = clamp(life / 1.5, 0, 1) * clamp((mx - life) / 0.25, 0, 1)
            w, h = int(hw * 2), max(6, int(hw * 0.34))
            blob = pygame.transform.smoothscale(soft_blob(64, (40, 46, 10), int(220 * a), 0.45), (w, h))
            blit_center(world, blob, x, FLOOR + 10)
            gl = pygame.transform.scale(glow(20, scale_c((90, 100, 50), a), 1.4), (int(w * 0.7), max(3, h // 3)))
            blit_add(world, gl, x - hw * 0.15, FLOOR + 7)
            k = int(self.t * 3 + x) % 7
            if k < 2:
                pygame.draw.circle(world, scale_c((150, 160, 80), a), (x + math.sin(x + self.t) * hw * 0.5, FLOOR + 9), 2 + k, 1)

    def draw_flies(self, world, t: Tomato) -> None:
        rx, ry = t.radii()
        for i in range(7):
            a = self.t * (2.2 + i * 0.37) + i * 1.9
            fx = t.x + math.cos(a) * (rx * 0.7 + 40 * math.sin(self.t * 1.3 + i))
            fy = t.y - ry * 0.75 + math.sin(a * 1.7) * ry * 0.35
            wing = 2 + int(abs(math.sin(self.t * 60 + i)) * 3)
            pygame.draw.ellipse(world, (170, 180, 190), (fx - wing, fy - 4, wing * 2, 3))
            pygame.draw.circle(world, (15, 15, 15), (fx, fy), 2.3)
        for i in range(3):
            x0 = t.x + (i - 1) * rx * 0.45
            pts = [(x0 + math.sin(self.t * 3 + k * 0.6 + i) * 10, t.y - ry - 10 - k * 9 - (self.t * 25 + i * 20) % 30) for k in range(6)]
            pygame.draw.lines(world, (90, 112, 52), False, pts, 2)

    def draw_cherry(self, world, c: dict) -> None:
        k = clamp(c["sq"].x, -0.4, 0.5)
        base = self.tart.cherry()
        w, h = int(base.get_width() * (1 + k * 0.6)), int(base.get_height() * (1 - k))
        img = pygame.transform.smoothscale(base, (max(4, w), max(4, h)))
        x, y = c["x"], c["y"] + base.get_height() / 2 - h / 2
        sh = pygame.transform.scale(soft_blob(16, (0, 0, 0), 140, 1.2), (int(28 * (1 - min(0.6, (FLOOR - c["y"]) / 300))), 7))
        blit_center(world, sh, x, FLOOR + 3)
        if c["t"] > 6.5 and int(c["t"] * 12) % 2:
            img = img.copy()
            img.fill((90, 90, 90), special_flags=pygame.BLEND_RGB_ADD)
        blit_center(world, img, x, y)
        # Ojitos enfadados mirando a Rufo
        f = c["face"]
        for ex in (2, 9):
            e = (x + f * ex - 5 * f + 1, y - 3)
            pygame.draw.circle(world, WHITE, e, 4)
            pygame.draw.circle(world, OUT, (e[0] + f * 1.5, e[1] + 0.5), 2)
        pygame.draw.line(world, OUT, (x + f * -3, y - 9), (x + f * 4, y - 6), 2)
        pygame.draw.line(world, OUT, (x + f * 6, y - 6), (x + f * 12, y - 9), 2)
        pygame.draw.line(world, (60, 130, 40), (x, y - h / 2 + 2), (x + 3, y - h / 2 - 7), 3)
        pygame.draw.circle(world, (80, 160, 50), (x - 2, y - h / 2 + 3), 4)

    def draw_stars(self, world, t: Tomato) -> None:
        rx, ry = t.radii()
        for i in range(4):
            a = self.t * 4 + i * math.pi / 2
            x = t.x + math.cos(a) * rx * 0.5
            y = t.y - ry - 26 + math.sin(a) * 12
            pts = []
            for k in range(10):
                rr = 10 if k % 2 == 0 else 4.5
                aa = k * math.pi / 5 + self.t * 3
                pts.append((x + math.cos(aa) * rr, y + math.sin(aa) * rr))
            pygame.draw.polygon(world, OUT, pts, 3)
            pygame.draw.polygon(world, (255, 230, 90), pts)

    def draw_trail(self, add, r: Rufo) -> None:
        if not r.trail:
            return
        now = r.time
        prev = None
        for x, y, tt in r.trail:
            age = now - tt
            if age > 0.12:
                prev = None
                continue
            f = 1 - age / 0.12
            if prev is not None:
                pygame.draw.line(add, scale_c((255, 120, 90), f * 0.8), prev, (x, y), max(1, int(16 * f)))
            prev = (x, y)

    def draw_debug(self, world) -> None:
        r, t = self.rufo, self.tomato
        pygame.draw.rect(world, (0, 255, 0), r.hurtbox(), 1)
        hb = r.hitbox()
        if hb:
            pygame.draw.rect(world, (255, 0, 0), hb, 2)
        lines = [f"FPS {self.fps:.0f}  Rufo {r.state}/{r.atk} chain={r.chain} vx={r.vx:.0f} vy={r.vy:.0f} suelo={r.on_ground} tomate={r.on_tomato}"]
        if t is not None:
            rx, ry = t.radii()
            pygame.draw.ellipse(world, (255, 255, 0), (t.x - rx, t.y - ry, 2 * rx, 2 * ry), 1)
            wx, wy = t.weak_pos()
            pygame.draw.circle(world, (0, 255, 255), (wx, wy), 26, 1)
            lines.append(f"Tomate {t.state}/{t.attack}/{t.phase} hp={t.hp}/{t.maxhp} t={t.timer:.2f} pausa={t.pause:.2f} furia={t.fury()}")
        for j in self.jets:
            xa, xb = sorted((j["tail"], j["front"]))
            pygame.draw.rect(world, (255, 0, 255), (xa, j["y"] - 10, xb - xa, 20), 1)
        lines.append(f"particulas={len(self.fx.p)} bloom={self.bloom}")
        for i, s in enumerate(lines):
            world.blit(self.txt.plain(s, 20, (0, 255, 120)), (50, 100 + i * 18))

    # ── postprocesado ───────────────────────────────────────────────────
    def post(self) -> None:
        world = self.world
        if self.bloom:
            small = pygame.transform.smoothscale(world, (W // 4, H // 4))
            small.fill((140, 140, 140), special_flags=pygame.BLEND_SUB)
            small = pygame.transform.smoothscale(pygame.transform.smoothscale(small, (W // 16, H // 16)), (W // 4, H // 4))
            small.blit(small, (0, 0), special_flags=pygame.BLEND_ADD)
            world.blit(pygame.transform.smoothscale(small, (W, H)), (0, 0), special_flags=pygame.BLEND_ADD)
        out = world
        if self.ab_t > 0 and self.opts["flashes"]:
            # Aberración cromática en los críticos
            off = int(2 + 8 * self.ab_t / 0.2)
            rch = world.copy()
            rch.fill((255, 0, 0), special_flags=pygame.BLEND_MULT)
            bch = world.copy()
            bch.fill((0, 0, 255), special_flags=pygame.BLEND_MULT)
            out = world.copy()
            out.fill((0, 255, 0), special_flags=pygame.BLEND_MULT)
            out.blit(rch, (-off, 0), special_flags=pygame.BLEND_ADD)
            out.blit(bch, (off, 0), special_flags=pygame.BLEND_ADD)
        if self.zoom_t > 0:
            z = 1 + 0.09 * math.sin(math.pi * self.zoom_t / 0.28)
            vw, vh = int(W / z), int(H / z)
            cx = clamp(self.zoom_at[0] - vw / 2, 0, W - vw)
            cy = clamp(self.zoom_at[1] - vh / 2, 0, H - vh)
            out = pygame.transform.smoothscale(out.subsurface((cx, cy, vw, vh)), (W, H))
        scr = self.screen
        scr.fill((8, 6, 12))
        amp = 16 * self.trauma**2 * self.opts["shake"] / 100
        ox = amp * (math.sin(self.real_t * 71) + math.sin(self.real_t * 43.7)) * 0.5
        oy = amp * (math.sin(self.real_t * 63.3) + math.sin(self.real_t * 37.1)) * 0.5
        scr.blit(out, (ox, oy))
        scr.blit(self.scene.vignette, (0, 0))
        if self.flash > 0:
            v = int(255 * min(1.0, self.flash) * (0.8 if self.opts["flashes"] else 0.2))
            scr.fill((v, int(v * 0.85), int(v * 0.8)), special_flags=pygame.BLEND_ADD)
        if self.red > 0:
            v = int(120 * self.red * (1.0 if self.opts["flashes"] else 0.35))
            scr.fill((v, 0, 0), special_flags=pygame.BLEND_ADD)
        if self.state == "title":
            self.draw_title(scr)
        else:
            self.draw_hud(scr)
            if self.banner:
                self.draw_banner(scr)
            if self.tip and self.state == "play":
                self.draw_tip(scr)
            if self.demo and int(self.real_t * 1.5) % 2 == 0:
                blit_center(scr, self.txt.outlined("DEMO · pulsa cualquier tecla", 34, (255, 220, 120)), W / 2, H - 40)
            if self.state == "over":
                self.draw_over(scr)
            elif self.paused:
                self.draw_pause(scr)

    # ── interfaz ───────────────────────────────────────────────────────
    def draw_hud(self, scr) -> None:
        txt = self.txt
        for i in range(MAX_HEARTS):
            draw_heart(scr, 70 + i * 46, 48, 17, i < self.hearts, 0.08 * math.sin(self.real_t * 8) if i == self.hearts - 1 and self.hearts == 1 else 0)
        scr.blit(txt.outlined(f"{int(self.shown_score):,}".replace(",", " "), 40, WHITE), (50, 76))
        if self.cheated and not self.demo:
            badge = txt.outlined("TRUCOS", 20, (255, 150, 60))
            scr.blit(badge, (196, 52))
        if self.combo > 1:
            mult = min(5.0, 1 + 0.1 * (self.combo - 1))
            img = txt.outlined(f"COMBO {self.combo}  ×{mult:.1f}", 28, (255, 210, 90))
            scr.blit(img, (52, 116))
            left = clamp(1 - (self.t - self.last_hit) / COMBO_WINDOW, 0, 1)
            pygame.draw.rect(scr, OUT, (54, 146, 184, 8), border_radius=4)
            pygame.draw.rect(scr, (255, 200, 80), (55, 147, int(182 * left), 6), border_radius=3)
        if self.combo_pop:
            word, life = self.combo_pop
            k = back_out(min(1.0, (1.2 - life) / 0.2))
            img = self.txt.outlined(word, max(8, int(44 * k)), (255, 120, 60), w=4)
            if life < 0.3:
                img = img.copy()
                img.set_alpha(int(255 * life / 0.3))
            scr.blit(img, (52, 158))
        t = self.tomato
        r = self.rufo
        hidden = r.y < 190 and abs(r.x - W / 2) < 330
        self.hud_alpha = approach(getattr(self, "hud_alpha", 1.0), 0.3 if hidden else 1.0, 0.08)
        top = pygame.Surface((W, 90), pygame.SRCALPHA)
        self.draw_top_center(top, t)
        top.set_alpha(int(255 * self.hud_alpha))
        scr.blit(top, (0, 0))
        tl = max(0.0, self.time_left)
        s = f"{int(tl) // 60}:{int(tl) % 60:02d}"
        if tl < 10:
            pulse = 1 + 0.18 * max(0.0, math.sin((tl % 1) * math.pi))
            img = txt.outlined(s, int(64 * pulse), (255, 70, 60))
        else:
            img = txt.outlined(s, 64, WHITE)
        scr.blit(img, (W - 60 - img.get_width(), 22))

    def draw_top_center(self, scr, t: Tomato | None) -> None:
        name = KIND_NAMES[t.kind if t is not None else tomato_kind(self.level)]
        img = self.txt.outlined(f"{name} · NIVEL {self.level}", 30, (255, 236, 220))
        blit_center(scr, img, W / 2, 34)
        bw, bx, by = 460, W / 2 - 230, 56
        pygame.draw.rect(scr, OUT, (bx - 3, by - 3, bw + 6, 24), border_radius=12)
        pygame.draw.rect(scr, (50, 20, 26), (bx, by, bw, 18), border_radius=9)
        if t is not None:
            trail = t.hp_trail / t.maxhp
            hp = t.hp / t.maxhp
            if trail > 0:
                pygame.draw.rect(scr, (255, 240, 230), (bx, by, int(bw * trail), 18), border_radius=9)
            if hp > 0:
                col = (230, 40, 40) if not t.fury() else mix((150, 10, 20), (255, 60, 40), 0.5 + 0.5 * math.sin(self.real_t * 12))
                pygame.draw.rect(scr, col, (bx, by, int(bw * hp), 18), border_radius=9)
                pygame.draw.rect(scr, (255, 140, 120), (bx + 6, by + 3, max(0, int(bw * hp) - 12), 4), border_radius=2)
            if t.max_armor and t.armor > 0:
                a = t.armor / t.max_armor
                pygame.draw.rect(scr, (60, 70, 80), (bx, by, bw, 18), border_radius=9)
                pygame.draw.rect(scr, (170, 196, 210), (bx, by, int(bw * a), 18), border_radius=9)
                pygame.draw.rect(scr, (235, 245, 255), (bx + 6, by + 3, max(0, int(bw * a) - 12), 4), border_radius=2)
                blit_center(scr, self.txt.outlined("CORAZA", 20, (230, 240, 255)), W / 2, by + 9)

    def draw_banner(self, scr) -> None:
        title, sub, life, mx = self.banner
        age = mx - life
        k = back_out(min(1.0, age / 0.3))
        a = min(1.0, life / 0.3)
        img = self.txt.outlined(title, int(110 * (0.5 + 0.5 * k)), (255, 230, 170), w=5)
        img = img.copy()
        img.set_alpha(int(255 * a))
        blit_center(scr, img, W / 2, H * 0.36)
        if sub:
            s = self.txt.outlined(sub, 32, (230, 230, 240)).copy()
            s.set_alpha(int(255 * a))
            blit_center(scr, s, W / 2, H * 0.36 + 72)

    def draw_title(self, scr) -> None:
        bob = math.sin(self.title_t * 2) * 6
        k = back_out(min(1.0, self.title_t / 0.8))
        img = self.title_img
        if k < 0.999:
            img = pygame.transform.smoothscale(img, (max(1, int(img.get_width() * k)), max(1, int(img.get_height() * k))))
        blit_center(scr, img, W / 2, 140 + bob)
        tag = self.txt.outlined("Un tomate del tamaño de una casa. Un cocinero diminuto con guantes de boxeo. Noventa segundos.", 26, (235, 225, 215))
        blit_center(scr, tag, W / 2, 250)
        if self.menu == "main":
            self.draw_menu(scr, MENU_MAIN, 70, 290, 430, 40, 38)
            if self.cheats_on():
                scr.blit(self.txt.outlined("trucos activos", 20, (255, 150, 60)), (300, 290 + 12 + 3 * 40 + 9))
            best = self.top[0] if self.top else None
            if best:
                rec = f"Récord: {best['score']:,}".replace(",", " ") + f"  ·  {best['name']}"
                blit_center(scr, self.txt.outlined(rec, 26, (255, 220, 140)), 285, 545)
        elif self.menu == "options":
            self.draw_menu(scr, MENU_OPTIONS, W / 2 - 330, 284, 660, 34, 30, values=True)
        elif self.menu == "cheats":
            self.draw_menu(scr, MENU_CHEATS, W / 2 - 330, 262, 660, 33, 30, values=True)
            note = "Con trucos la puntuación no entra en la tabla (cabezón y arcoíris son solo estéticos)"
            blit_center(scr, self.txt.outlined(note, 20, (255, 170, 100)), W / 2, 262 + 33 * len(MENU_CHEATS) + 40)
        else:
            self.draw_records(scr)
        hint = "W/S o flechas: elegir  ·  A/D: cambiar  ·  J/Espacio/Intro: aceptar  ·  Esc: volver"
        blit_center(scr, self.txt.plain(hint, 20, (200, 195, 210)), W / 2, H - 22)

    def draw_menu(self, scr, items: list[str], x: float, y: float, w: int, step: int, size: int, values: bool = False) -> None:
        scr.blit(panel((w, step * len(items) + 24), 180, 16), (x, y))
        for i, item in enumerate(items):
            yy = y + 12 + i * step + step / 2
            sel = i == self.cursor
            if sel:
                glow_w = w - 24
                bar = pygame.Surface((glow_w, step - 6), pygame.SRCALPHA)
                pulse = 0.5 + 0.5 * math.sin(self.real_t * 6)
                pygame.draw.rect(bar, (255, 120, 60, int(70 + 50 * pulse)), bar.get_rect(), border_radius=10)
                scr.blit(bar, (x + 12, yy - (step - 6) / 2))
            col = (255, 230, 170) if sel else (215, 210, 225)
            label = self.txt.outlined(item, size, col) if sel else self.txt.plain(item, size, col)
            scr.blit(label, (x + 30, yy - label.get_height() / 2))
            val = self.option_value(item)
            if val:
                v = self.txt.plain(val, size, (255, 210, 120) if sel else (190, 185, 200))
                scr.blit(v, (x + w - 30 - v.get_width(), yy - v.get_height() / 2))

    def draw_records(self, scr) -> None:
        cw, ch = 620, 420
        x, y = W / 2 - cw / 2, 278
        scr.blit(panel((cw, ch), 200, 18), (x, y))
        blit_center(scr, self.txt.outlined("RÉCORDS", 44, (255, 220, 160)), W / 2, y + 34)
        if not self.top:
            blit_center(scr, self.txt.plain("Aún no hay récords. ¡A por el primero!", 30, (220, 215, 230)), W / 2, y + ch / 2)
        for i, e in enumerate(self.top):
            yy = y + 70 + i * 33
            col = (255, 220, 120) if i == 0 else (225, 220, 235)
            scr.blit(self.txt.plain(f"{i + 1:>2}.", 28, col), (x + 40, yy))
            scr.blit(self.txt.plain(e["name"], 28, col), (x + 100, yy))
            scr.blit(self.txt.plain(f"nivel {e.get('level', 0)} · {e.get('diff', 'Normal')}", 24, (170, 165, 185)), (x + 200, yy + 3))
            v = self.txt.plain(f"{e['score']:,}".replace(",", " "), 28, col)
            scr.blit(v, (x + cw - 40 - v.get_width(), yy))

    def draw_tip(self, scr) -> None:
        text, life = self.tip
        a = clamp(min(life / 0.4, (4.5 - life) / 0.25), 0, 1)
        img = self.txt.outlined(text, 28, (255, 245, 220))
        w, h = img.get_width() + 40, img.get_height() + 18
        box = panel((w, h), 200, 12)
        pygame.draw.rect(box, (255, 200, 90, 160), (0, 0, 6, h), border_radius=3)
        box.blit(img, (22, 9))
        box.set_alpha(int(255 * a))
        scr.blit(box, (W / 2 - w / 2, H - 120 + (1 - a) * 20))

    def draw_pause(self, scr) -> None:
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((6, 4, 10, 170))
        scr.blit(dim, (0, 0))
        blit_center(scr, self.txt.outlined("PAUSA", 110, (255, 230, 170), w=5), W / 2, H * 0.36)
        blit_center(scr, self.txt.outlined("P / Esc / J: seguir   ·   Q: menú", 32, (230, 230, 240)), W / 2, H * 0.36 + 80)

    def draw_over(self, scr) -> None:
        k = ease_out(min(1.0, self.over_t / 0.5))
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((6, 4, 10, int(160 * k)))
        scr.blit(dim, (0, 0))
        cw, ch = 560, 470
        y = H / 2 - ch / 2 + (1 - k) * 80
        scr.blit(panel((cw, ch), 210, 22), (W / 2 - cw / 2, y))
        blit_center(scr, self.txt.outlined("FIN DE LA PARTIDA", 64, (255, 220, 160), w=4), W / 2, y + 50)
        rows = [
            ("Puntos", f"{self.score:,}".replace(",", " ")),
            ("Récord", f"{max(self.best, self.score):,}".replace(",", " ") + ("  ¡NUEVO!" if self.new_record else "")),
            ("Tomates reventados", str(self.stats["tomatoes"])),
            ("Combo máximo", str(self.stats["max_combo"])),
            ("Críticos", str(self.stats["crits"])),
            ("Esquivas perfectas", str(self.stats["perfect"])),
        ]
        for i, (a, b) in enumerate(rows):
            yy = y + 104 + i * 40
            scr.blit(self.txt.plain(a, 32, (210, 205, 220)), (W / 2 - 230, yy))
            col = (255, 220, 100) if (i == 1 and self.new_record) else WHITE
            v = self.txt.plain(b, 34, col)
            scr.blit(v, (W / 2 + 230 - v.get_width(), yy))
        if self.cheated:
            blit_center(scr, self.txt.outlined("Partida con trucos: no entra en la tabla", 26, (255, 160, 90)), W / 2, y + ch - 80)
        if self.entering:
            blit_center(scr, self.txt.outlined("¡ENTRAS EN LA TABLA! Tus iniciales:", 28, (255, 220, 120)), W / 2, y + ch - 112)
            for i, ch_ in enumerate(self.name):
                cx = W / 2 + (i - 1) * 64
                sel = i == self.name_i and int(self.real_t * 3) % 2 == 0
                pygame.draw.rect(scr, (255, 150, 80) if sel else (90, 80, 100), (cx - 26, y + ch - 92, 52, 58), 3, border_radius=8)
                blit_center(scr, self.txt.outlined(ch_, 48, WHITE), cx, y + ch - 62)
            blit_center(scr, self.txt.plain("Escribe o usa W/S · Intro para guardar", 20, (190, 185, 200)), W / 2, y + ch - 16)
        else:
            if self.rank >= 0:
                blit_center(scr, self.txt.outlined(f"Puesto {self.rank + 1} en la tabla de récords", 28, (160, 230, 255)), W / 2, y + ch - 80)
            if self.over_t > 0.8 and int(self.over_t * 2) % 2 == 0:
                blit_center(scr, self.txt.outlined("ESPACIO / J: otra  ·  Esc: menú", 30, (255, 220, 120)), W / 2, y + ch - 34)


# ═══════════════════════════════════════════════════════════════════════════
# 13. ARRANQUE, SELFTEST Y CAPTURAS
# ═══════════════════════════════════════════════════════════════════════════


def load_config() -> tuple[dict[str, list[str]], dict]:
    """Lee ~/.tomatoes/config.json (teclas y opciones) y lo reescribe completo."""
    path = CFG_DIR / "config.json"
    cfg = load_json(path, None)
    keys = dict(DEFAULT_KEYS)
    opts = dict(OPT_DEFAULT)
    if isinstance(cfg, dict):
        for k, v in (cfg.get("keys") or {}).items():
            if k in keys and isinstance(v, list) and all(isinstance(x, str) for x in v):
                keys[k] = v
        for k, v in (cfg.get("options") or {}).items():
            if k in opts and type(v) is type(opts[k]):
                opts[k] = v
            elif k == "last_name" and isinstance(v, str):
                opts[k] = v
            elif k == "cheats" and isinstance(v, dict):
                opts[k] = {ck: cv for ck, cv in v.items() if ck in CHEAT_DEFAULT and type(cv) is type(CHEAT_DEFAULT[ck])}
    if opts["difficulty"] not in DIFFICULTY:
        opts["difficulty"] = "Normal"
    save_json(path, {"keys": keys, "options": opts})
    return keys, opts


def load_records() -> list[dict]:
    rec = load_json(CFG_DIR / "record.json", {})
    top: list[dict] = []
    if isinstance(rec, dict):
        for e in rec.get("top", []) if isinstance(rec.get("top"), list) else []:
            if isinstance(e, dict) and isinstance(e.get("score"), int) and isinstance(e.get("name"), str):
                top.append({"name": e["name"][:3], "score": e["score"], "level": int(e.get("level", 0)), "diff": str(e.get("diff", "Normal"))})
        best = rec.get("best", 0)
        if not top and isinstance(best, int) and best > 0:  # récord del formato antiguo
            top.append({"name": "???", "score": best, "level": 0, "diff": "Normal"})
    top.sort(key=lambda e: -e["score"])
    return top[:10]


def save_records(top: list[dict]) -> None:
    save_json(CFG_DIR / "record.json", {"best": top[0]["score"] if top else 0, "top": top})


def make_screen(headless: bool) -> pygame.Surface:
    pygame.display.set_caption("TOMATOES")
    if headless:
        return pygame.display.set_mode((W, H))
    for flags, vs in ((pygame.SCALED | pygame.RESIZABLE, 1), (pygame.SCALED, 0), (0, 0)):
        try:
            return pygame.display.set_mode((W, H), flags, vsync=vs)
        except pygame.error:
            continue
    return pygame.display.set_mode((W, H))


class Bot:
    """Jugador automático muy simple para el selftest."""

    def __init__(self):
        self.next_punch = 0.0

    def act(self, g: Game) -> tuple[set[str], list[str]]:
        held: set[str] = set()
        presses: list[str] = []
        r, t = g.rufo, g.tomato
        if t is None or g.sub != "fight":
            return held, presses
        rx, ry = t.radii()
        side = 1 if r.x >= t.x else -1
        if t.state == "tele" and t.attack == "jet":
            if t.jet_high:
                held.add("down")
            elif t.timer > t.tele("jet") - 0.06:
                presses.append("jump")
                held.add("jump")
            return held, presses
        if g.jets:
            held.add("down" if g.jets[0]["y"] < FLOOR - 30 else "jump")
            return held, presses
        if t.state == "atk" and t.attack == "roll" and t.phase == "go":
            if abs(r.x - t.x) < rx + 140 and r.dash_cd <= 0:
                held.add("left" if t.x < r.x else "right")
                presses.append("dash")
            return held, presses
        if t.state == "atk" and t.attack == "bounce" and t.phase in ("hover", "fall"):
            away = 1 if r.x >= t.target_x else -1
            if r.x + away * 300 > WALL_R or r.x + away * 300 < WALL_L:
                away = -away
            held.add("right" if away > 0 else "left")
            if t.phase == "fall" and r.dash_cd <= 0:
                presses.append("dash")
            return held, presses
        for c in g.cherries:
            if c["y"] >= FLOOR - CHERRY_R - 2 and abs(c["x"] - r.x) < 80:
                held.update({"down", "right" if c["x"] > r.x else "left"})
                if g.t >= self.next_punch:
                    presses.append("jab")
                    self.next_punch = g.t + 0.2
                return held, presses
        target = t.x + side * (rx + RUFO_W / 2 + 6)
        if abs(r.x - target) > 18:
            held.add("right" if target > r.x else "left")
        elif g.t >= self.next_punch:
            held.add("left" if side > 0 else "right")
            presses.append("hook" if t.armor > 0 else random.choice(["jab", "jab", "hook"]))
            self.next_punch = g.t + (0.3 if t.armor > 0 else 0.16)
        return held, presses


def run_headless(seconds: float, shots: Path | None = None) -> dict:
    global CFG_DIR
    CFG_DIR = Path(tempfile.mkdtemp(prefix="tomatoes-"))  # nunca tocar el récord real
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    pygame.init()
    screen = make_screen(True)
    audio = Audio(enabled=True)
    random.seed(1)
    g = Game(screen, audio, DEFAULT_KEYS)
    taken: list[str] = []

    def shot(name: str) -> None:
        if shots is not None:
            shots.mkdir(parents=True, exist_ok=True)
            pygame.image.save(screen, str(shots / f"{name}.png"))
            taken.append(name)

    for _ in range(90):
        g.update(1 / 60)
    g.draw()
    shot("01_titulo")
    g.new_game()
    g.tart.sync_bakes = 0
    bot = Bot()
    frame = 0
    draw_ms = []
    shots_due = {"02_combate": 9.0, "03_combate": 21.0}
    burst_shot = False
    max_level = 1
    while g.state == "play" and g.t < seconds:
        held, presses = bot.act(g)
        g.inp.virtual = held
        for p in presses:
            g.press(p)
        g.update(1 / 60)
        frame += 1
        max_level = max(max_level, g.level)
        if frame % 3 == 0 or g.sub == "burst":
            t0 = time.perf_counter()
            g.draw()
            draw_ms.append((time.perf_counter() - t0) * 1000)
        for name, at in list(shots_due.items()):
            if g.t >= at:
                g.draw()
                shot(name)
                del shots_due[name]
        if g.sub == "burst" and not burst_shot and g.sub_t > 0.05:
            g.draw()
            shot("04_splash")
            burst_shot = True
        if g.tomato is not None and g.tomato.state == "tele" and g.tomato.attack == "jet" and "05_aviso_chorro" not in taken and g.tomato.timer > 0.3:
            g.draw()
            shot("05_aviso_chorro")
        if g.tomato is not None and g.tomato.attack == "bounce" and g.tomato.phase == "hover" and "06_aviso_bote" not in taken and g.tomato.timer > 0.5:
            g.draw()
            shot("06_aviso_bote")
    if g.state == "play":
        g.time_left = 0.01
        for _ in range(200):
            g.update(1 / 60)
    for _ in range(60):
        g.update(1 / 60)
    g.draw()
    shot("07_fin")
    res = {
        "score": g.score,
        "level": max_level,
        "tomatoes": g.stats["tomatoes"],
        "crits": g.stats["crits"],
        "max_combo": g.stats["max_combo"],
        "perfect": g.stats["perfect"],
        "hearts": g.hearts,
        "draw_ms_avg": sum(draw_ms) / max(1, len(draw_ms)),
        "draw_ms_p95": sorted(draw_ms)[int(len(draw_ms) * 0.95)] if draw_ms else 0,
        "draw_ms_max": max(draw_ms, default=0),
        "sync_bakes": g.tart.sync_bakes,
        "shots": taken,
        "audio": audio.ok,
        "state": g.state,
    }
    g.tart.close()
    pygame.quit()
    return res


def _test_game() -> Game:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    pygame.init()
    return Game(make_screen(True), Audio(False), DEFAULT_KEYS)


def _arena(g: Game, level: int, attacks: list[str] | None = None, x: float = 900.0) -> Tomato:
    """Partida preparada: tomate ya en el suelo, quieto salvo que se den ataques."""
    g.new_game()
    g.banner = None
    g.level = level
    t = g.tomato = Tomato(level, x=x, diff=g.diff())
    t.state = "idle"
    t.y = FLOOR - t.radii()[1]
    t.pause = 0.0 if attacks else 99.0
    if attacks:
        t.attacks = attacks
    return t


def _run(g: Game, secs: float, held=(), until=None) -> bool:
    g.inp.virtual = set(held)
    for _ in range(int(secs * PHYS_HZ)):
        g.hitstop = 0.0
        g.step(DT)
        if until is not None and until():
            return True
    return False


def mechanics(check) -> None:
    """Comprueba las mecánicas una a una con entradas simuladas."""
    global CFG_DIR
    CFG_DIR = Path(tempfile.mkdtemp(prefix="tomatoes-"))
    random.seed(5)
    g = _test_game()
    # Golpe cargado
    _arena(g, 1)
    r = g.rufo
    g.press("jab")
    _run(g, 0.9, {"jab"})
    check(r.state == "charge", "mantener J carga el golpe")
    _run(g, 0.02)
    check(r.state == "attack" and r.atk == "charge" and r.atk_dmg == 5, "al soltar sale el cargado con daño según la carga")
    # Cadena contra el tomate
    t = _arena(g, 1)
    r = g.rufo
    r.x = t.x - t.radii()[0] - 60
    _run(g, 0.4, {"right"})
    seq = []
    for k in ("jab", "jab", "hook", "jab"):
        g.press(k)
        _run(g, 0.5, until=lambda: r.state == "attack" and r.phase()[0] == "rc")
        seq.append(r.atk)
    check(seq == ["jab", "jab", "hook", "upper"], "cadena " + " → ".join(seq))
    check(t.hp < t.maxhp and g.combo >= 3, "los golpes conectan y suben el combo")
    # Trepar: doble salto + ascendente con rebote
    t = _arena(g, 1, x=640)
    r = g.rufo
    r.x = t.x - t.radii()[0] - 30
    for i in range(int(3 * PHYS_HZ)):  # como un jugador: salta, y en cada cima, doble salto o ascendente
        held = {"jump", "right"}
        if r.on_ground and not r.on_tomato:
            g.press("jump")
        elif r.vy > -60 and r.state == "normal":
            if r.air_jumps > 0:
                g.press("jump")
            else:
                held.add("up")
                g.press("jab")
        _run(g, DT, held)
        if r.on_tomato:
            break
    check(r.on_tomato, "doble salto + ascendente con rebote: Rufo trepa a la corona")
    # Rodada atravesada con la esquiva
    t = _arena(g, 1, ["roll"], x=700)
    r = g.rufo
    r.x = 300
    for _ in range(600):
        if t.state == "atk" and t.phase == "go" and abs(r.x - t.x) < t.radii()[0] + 80 and r.state != "dash" and r.dash_cd <= 0:
            g.press("dash")
        _run(g, DT)
        if t.state == "stun":
            break
    check(g.hearts == MAX_HEARTS and g.stats["perfect"] >= 1, "la esquiva atraviesa la rodada (esquiva perfecta)")
    # Chorro bajo: se salta
    t = _arena(g, 3, ["jet"], x=900)
    r = g.rufo
    r.x = 400
    for _ in range(300):
        if t.state == "tele":
            t.jet_high = False
            if t.timer > t.tele("jet") - 0.08:
                g.press("jump")
        _run(g, DT, {"jump"})
        if t.state == "stun":
            break
    check(g.hearts == MAX_HEARTS, "el chorro bajo se esquiva saltando")
    # Tomate verde blindado
    t = _arena(g, 4)
    r = g.rufo
    r.x = t.x - t.radii()[0] - 60
    _run(g, 0.4, {"right"})
    g.press("jab")
    _run(g, 0.3)
    check(t.hp == t.maxhp and t.armor < t.max_armor, "tomate verde: el jab rebota en la coraza")
    for _ in range(24):
        _run(g, 0.1, {"right"})
        g.press("hook")
        _run(g, 0.4)
        if t.armor <= 0:
            break
    check(t.armor <= 0 and t.hp < t.maxhp, "los ganchos rompen la coraza y el tomate madura")
    # Tomate podrido: los charcos resbalan
    stop = []
    for slick in (False, True):
        _arena(g, 6)
        r = g.rufo
        r.x, r.vx = 400.0, RUN_MAX
        if slick:
            g.add_puddle(450, 120)
        _run(g, 1.0)
        stop.append(r.x - 400)
    check(stop[1] > stop[0] * 4, f"charco del podrido: frenada de {stop[0]:.0f} a {stop[1]:.0f} px")
    # Cherrys
    _arena(g, 7)
    r = g.rufo
    r.x = 500
    g.cherries.append({"x": 540.0, "y": FLOOR - CHERRY_R, "vx": 0.0, "vy": 0.0, "t": 0.0, "hop": 9.0, "id": "c", "sq": Spring(260, 10), "face": -1})
    _run(g, DT, {"down"})
    g.press("jab")
    _run(g, 0.3, {"down"})
    check(not g.cherries and g.score > 0, "el jab agachado revienta una cherry")
    _arena(g, 7, ["cherry"], x=1000)
    g.rufo.x = 300
    check(_run(g, 7.0, until=lambda: g.hearts < MAX_HEARTS), "las cherrys persiguen a Rufo y hacen daño")
    # Menú, opciones y récords en disco
    g.to_title()
    g.menu_input(["down"])
    g.menu_input(["right"])
    check(g.diff_name == "Difícil", "el menú cambia la dificultad")
    g2 = Game(g.screen, Audio(False), *load_config())
    check(g2.diff_name == "Difícil" and Tomato(1, diff=g2.diff()).pause < 3.0, "las opciones se guardan y afectan al tomate")
    g.new_game()
    g.score = 1234
    g.game_over()
    check(g.entering, "una puntuación de la tabla pide iniciales")
    for ch in "ABC":
        g.name_input(pygame.event.Event(pygame.KEYDOWN, key=0, unicode=ch, mod=0, scancode=0), [])
    g.name_input(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r", mod=0, scancode=0), [])
    top = load_records()
    check(bool(top) and top[0]["name"] == "ABC" and top[0]["score"] == 1234, "la tabla de récords se guarda con iniciales")
    # Trucos
    g.to_title()
    for _ in range(MENU_MAIN.index("TRUCOS") - g.cursor):
        g.menu_input(["down"])
    g.menu_input(["confirm"])
    check(g.menu == "cheats", "el menú principal abre los trucos")
    g.menu_input(["confirm"])  # vidas infinitas
    for _ in range(5):
        g.menu_input(["down"])
    g.menu_input(["right"])
    g.menu_input(["right"])  # empezar en el nivel 3
    check(g.cheats["infinite"] and g.cheats["start_level"] == 3, "los trucos se activan desde el menú")
    check(load_config()[1]["cheats"]["start_level"] == 3, "los trucos se guardan")
    g.new_game()
    check(g.level == 3 and g.tomato.level == 3 and g.cheated, "«empezar en el nivel» arranca en el nivel elegido")
    g.hurt_rufo(g.rufo.x + 50)
    check(g.hearts == MAX_HEARTS, "con vidas infinitas un golpe no quita corazón")
    g.score = 99999
    g.game_over()
    check(not g.entering and load_records()[0]["score"] != 99999, "con trucos la puntuación no entra en la tabla")
    g.to_title()
    g.start_demo()
    check(g.level == 1 and not g.cheated, "la demo juega sin trucos")
    g.to_title()
    g.menu, g.cursor = "cheats", MENU_CHEATS.index("Desactivar todos")
    g.menu_input(["confirm"])
    check(not g.cheats_on(), "«Desactivar todos» los apaga")
    # Modo demo
    g.to_title()
    g.idle_t = DEMO_IDLE + 1
    g.update(1 / 60)
    check(g.state == "play" and g.demo, "el título lanza el modo demo si nadie toca nada")
    g.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE, unicode=" ", mod=0, scancode=0))
    check(g.state == "title", "cualquier tecla corta la demo")
    # Niveles especiales jugados por el bot, con dibujo incluido
    bot = Bot()
    for lvl in (4, 6, 7, 8):
        t = _arena(g, lvl)
        t.pause = 0.6
        for i in range(60 * 8):
            held, presses = bot.act(g)
            g.inp.virtual = held
            for a in presses:
                g.press(a)
            g.update(1 / 60)
            if i % 6 == 0:
                g.draw()
            if g.state != "play":
                break
        check(True, f"nivel {lvl} ({KIND_NAMES[tomato_kind(lvl)].lower()}) jugado y dibujado sin errores")
    g.tart.close()
    g2.tart.close()
    pygame.quit()


def gallery(out: Path) -> list[str]:
    """Capturas de las situaciones más vistosas (para el README y la CI)."""
    global CFG_DIR
    CFG_DIR = Path(tempfile.mkdtemp(prefix="tomatoes-"))
    out.mkdir(parents=True, exist_ok=True)
    random.seed(3)
    g = _test_game()
    bot = Bot()
    names: list[str] = []

    def ready() -> None:
        for f in list(g.tart.pending.values()):
            f.result()
        g.tart.poll()

    def shot(name: str) -> None:
        ready()
        if g.tomato is not None:
            g.tomato.flash = 0.0  # sin el destello del último impacto
        g.flash = 0.0
        g.draw()
        pygame.image.save(g.screen, str(out / f"{name}.png"))
        names.append(name)

    def play(secs: float, until=None) -> None:
        for _ in range(int(secs * 60)):
            held, presses = bot.act(g)
            g.inp.virtual = held
            for a in presses:
                g.press(a)
            g.update(1 / 60)
            if until is not None and until():
                return

    for _ in range(80):
        g.update(1 / 60)
    shot("menu")
    for level, attacks, secs, name in ((4, ["roll", "jet"], 5.0, "verde"), (6, ["roll"], 6.0, "podrido"), (9, ["seeds"], 3.0, "pepitas")):
        t = _arena(g, level, attacks, x=820)
        g.tart.warm(t)
        play(secs)
        shot(name)
    t = _arena(g, 7, ["cherry"], x=950)
    g.tart.warm(t)
    play(4.0, until=lambda: len(g.cherries) >= 3 and all(c["y"] > FLOOR - 120 for c in g.cherries))
    shot("cherrys")
    t = _arena(g, 5, x=760)
    g.tart.warm(t)
    t.hp = int(t.maxhp * 0.2)
    for _ in range(9):
        t.take_hit(random.uniform(-2.8, 0.6), 0, 0, False)
    t.flash = 0
    g.rufo.x = 380
    play(1.2)
    shot("furia")
    g.tart.close()
    pygame.quit()
    return names


def selftest() -> int:
    ok = True

    def check(cond: bool, msg: str) -> None:
        nonlocal ok
        print(("  ok  " if cond else "  FALLO ") + msg)
        ok = ok and cond

    print("TOMATOES selftest")
    # Unidades: tiempos de golpe y caja de colisión
    r = Rufo(300)
    r.state, r.atk, r.atk_t = "attack", "jab", 3.5 * FRAME
    check(r.phase()[0] == "ac", "el jab está activo en el fotograma 4")
    check(r.hitbox() is not None and r.hitbox().left > r.x, "la caja del jab sale hacia delante")
    r.facing = -1
    check(r.hitbox().right < r.x, "y se refleja al mirar a la izquierda")
    t = Tomato(1)
    check(t.r == 220 and t.maxhp == 30 and abs(t.pause - 3.0) < 1e-9, "tomate de nivel 1 según el diseño")
    t9 = Tomato(12)
    check(t9.r == 320 and abs(t9.pause - 1.2) < 1e-9 and "seeds" in t9.attacks, "topes de escalado a nivel alto")
    check(all(angle_ok(random_weak_angle()) for _ in range(200)), "el punto débil nunca cae debajo")
    check(rect_ellipse(pygame.Rect(95, -5, 10, 10), 0, 0, 100, 50) and not rect_ellipse(pygame.Rect(120, 0, 5, 5), 0, 0, 100, 50), "colisión rectángulo–elipse")
    mechanics(check)
    # Partida completa con bot
    res = run_headless(150.0)
    print("  partida:", {k: v for k, v in res.items() if k != "shots"})
    check(res["tomatoes"] >= 1, "el bot revienta al menos un tomate")
    check(res["state"] == "over", "la partida termina en la pantalla final")
    check(res["draw_ms_avg"] < 60, "render por debajo de 60 ms por fotograma (CPU, sin GPU)")
    check(res["sync_bakes"] == 0, "sin tirones: ningún horneado del tomate bloquea la partida")
    print("RESULTADO:", "OK" if ok else "FALLO")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pytomatoes", description="TOMATOES: Rufo contra el tomate gigante.")
    ap.add_argument("--selftest", action="store_true", help="partida simulada por un bot, sin ventana")
    ap.add_argument("--shots", type=Path, metavar="DIR", help="guardar capturas PNG de cada pantalla")
    ap.add_argument("--mute", action="store_true", help="arrancar sin sonido")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.shots:
        res = run_headless(60.0, args.shots)
        extra = gallery(args.shots)
        print("capturas:", ", ".join(res["shots"] + extra), "→", args.shots)
        return 0
    headless = os.environ.get("SDL_VIDEODRIVER") == "dummy"
    pygame.init()
    screen = make_screen(headless)
    try:
        pygame.joystick.init()
    except pygame.error:
        pass
    audio = Audio(enabled=not args.mute)
    keys, opts = load_config()
    g = Game(screen, audio, keys, opts)
    if opts["fullscreen"] and not headless:
        try:
            pygame.display.toggle_fullscreen()
        except pygame.error:
            pass
    clock = pygame.time.Clock()
    while g.running:
        dt = clock.tick(240) / 1000
        for e in pygame.event.get():
            g.handle(e)
        g.update(dt)
        g.draw()
        g.fps = clock.get_fps()
        pygame.display.flip()
    g.tart.close()
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
