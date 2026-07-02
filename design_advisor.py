"""
design_advisor.py
===================
Intelligent Engineering Design Advisor.

Given a FAILING evaluate_design() result, this module explains WHY it
failed (with quantified percentage over-stress / over-deflection) and
generates ranked, calculation-based improvement recommendations rather
than fixed canned messages.

Each recommendation is derived from an actual re-run of the solver (e.g.
"next larger section" is found by walking the real IPE catalogue and
testing it; "maximum permissible span" is found via bisection against the
real constraints) so that the advice is always consistent with the
toolkit's own engineering model.
"""

from design_checks import evaluate_design
from missing_param_solver import solve_max_span, solve_max_allowable_load, solve_best_material
from sections_db import sections_sorted_by_weight


def _percent_over(value, limit):
    """Return how far `value` exceeds `limit`, as a percentage of the limit."""
    if limit == 0:
        return float("inf")
    return max(0.0, (value - limit) / limit * 100)


def diagnose(result, min_safety_factor=1.5):
    """
    Build a structured diagnosis of WHY a design failed.

    Returns dict:
        {
          "stress_fail": bool, "stress_over_pct": float,
          "deflection_fail": bool, "deflection_over_pct": float,
          "both_fail": bool,
        }
    """
    sf = result["safety_factor"]
    required_stress_capacity = result["max_stress"] * (min_safety_factor / sf) if sf > 0 else float("inf")
    # Equivalent: how much stress would need to drop to hit the safety factor target
    stress_over_pct = _percent_over(min_safety_factor, sf) if sf < min_safety_factor else 0.0

    deflection_over_pct = _percent_over(result["max_deflection"], result["allowable_deflection"])

    return {
        "stress_fail": not result["stress_pass"],
        "stress_over_pct": stress_over_pct,
        "deflection_fail": not result["deflection_pass"],
        "deflection_over_pct": deflection_over_pct,
        "both_fail": (not result["stress_pass"]) and (not result["deflection_pass"]),
    }


def _find_next_larger_section(current_section_name, ipe_sections):
    """Return the name of the next heavier IPE section in the catalogue, or None."""
    ordered = sections_sorted_by_weight(ipe_sections)
    names = [name for name, _ in ordered]
    if current_section_name not in names:
        return None
    idx = names.index(current_section_name)
    if idx + 1 < len(names):
        return names[idx + 1]
    return None


def _try_section_upgrade(beam_type, loads, L, E, yield_stress, current_section_name,
                          ipe_sections, deflection_limit_key, min_safety_factor):
    """Test whether upgrading to the next larger IPE section fixes the design."""
    next_name = _find_next_larger_section(current_section_name, ipe_sections)
    if next_name is None:
        return None
    props = ipe_sections[next_name]
    result = evaluate_design(beam_type, loads, L, E, props["I"], props["Z"], yield_stress,
                              deflection_limit_key, min_safety_factor)
    return {"section_name": next_name, "result": result}


