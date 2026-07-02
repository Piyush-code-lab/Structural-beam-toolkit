"""
design_checks.py
=================
Engineering design-check utilities:
  - Serviceability (deflection limit) checks: L/250, L/360
  - Stress / Factor-of-Safety checks
  - Automatic lightest-section recommendation from the IPE database
"""

import numpy as np
from beam_solver import solve_beam_multi, max_bending_stress


def deflection_limits(L):
    """Return dict of standard deflection limits (m) for a span L (m)."""
    return {
        "L/250": L / 250,
        "L/360": L / 360,
    }


def evaluate_design(beam_type, loads, L, E, I, Z, yield_stress,
                     deflection_limit_key="L/360", min_safety_factor=1.5, n=500):
    """
    Run the solver and evaluate stress + deflection + safety-factor checks.

    Returns a result dict with all computed values and PASS/FAIL flags.
    """
    x, V, M, delta, used_numerical = solve_beam_multi(beam_type, loads, L, E, I, n=n)
    sigma = max_bending_stress(M, Z)

    max_def = np.max(np.abs(delta))
    max_sigma = np.max(np.abs(sigma))
    max_shear = np.max(np.abs(V))
    max_moment = np.max(np.abs(M))

    safety_factor = yield_stress / max_sigma if max_sigma > 0 else float("inf")
    limits = deflection_limits(L)
    allowable_defl = limits[deflection_limit_key]

    stress_pass = safety_factor >= min_safety_factor
    deflection_pass = max_def <= allowable_defl
    overall_pass = stress_pass and deflection_pass

    return {
        "x": x, "V": V, "M": M, "delta": delta, "sigma": sigma,
        "max_deflection": max_def,
        "max_stress": max_sigma,
        "max_shear": max_shear,
        "max_moment": max_moment,
        "safety_factor": safety_factor,
        "allowable_deflection": allowable_defl,
        "deflection_limit_key": deflection_limit_key,
        "stress_pass": stress_pass,
        "deflection_pass": deflection_pass,
        "overall_pass": overall_pass,
        "used_numerical_integration": used_numerical,
    }


def recommend_section(beam_type, loads, L, E, yield_stress, ipe_sections,
                       deflection_limit_key="L/360", min_safety_factor=1.5, n=300):
    """
    Iterate through the IPE catalogue (lightest first) and return the first
    section that satisfies stress, safety factor, AND deflection checks.

    Parameters
    ----------
    ipe_sections : dict from sections_db.load_ipe_sections()

    Returns
    -------
    (section_name, result_dict) for the first PASSing section, or
    (None, None) if no catalogue section satisfies the constraints.
    """
    candidates = sorted(ipe_sections.items(), key=lambda kv: kv[1]["weight"])

    for name, props in candidates:
        result = evaluate_design(
            beam_type, loads, L, E, props["I"], props["Z"], yield_stress,
            deflection_limit_key=deflection_limit_key,
            min_safety_factor=min_safety_factor, n=n
        )
        if result["overall_pass"]:
            result["section_name"] = name
            result["weight"] = props["weight"]
            return name, result

    return None, None
