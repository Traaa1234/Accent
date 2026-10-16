"""Colour tokens shared by charts, the HTML report and the PDF.

Direction uses a diverging pair (falling = blue, rising = red) with a neutral gray
for level; validated for colour-vision deficiency in both modes. Direction is
never shown by colour alone: charts also use position (sign of Δ), marker shape
(▲ / ▼) or a text label.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    surface: str
    page: str
    ink: str
    ink_secondary: str
    muted: str
    grid: str
    axis: str
    series: str
    falling: str
    rising: str
    level: str
    band: str  # target-zone fill
    good: str = "#0ca30c"
    warning: str = "#fab219"


LIGHT = Theme(
    name="light",
    surface="#fcfcfb",
    page="#f9f9f7",
    ink="#0b0b0b",
    ink_secondary="#52514e",
    muted="#898781",
    grid="#e1e0d9",
    axis="#c3c2b7",
    series="#2a78d6",
    falling="#2a78d6",
    rising="#e34948",
    level="#898781",
    band="#eef4ee",
)

DARK = Theme(
    name="dark",
    surface="#1a1a19",
    page="#0d0d0d",
    ink="#f0efec",
    ink_secondary="#c3c2b7",
    muted="#898781",
    grid="#2c2c2a",
    axis="#383835",
    series="#3987e5",
    falling="#3987e5",
    rising="#e66767",
    level="#898781",
    band="#1c241c",
)

THEMES = (LIGHT, DARK)
