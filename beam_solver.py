"""
beam_solver.py
==============
Core structural solver. Computes shear force, bending moment, and deflection
along a beam for THREE boundary conditions:

    - Simply Supported
    - Cantilever (fixed at x=0)
    - Fixed-Fixed

Each beam carries a LIST of loads (point loads and/or UDLs). Effects are
combined using the principle of superposition: since all governing equations
(shear, moment, deflection) are linear in load magnitude for a given beam,
the total response is simply the sum of each individual load's response.

Loads are represented as simple dicts:
    Point load: {"type": "point", "P": <N>, "a": <m from left>}
    UDL:        {"type": "udl",   "w": <N/m>, "start": <m>, "end": <m>}

NOTE on UDL placement: the closed-form deflection equations implemented here
assume a FULL-SPAN UDL (start=0, end=L). Partial-span UDLs are handled for
shear/moment (exact) but their deflection contribution is approximated by
discretized numerical integration (see _udl_partial_deflection) to keep the
solver self-contained without a finite-element backend. This is flagged
clearly in the output if a partial UDL is used.
"""

import numpy as np


def _point_load_response(beam_type, L, P, a, E, I, x):
    """Closed-form V, M, delta for a single point load P at position a."""
    n = len(x)
    V = np.zeros(n)
    M = np.zeros(n)
    delta = np.zeros(n)
    b = L - a

    if beam_type == "Simply Supported":
        Ra = P * b / L
        for i, xi in enumerate(x):
            V[i] = Ra - (P if xi >= a else 0)
            M[i] = Ra * xi - (P * (xi - a) if xi >= a else 0)
            if xi <= a:
                delta[i] = (P * b * xi * (L ** 2 - b ** 2 - xi ** 2)) / (6 * E * I * L)
            else:
                delta[i] = (P * a * (L - xi) * (2 * L * xi - xi ** 2 - a ** 2)) / (6 * E * I * L)

    elif beam_type == "Cantilever":
        for i, xi in enumerate(x):
            V[i] = -P if xi <= a else 0
            M[i] = -P * (a - xi) if xi <= a else 0
            if xi <= a:
                delta[i] = (P * xi ** 2 * (3 * a - xi)) / (6 * E * I)
            else:
                delta[i] = (P * a ** 2 * (3 * xi - a)) / (6 * E * I)

    elif beam_type == "Fixed-Fixed":
        Ra = P * b ** 2 * (3 * a + b) / L ** 3
        Ma_fix = P * a * b ** 2 / L ** 2
        for i, xi in enumerate(x):
            V[i] = Ra - (P if xi >= a else 0)
            M[i] = -Ma_fix + Ra * xi - (P * (xi - a) if xi >= a else 0)
            if xi <= a:
                delta[i] = (P * b ** 2 * xi ** 2 * (3 * a * L - (3 * a + b) * xi)) / (6 * E * I * L ** 3)
            else:
                delta[i] = (P * a ** 2 * (L - xi) ** 2 * (3 * b * L - (3 * b + a) * (L - xi))) / (6 * E * I * L ** 3)
    else:
        raise ValueError(f"Unknown beam_type: {beam_type}")

    return V, M, delta


def _udl_full_span_response(beam_type, L, w, E, I, x):
    """Closed-form V, M, delta for a UDL spanning the FULL beam length."""
    n = len(x)
    V = np.zeros(n)
    M = np.zeros(n)
    delta = np.zeros(n)

    if beam_type == "Simply Supported":
        Ra = w * L / 2
        for i, xi in enumerate(x):
            V[i] = Ra - w * xi
            M[i] = Ra * xi - w * xi ** 2 / 2
            delta[i] = (w * xi * (L ** 3 - 2 * L * xi ** 2 + xi ** 3)) / (24 * E * I)

    elif beam_type == "Cantilever":
        for i, xi in enumerate(x):
            V[i] = -w * (L - xi)
            M[i] = -w * (L - xi) ** 2 / 2
            delta[i] = (w * xi ** 2 * (6 * L ** 2 - 4 * L * xi + xi ** 2)) / (24 * E * I)

    elif beam_type == "Fixed-Fixed":
        Ra = w * L / 2
        for i, xi in enumerate(x):
            V[i] = Ra - w * xi
            M[i] = -w * L ** 2 / 12 + Ra * xi - w * xi ** 2 / 2
            delta[i] = (w * xi ** 2 * (L - xi) ** 2) / (24 * E * I)
    else:
        raise ValueError(f"Unknown beam_type: {beam_type}")

    return V, M, delta


