"""
missing_param_solver.py
========================
"Design assistant" mode: exactly ONE of {length, section, material, load
magnitude} may be left unknown. This module determines the safest feasible
value for the missing parameter using iterative numerical search, subject to:
    - stress / safety-factor constraint
    - deflection constraint (serviceability)

All searches use simple, transparent BISECTION on a monotonic governing
quantity (deflection and stress both increase monotonically with load
magnitude and with span length, and decrease monotonically with section
stiffness/strength) — appropriate for a single point load or single UDL,
which is the expected use case for this feature. If the beam carries
multiple loads, this feature solves for the missing parameter by scaling
ALL loads of the missing-magnitude type proportionally (point loads and
UDLs scaled together) -- this is documented to the user.

Each public function returns a dict with the solved value plus full
evaluate_design() diagnostics so results can be reported consistently.
"""

from design_checks import evaluate_design
from sections_db import sections_sorted_by_weight
from materials import MATERIALS


def _scale_loads(loads, factor):
    """Return a new loads list with all magnitudes (P or w) scaled by factor."""
    scaled = []
    for load in loads:
        new_load = dict(load)
        if load["type"] == "point":
            new_load["P"] = load["P"] * factor
        elif load["type"] == "udl":
            new_load["w"] = load["w"] * factor
        scaled.append(new_load)
    return scaled


def solve_max_allowable_load(beam_type, base_loads, L, E, I, Z, yield_stress,
                              deflection_limit_key="L/360", min_safety_factor=1.5,
                              max_iterations=60, search_upper_factor=1e6):
    """
    Find the maximum load-scaling factor such that the design still PASSES.
    base_loads should have magnitude 1 unit (e.g. P=1 N, w=1 N/m) per load,
    OR any reference magnitude -- the result is reported as the actual solved
    load magnitude(s), not just a factor.

    Uses bisection: find largest 'factor' for which evaluate_design() passes.
    """
    def passes(factor):
        loads = _scale_loads(base_loads, factor)
        result = evaluate_design(beam_type, loads, L, E, I, Z, yield_stress,
                                  deflection_limit_key, min_safety_factor)
        return result["overall_pass"], result

    # Establish bracket: factor=0 must pass trivially; find an upper bound that fails
    lo, hi = 0.0, 1.0
    ok, _ = passes(hi)
    iterations_to_expand = 0
    while ok and hi < search_upper_factor and iterations_to_expand < 100:
        lo = hi
        hi *= 2
        ok, _ = passes(hi)
        iterations_to_expand += 1

    if ok:
        # Even at the search ceiling, design passes -> essentially unbounded
        loads = _scale_loads(base_loads, hi)
        result = evaluate_design(beam_type, loads, L, E, I, Z, yield_stress,
                                  deflection_limit_key, min_safety_factor)
        result["solved_factor"] = hi
        result["solved_loads"] = loads
        result["note"] = "Search ceiling reached without failure; load capacity is very high relative to beam."
        return result

    # Bisection between lo (passes) and hi (fails)
    for _ in range(max_iterations):
        mid = (lo + hi) / 2
        ok, result = passes(mid)
        if ok:
            lo = mid
        else:
            hi = mid

    final_factor = lo
    loads = _scale_loads(base_loads, final_factor)
    result = evaluate_design(beam_type, loads, L, E, I, Z, yield_stress,
                              deflection_limit_key, min_safety_factor)
    result["solved_factor"] = final_factor
    result["solved_loads"] = loads
    return result


