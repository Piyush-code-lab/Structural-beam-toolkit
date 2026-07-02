"""
materials.py
============
Material property database and non-IPE (rectangular/circular) cross-section
helpers. Kept separate from the IPE steel section database (sections_db.py)
since rectangular/circular sections are parametric, not catalogue-based.
"""

import numpy as np

# E in Pascals, yield strength in Pascals, density in kg/m^3, cost in $/kg
# (cost_per_kg figures are indicative market rates for raw structural stock;
#  used only for relative cost comparison between design options, not as a
#  quote-grade estimate)
MATERIALS = {
    "Steel":     {"E": 200e9, "yield": 250e6, "density": 7850, "cost_per_kg": 0.80},
    "Aluminium": {"E": 70e9,  "yield": 270e6, "density": 2700, "cost_per_kg": 2.50},
    "Concrete":  {"E": 30e9,  "yield": 30e6,  "density": 2400, "cost_per_kg": 0.10},
    "Timber":    {"E": 12e9,  "yield": 40e6,  "density": 600,  "cost_per_kg": 0.60},
}


def rectangular_section(width_m, height_m):
    """Return dict with I (m^4), Z (m^3), area (m^2) for a rectangular section."""
    I = (width_m * height_m ** 3) / 12
    Z = I / (height_m / 2)
    area = width_m * height_m
    return {"I": I, "Z": Z, "area": area, "y": height_m / 2}


def circular_section(diameter_m):
    """Return dict with I (m^4), Z (m^3), area (m^2) for a solid circular section."""
    r = diameter_m / 2
    I = np.pi * r ** 4 / 4
    Z = I / r
    area = np.pi * r ** 2
    return {"I": I, "Z": Z, "area": area, "y": r}


# Preset non-IPE sections (kept from the original project for quick manual selection)
PRESET_SECTIONS = {
    "Rectangular (100x200mm)": rectangular_section(0.1, 0.2),
    "Rectangular (50x100mm)":  rectangular_section(0.05, 0.1),
    "Circular (d=100mm)":      circular_section(0.1),
}