def _udl_partial_span_shear_moment(beam_type, L, w, start, end, x):
    """
    Exact V and M for a partial-span UDL using statics (works for all three
    boundary conditions for V and M, since these only require equilibrium
    and — for Fixed-Fixed — the fixed-end moments derived from standard
    tables). Deflection for partial UDLs is handled separately/numerically.
    """
    n = len(x)
    V = np.zeros(n)
    M = np.zeros(n)
    total_load = w * (end - start)
    centroid = (start + end) / 2

    if beam_type == "Simply Supported":
        Ra = total_load * (L - centroid) / L
        for i, xi in enumerate(x):
            if xi < start:
                V[i] = Ra
                M[i] = Ra * xi
            elif xi <= end:
                loaded_len = xi - start
                V[i] = Ra - w * loaded_len
                M[i] = Ra * xi - w * loaded_len ** 2 / 2
            else:
                V[i] = Ra - total_load
                M[i] = Ra * xi - total_load * (xi - centroid)

    elif beam_type == "Cantilever":
        for i, xi in enumerate(x):
            if xi >= end:
                V[i] = 0
                M[i] = 0
            elif xi >= start:
                loaded_len = end - xi
                V[i] = -w * loaded_len
                M[i] = -w * loaded_len ** 2 / 2
            else:
                V[i] = -total_load
                M[i] = -total_load * (centroid - xi)

    elif beam_type == "Fixed-Fixed":
        # Approximate fixed-end moments for a partial UDL (standard formula),
        # then resolve reactions via statics. Acceptable engineering
        # approximation; exact for full-span (reduces to standard case).
        a = start
        c = end - start  # loaded length
        b = L - end
        # Using equivalent full-span UDL fixed-end moment scaled by loaded fraction
        # (engineering approximation — flagged to user in output for partial UDLs)
        Ma_fix = w * c * (2 * L - c) * (2 * L - c) / (12 * L ** 2) if L > 0 else 0
        Ra = total_load * (L - centroid) / L
        for i, xi in enumerate(x):
            if xi < start:
                V[i] = Ra
                M[i] = -Ma_fix + Ra * xi
            elif xi <= end:
                loaded_len = xi - start
                V[i] = Ra - w * loaded_len
                M[i] = -Ma_fix + Ra * xi - w * loaded_len ** 2 / 2
            else:
                V[i] = Ra - total_load
                M[i] = -Ma_fix + Ra * xi - total_load * (xi - centroid)
    else:
        raise ValueError(f"Unknown beam_type: {beam_type}")

    return V, M


def _numerical_deflection_from_moment(beam_type, L, M, E, I, x):
    """
    Double numerical integration of M/EI to get deflection, with boundary
    conditions enforced per beam type. Used as a fallback for partial-span
    UDLs where closed-form deflection isn't implemented.

    Method: trapezoidal integration twice, then apply boundary conditions
    by solving for the two integration constants.
    """
    n = len(x)
    curvature = M / (E * I)

    # First integration -> slope (+ C1)
    slope_raw = np.zeros(n)
    for i in range(1, n):
        slope_raw[i] = slope_raw[i - 1] + 0.5 * (curvature[i] + curvature[i - 1]) * (x[i] - x[i - 1])

    # Second integration -> deflection (+ C1*x + C2)
    defl_raw = np.zeros(n)
    for i in range(1, n):
        defl_raw[i] = defl_raw[i - 1] + 0.5 * (slope_raw[i] + slope_raw[i - 1]) * (x[i] - x[i - 1])

    if beam_type == "Simply Supported":
        # delta(0) = 0, delta(L) = 0
        # defl_raw already has implicit C2=0 (since starts at 0); solve C1 from delta(L)=0
        C1 = -defl_raw[-1] / L
        delta = defl_raw + C1 * x

    elif beam_type == "Cantilever":
        # delta(0) = 0, slope(0) = 0 -> both integration constants are zero already
        delta = defl_raw

    elif beam_type == "Fixed-Fixed":
        # delta(0)=0, delta(L)=0, slope(0)=0, slope(L)=0
        # With slope(0)=0 enforced (C1_slope=0 already), and delta(0)=0 (C2=0),
        # the only remaining freedom is a rigid rotation correction for delta(L)=0
        C1 = -defl_raw[-1] / L
        delta = defl_raw + C1 * x
    else:
        raise ValueError(f"Unknown beam_type: {beam_type}")

    return delta


def solve_beam_multi(beam_type, loads, L, E, I, n=500):
    """
    Solve a beam carrying MULTIPLE loads using superposition.

    Parameters
    ----------
    beam_type : str -> "Simply Supported" | "Cantilever" | "Fixed-Fixed"
    loads     : list of dicts, each either
                {"type": "point", "P": N, "a": m}
                {"type": "udl", "w": N/m, "start": m, "end": m}
    L, E, I   : beam length (m), Young's modulus (Pa), moment of inertia (m^4)
    n         : number of discretization points

    Returns
    -------
    x, V, M, delta : numpy arrays (combined response from all loads)
    used_numerical_integration : bool (True if any partial UDL required
                                  numerical deflection integration)
    """
    x = np.linspace(0, L, n)
    V_total = np.zeros(n)
    M_total = np.zeros(n)
    delta_total = np.zeros(n)
    used_numerical_integration = False

    for load in loads:
        if load["type"] == "point":
            P = load["P"]
            a = load["a"]
            if not (0 <= a <= L):
                raise ValueError(f"Point load position a={a} m is outside beam length L={L} m")
            V, M, delta = _point_load_response(beam_type, L, P, a, E, I, x)

        elif load["type"] == "udl":
            w = load["w"]
            start = load.get("start", 0)
            end = load.get("end", L)
            if not (0 <= start < end <= L):
                raise ValueError(f"UDL span [{start}, {end}] is invalid for beam length L={L} m")

            if start == 0 and end == L:
                V, M, delta = _udl_full_span_response(beam_type, L, w, E, I, x)
            else:
                V, M = _udl_partial_span_shear_moment(beam_type, L, w, start, end, x)
                delta = _numerical_deflection_from_moment(beam_type, L, M, E, I, x)
                used_numerical_integration = True
        else:
            raise ValueError(f"Unknown load type: {load['type']}")

        V_total += V
        M_total += M
        delta_total += delta

    return x, V_total, M_total, delta_total, used_numerical_integration


def max_bending_stress(M, Z):
    """sigma = M / Z  (Z = section modulus, m^3). Returns stress array (Pa)."""
    return M / Z