def generate_recommendations(beam_type, loads, L, E, yield_stress, current_section_name,
                              ipe_sections, result, deflection_limit_key="L/360",
                              min_safety_factor=1.5):
    """
    Generate a ranked list of engineering recommendations for a FAILING design.

    Each recommendation is a dict:
        {"text": str, "fixes_design": bool, "rank_score": float}
    Lower rank_score = more effective (tested first / sorted ascending).

    Returns
    -------
    diagnosis : dict from diagnose()
    recommendations : list of recommendation dicts, sorted by effectiveness
    """
    diagnosis = diagnose(result, min_safety_factor)
    recommendations = []

    if not (diagnosis["stress_fail"] or diagnosis["deflection_fail"]):
        return diagnosis, recommendations  # design actually passes; nothing to recommend

    # --- Recommendation A: upgrade to next larger section ---
    upgrade = _try_section_upgrade(beam_type, loads, L, E, yield_stress, current_section_name,
                                    ipe_sections, deflection_limit_key, min_safety_factor)
    if upgrade is not None:
        fixes = upgrade["result"]["overall_pass"]
        recommendations.append({
            "text": f"Upgrade section from {current_section_name} → {upgrade['section_name']}",
            "fixes_design": fixes,
            "rank_score": 0 if fixes else 5,
            "detail": upgrade,
        })

    # --- Recommendation B: reduce span (only meaningful if deflection or stress fails) ---
    # Build a unit-load list preserving relative position of point loads / full-span UDLs
    span_loads = []
    for load in loads:
        new_load = dict(load)
        if load["type"] == "point":
            new_load["_relative_position"] = load["a"] / L if L > 0 else 0.5
        span_loads.append(new_load)

    span_result = solve_max_span(beam_type, span_loads, E,
                                  ipe_sections[current_section_name]["I"],
                                  ipe_sections[current_section_name]["Z"],
                                  yield_stress, deflection_limit_key, min_safety_factor)
    if span_result.get("feasible"):
        max_span = span_result["solved_length"]
        if max_span < L:
            recommendations.append({
                "text": f"Reduce span below {max_span:.2f} m",
                "fixes_design": True,
                "rank_score": 1,
                "detail": span_result,
            })

    # --- Recommendation C: reduce applied load by required percentage ---
    # Use the FIRST load as the scaling reference (dominant load assumption,
    # consistent with missing_param_solver's single-governing-load model)
    if loads:
        ref_load = dict(loads[0])
        load_result = solve_max_allowable_load(
            beam_type, [ref_load], L, E,
            ipe_sections[current_section_name]["I"],
            ipe_sections[current_section_name]["Z"],
            yield_stress, deflection_limit_key, min_safety_factor
        )
        if "solved_factor" in load_result and load_result["solved_factor"] < 1.0:
            pct_reduction = (1 - load_result["solved_factor"]) * 100
            recommendations.append({
                "text": f"Reduce applied load by approximately {pct_reduction:.0f}%",
                "fixes_design": True,
                "rank_score": 2,
                "detail": load_result,
            })

    # --- Recommendation D: switch to a stiffer / stronger material (same section) ---
    mat_result = solve_best_material(beam_type, loads, L,
                                      ipe_sections[current_section_name]["I"],
                                      ipe_sections[current_section_name]["Z"],
                                      deflection_limit_key, min_safety_factor)
    if mat_result["material_name"] is not None:
        recommendations.append({
            "text": f"Use {mat_result['material_name']} instead of the current material "
                    f"(same {current_section_name} section)",
            "fixes_design": True,
            "rank_score": 3,
            "detail": mat_result,
        })

    # --- Recommendation E: generic stress-specific note when stress (not deflection) governs ---
    if diagnosis["stress_fail"] and not diagnosis["deflection_fail"]:
        recommendations.append({
            "text": "Consider a higher-grade steel (e.g. Fe410/Fe345-equivalent yield strength) "
                    "to raise allowable stress without changing section size",
            "fixes_design": None,  # qualitative; not independently re-verified
            "rank_score": 4,
            "detail": None,
        })

    # Sort by effectiveness: fixes_design=True first, then by rank_score ascending
    recommendations.sort(key=lambda r: (r["fixes_design"] is not True, r["rank_score"]))
    return diagnosis, recommendations


def format_advisor_report(diagnosis, recommendations, current_section_name):
    """Build the human-readable advisor report string (matches the spec's example format)."""
    lines = []
    lines.append("-" * 45)
    lines.append("DESIGN STATUS : FAIL")
    lines.append("Reason:")
    if diagnosis["stress_fail"]:
        lines.append(f"  • Stress/safety-factor shortfall: {diagnosis['stress_over_pct']:.0f}% "
                      f"below required safety factor")
    if diagnosis["deflection_fail"]:
        lines.append(f"  • Deflection exceeds limit by {diagnosis['deflection_over_pct']:.0f}%")
    lines.append("")
    if recommendations:
        lines.append("Recommended Improvements:")
        for i, rec in enumerate(recommendations, 1):
            lines.append(f"  {i}. {rec['text']}")
        lines.append("")
        first_fix = next((i for i, r in enumerate(recommendations, 1) if r["fixes_design"]), None)
        if first_fix:
            lines.append(f"Expected Result:")
            lines.append(f"  PASS after Recommendation #{first_fix}")
        else:
            lines.append("Expected Result:")
            lines.append("  No single recommendation alone is confirmed to resolve the failure; "
                          "consider combining improvements above.")
    else:
        lines.append("No automatic recommendations could be generated for this configuration.")
    lines.append("-" * 45)
    return "\n".join(lines)
