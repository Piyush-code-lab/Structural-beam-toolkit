"""
sections_db.py
==============
Loads the IPE steel section catalogue from ipe_sections.csv into memory.

CSV units -> converted to SI (metres) on load:
    area_mm2        -> area_m2
    I_mm4           -> I_m4
    Z_mm3           -> Z_m3
    weight_kg_per_m -> kept as-is (already SI: kg/m)
"""

import csv
import os

_CSV_PATH = os.path.join(os.path.dirname(__file__), "ipe_sections.csv")


def load_ipe_sections(csv_path=_CSV_PATH):
    """
    Returns a dict keyed by section name:
        {
          "IPE200": {
              "I": <m^4>, "Z": <m^3>, "area": <m^2>,
              "weight": <kg/m>, "depth": <m>, "y": <m>  # y = depth/2, extreme fibre distance
          },
          ...
        }
    """
    sections = {}
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name"]
            I_m4 = float(row["I_mm4"]) * 1e-12      # mm^4 -> m^4
            Z_m3 = float(row["Z_mm3"]) * 1e-9        # mm^3 -> m^3
            area_m2 = float(row["area_mm2"]) * 1e-6  # mm^2 -> m^2
            depth_m = float(row["depth_mm"]) * 1e-3  # mm -> m
            sections[name] = {
                "I": I_m4,
                "Z": Z_m3,
                "area": area_m2,
                "weight": float(row["weight_kg_per_m"]),  # kg/m
                "depth": depth_m,
                "y": depth_m / 2,
            }
    return sections


def sections_sorted_by_weight(sections):
    """Return list of (name, props) tuples sorted lightest-first (steel weight)."""
    return sorted(sections.items(), key=lambda kv: kv[1]["weight"])


def weight_per_metre_for_material(section_props, density_kg_per_m3):
    """
    Compute weight per metre (kg/m) for a section made of a given material,
    using cross-sectional area x density. This generalizes the CSV's
    steel-only 'weight' column to any material (Aluminium, Timber, etc.)
    for use in optimization mode.
    """
    return section_props["area"] * density_kg_per_m3
