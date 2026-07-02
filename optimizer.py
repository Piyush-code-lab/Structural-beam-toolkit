"""
optimizer.py
=============
Multi-Objective Design Optimization.

Iterates over every feasible (material, section) combination from the
existing databases and finds the design that best satisfies a chosen
objective, subject to the same engineering constraints used everywhere
else in the toolkit (stress, factor of safety, serviceability deflection).

Objectives supported:
    - "weight"   : Minimum weight per metre
    - "cost"     : Minimum material cost per metre
    - "safety"   : Maximum factor of safety
    - "deflection": Minimum max deflection

Design space: for each material in MATERIALS x each IPE section in the
catalogue, the section is evaluated using THAT material's E and yield
stress (the IPE geometry is treated as a shape that could in principle be
rolled/extruded in any of the four materials -- a simplification that
keeps the search space well-defined and easy to extend; documented to the
user in the CLI banner). Weight is computed from section area x material
density (sections_db.weight_per_metre_for_material), not the CSV's
steel-only weight column, so the comparison is fair across materials.

This module is intentionally decoupled from the CLI -- adding a new
objective only requires adding a key to OBJECTIVE_KEY_FUNCS below.
"""

from design_checks import evaluate_design
from sections_db import weight_per_metre_for_material


def _material_cost_per_metre(weight_per_m, cost_per_kg):
    return weight_per_m * cost_per_kg


# Each objective function takes a candidate dict and returns a sortable
# value where LOWER is always better (maximization objectives are negated).
OBJECTIVE_KEY_FUNCS = {
    "weight":     lambda c: c["weight_per_m"],
    "cost":       lambda c: c["cost_per_m"],
    "safety":     lambda c: -c["result"]["safety_factor"],   # maximize -> negate
    "deflection": lambda c: c["result"]["max_deflection"],
}

OBJECTIVE_LABELS = {
    "weight": "Minimum Weight",
    "cost": "Minimum Material Cost",
    "safety": "Maximum Factor of Safety",
    "deflection": "Minimum Deflection",
}


def optimize_design(beam_type, loads, L, materials_db, ipe_sections,
                     objective="weight", deflection_limit_key="L/360",
                     min_safety_factor=1.5, n=300):
    """
    Search every (material, section) combination and return the best
    candidate satisfying all constraints, per the chosen objective.

    Parameters
    ----------
    materials_db : dict from materials.MATERIALS
    ipe_sections  : dict from sections_db.load_ipe_sections()
    objective     : one of OBJECTIVE_KEY_FUNCS keys

    Returns
    -------
    dict with keys: material, section_name, weight_per_m, cost_per_m,
    result (full evaluate_design() dict), objective, n_feasible, n_total
    or None if no combination satisfies the constraints.
    """
    if objective not in OBJECTIVE_KEY_FUNCS:
        raise ValueError(f"Unknown objective '{objective}'. Choose from {list(OBJECTIVE_KEY_FUNCS)}")

    candidates = []
    n_total = 0

    for material_name, mat_props in materials_db.items():
        E = mat_props["E"]
        yield_stress = mat_props["yield"]
        density = mat_props["density"]
        cost_per_kg = mat_props["cost_per_kg"]

        for section_name, sec_props in ipe_sections.items():
            n_total += 1
            result = evaluate_design(
                beam_type, loads, L, E, sec_props["I"], sec_props["Z"], yield_stress,
                deflection_limit_key=deflection_limit_key,
                min_safety_factor=min_safety_factor, n=n
            )
            if not result["overall_pass"]:
                continue

            weight_per_m = weight_per_metre_for_material(sec_props, density)
            cost_per_m = _material_cost_per_metre(weight_per_m, cost_per_kg)

            candidates.append({
                "material": material_name,
                "section_name": section_name,
                "weight_per_m": weight_per_m,
                "cost_per_m": cost_per_m,
                "result": result,
            })

    if not candidates:
        return None

    key_func = OBJECTIVE_KEY_FUNCS[objective]
    best = min(candidates, key=key_func)
    best["objective"] = objective
    best["objective_label"] = OBJECTIVE_LABELS[objective]
    best["n_feasible"] = len(candidates)
    best["n_total"] = n_total
    return best