def solve_max_span(beam_type, loads_at_unit_length, E, I, Z, yield_stress,
                    deflection_limit_key="L/360", min_safety_factor=1.5,
                    max_iterations=60, search_upper_length=200.0,
                    min_length=0.1):
    """
    Find the maximum beam length L such that the design still passes,
    given fixed load magnitudes (loads do NOT scale with length here --
    this models a beam carrying fixed point loads / line loads at fixed
    positions/intensity, with span being the unknown).

    NOTE: load positions in `loads_at_unit_length` that depend on L (e.g.
    "midspan") must be passed in as functions of L by the caller; for
    simplicity this solver assumes point load positions scale proportionally
    with L (i.e. relative position is preserved) and UDLs are full-span.
    """
    def build_loads_for_length(L):
        new_loads = []
        for load in loads_at_unit_length:
            new_load = dict(load)
            if load["type"] == "point":
                # preserve relative position (fraction of span)
                rel_pos = load.get("_relative_position", 0.5)
                new_load["a"] = rel_pos * L
            elif load["type"] == "udl":
                # assume full span UDL scales with L automatically
                new_load["start"] = 0
                new_load["end"] = L
            new_loads.append(new_load)
        return new_loads

    def passes(L):
        if L <= 0:
            return False, None
        loads = build_loads_for_length(L)
        result = evaluate_design(beam_type, loads, L, E, I, Z, yield_stress,
                                  deflection_limit_key, min_safety_factor)
        return result["overall_pass"], result

    lo, hi = min_length, min_length
    ok, _ = passes(hi)
    if not ok:
        # Even the minimum length fails -- design is infeasible
        result_fail = passes(min_length)[1]
        return {
            "feasible": False,
            "message": f"Design fails even at minimum span {min_length} m. "
                       f"No feasible length exists with current load/section/material.",
            "diagnostic": result_fail,
        }

    iterations_to_expand = 0
    while ok and hi < search_upper_length and iterations_to_expand < 100:
        lo = hi
        hi *= 1.5 if hi > min_length else 2.0
        if hi < lo + 0.01:
            hi = lo + 0.5
        ok, _ = passes(hi)
        iterations_to_expand += 1

    if ok:
        result = passes(hi)[1]
        result["feasible"] = True
        result["solved_length"] = hi
        result["solved_loads"] = build_loads_for_length(hi)
        result["note"] = "Search ceiling reached without failure; span capacity is very high."
        return result

    for _ in range(max_iterations):
        mid = (lo + hi) / 2
        ok, result = passes(mid)
        if ok:
            lo = mid
        else:
            hi = mid

    final_length = lo
    final_result = passes(final_length)[1]
    final_result["feasible"] = True
    final_result["solved_length"] = final_length
    final_result["solved_loads"] = build_loads_for_length(final_length)
    return final_result


def solve_best_material(beam_type, loads, L, I, Z,
                         deflection_limit_key="L/360", min_safety_factor=1.5):
    """
    Try every material in the database and return the lightest-density
    material that satisfies the stress and deflection constraints for the
    GIVEN fixed cross-section (I, Z fixed -- only E and yield_stress vary
    by material). This models "what's the most suitable / lightest material
    for this already-chosen section?"

    Returns dict: {material_name, result, all_results} or
                  {material_name: None, message} if none pass.
    """
    all_results = {}
    passing = []

    for name, props in MATERIALS.items():
        result = evaluate_design(beam_type, loads, L, props["E"], I, Z,
                                  props["yield"], deflection_limit_key, min_safety_factor)
        result["material"] = name
        result["density"] = props["density"]
        all_results[name] = result
        if result["overall_pass"]:
            passing.append((name, result))

    if not passing:
        return {
            "material_name": None,
            "message": "No material in the database satisfies the constraints for this section/span/load.",
            "all_results": all_results,
        }

    # Recommend lightest (by density) among passing materials -- proxy for most efficient/suitable
    passing.sort(key=lambda kv: kv[1]["density"])
    best_name, best_result = passing[0]
    return {
        "material_name": best_name,
        "result": best_result,
        "all_results": all_results,
    }


def solve_best_section(beam_type, loads, L, E, yield_stress, ipe_sections,
                        deflection_limit_key="L/360", min_safety_factor=1.5):
    """
    Thin wrapper -- recommend the lightest IPE section that passes.
    Re-exposed here for interface consistency with the other "solve_*"
    functions used by the missing-parameter dispatcher.
    """
    from design_checks import recommend_section
    name, result = recommend_section(beam_type, loads, L, E, yield_stress, ipe_sections,
                                      deflection_limit_key, min_safety_factor)
    if name is None:
        return {
            "section_name": None,
            "message": "No section in the IPE database satisfies the constraints for this span/load/material.",
        }
    return {"section_name": name, "result": result}
