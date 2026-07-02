"""
beam_analyzer.py
=================
Structural Beam Analysis & Design Toolkit
-------------------------------------------
A lightweight engineering design assistant built on top of classical
beam theory. Beams are configured interactively by placing supports
(Fixed, Pin, Roller) rather than picking a beam-type label -- the
configuration is then classified into one of the solver's three internal
beam types (Simply Supported, Cantilever, Fixed-Fixed). Supports multiple
simultaneous loads, an IPE steel section database, automatic section
recommendation, serviceability checks, an intelligent missing-parameter
solver, multi-objective design optimization, and an engineering design
advisor for failing designs.

Run: python beam_analyzer.py
"""

from materials import MATERIALS, PRESET_SECTIONS, rectangular_section, circular_section
from sections_db import load_ipe_sections
from design_checks import evaluate_design, recommend_section
from missing_param_solver import (
    solve_max_allowable_load, solve_max_span, solve_best_material, solve_best_section
)
from plotting import plot_results
from optimizer import optimize_design, OBJECTIVE_LABELS
from design_advisor import generate_recommendations, format_advisor_report
from beam_config import (
    collect_supports, classify_supports, print_configuration_summary,
    UnsupportedConfigurationError
)


# ───────────────────────────── Input helpers ──────────────────────────────
def ask_float(prompt, allow_blank=False):
    """Prompt for a float. If allow_blank, an empty input returns None."""
    raw = input(prompt).strip()
    if allow_blank and raw == "":
        return None
    return float(raw)


def choose_from_list(prompt, options):
    print(prompt)
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    idx = int(input(f"Choose [1-{len(options)}]: ").strip())
    return options[idx - 1]


def collect_loads(L, allow_blank_magnitude=False):
    """
    Collect multiple point loads and/or UDLs from the user.
    If allow_blank_magnitude is True, the user may leave ONE load's
    magnitude blank to signal "solve for max allowable load" mode --
    in that case all loads are treated as unit-reference loads.
    """
    loads = []
    blank_magnitude_used = False

    print("\n--- Load Definition ---")
    print("You can add multiple loads. Enter 'done' when finished.\n")

    while True:
        choice = input("Add a load - [P]oint load, [U]DL, or [done]: ").strip().lower()
        if choice == "done":
            if not loads:
                print("⚠ You must add at least one load.")
                continue
            break

        if choice in ("p", "point"):
            mag_raw = input("  Point load magnitude (kN) [blank = solve for max allowable]: ").strip()
            if mag_raw == "":
                if not allow_blank_magnitude or blank_magnitude_used:
                    print("  ⚠ Blank magnitude not allowed here, or already used. Enter a value.")
                    continue
                P_ref = 1000.0  # 1 kN reference unit; solver will scale this
                blank_magnitude_used = True
            else:
                P_ref = float(mag_raw) * 1000

            a = ask_float(f"  Position from left support (0 to {L} m): ")
            loads.append({"type": "point", "P": P_ref, "a": a,
                          "_is_reference": mag_raw == ""})

        elif choice in ("u", "udl"):
            mag_raw = input("  UDL intensity (kN/m) [blank = solve for max allowable]: ").strip()
            if mag_raw == "":
                if not allow_blank_magnitude or blank_magnitude_used:
                    print("  ⚠ Blank magnitude not allowed here, or already used. Enter a value.")
                    continue
                w_ref = 1000.0  # 1 kN/m reference unit
                blank_magnitude_used = True
            else:
                w_ref = float(mag_raw) * 1000

            span_choice = input("  Full span UDL? [y/n]: ").strip().lower()
            if span_choice == "y":
                start, end = 0, L
            else:
                start = ask_float("    Start position (m): ")
                end = ask_float("    End position (m): ")
            loads.append({"type": "udl", "w": w_ref, "start": start, "end": end,
                          "_is_reference": mag_raw == ""})
        else:
            print("  Please enter 'P', 'U', or 'done'.")

    return loads, blank_magnitude_used


def configure_beam(L):
    """
    Run the interactive support-definition workflow and classify the result
    into one of the solver's internal beam types. Returns (beam_type, supports)
    or raises UnsupportedConfigurationError if the user declines to retry
    after an invalid configuration.
    """
    return collect_supports(L, ask_float, choose_from_list)


def choose_section(ipe_sections):
    """Manual section selection: choose IPE catalogue section or preset rectangular/circular."""
    print("\nSection source:")
    source = choose_from_list("", ["IPE (steel catalogue)", "Rectangular / Circular (custom)"])

    if source.startswith("IPE"):
        names = list(ipe_sections.keys())
        name = choose_from_list("\nChoose IPE section:", names)
        props = ipe_sections[name]
        return name, props["I"], props["Z"]
    else:
        shape = choose_from_list("\nShape:", ["Rectangular", "Circular"])
        if shape == "Rectangular":
            w = ask_float("  Width (m): ")
            h = ask_float("  Height (m): ")
            props = rectangular_section(w, h)
            name = f"Rectangular ({w*1000:.0f}x{h*1000:.0f}mm)"
        else:
            d = ask_float("  Diameter (m): ")
            props = circular_section(d)
            name = f"Circular (d={d*1000:.0f}mm)"
        return name, props["I"], props["Z"]


# ───────────────────────────── Report printing ──────────────────────────────
def print_result_report(result, section_name, material_name):
    print("\n" + "=" * 52)
    print("           ANALYSIS RESULTS")
    print("=" * 52)
    print(f"  Section            : {section_name}")
    print(f"  Material           : {material_name}")
    print(f"  Max Shear Force    : {result['max_shear']/1000:.3f} kN")
    print(f"  Max Bending Moment : {result['max_moment']/1000:.3f} kN·m")
    print(f"  Max Deflection     : {result['max_deflection']*1000:.4f} mm")
    print(f"  Allowable Defl.    : {result['allowable_deflection']*1000:.4f} mm "
          f"({result['deflection_limit_key']})")
    print(f"  Max Bending Stress : {result['max_stress']/1e6:.2f} MPa")
    print(f"  Safety Factor      : {result['safety_factor']:.2f}")
    print("-" * 52)
    print(f"  Stress Check       : {'PASS ✓' if result['stress_pass'] else 'FAIL ✗'}")
    print(f"  Deflection Check   : {'PASS ✓' if result['deflection_pass'] else 'FAIL ✗'}")
    print(f"  Overall Design     : {'PASS ✓' if result['overall_pass'] else 'FAIL ✗'}")
    if result.get("used_numerical_integration"):
        print("  Note: partial-span UDL deflection computed via numerical")
        print("        integration (closed-form used wherever possible).")
    print("=" * 52)


def maybe_run_advisor(result, beam_type, loads, L, E, yield_stress, section_name, ipe_sections,
                       deflection_limit_key="L/360", min_safety_factor=1.5):
    """
    If the design FAILED, automatically run the Design Advisor and print its
    report. Does nothing if the design passed. Silently skips advisor logic
    for custom (non-IPE) sections, since recommendations like 'next larger
    section' rely on the IPE catalogue.
    """
    if result["overall_pass"]:
        return
    if section_name not in ipe_sections:
        print("\n⚠ Design failed, but advisor recommendations are only available for IPE "
              "catalogue sections (not custom rectangular/circular sections).")
        return

    diagnosis, recommendations = generate_recommendations(
        beam_type, loads, L, E, yield_stress, section_name, ipe_sections, result,
        deflection_limit_key=deflection_limit_key, min_safety_factor=min_safety_factor
    )
    print("\n" + format_advisor_report(diagnosis, recommendations, section_name))


# ───────────────────────────── Mode: Standard Analysis ──────────────────────
def run_standard_analysis(ipe_sections):
    L = ask_float("\nBeam Length (m): ")
    try:
        beam_type, supports = configure_beam(L)
    except UnsupportedConfigurationError:
        print("\nReturning to main menu.")
        return

    loads, _ = collect_loads(L, allow_blank_magnitude=False)
    deflection_limit_key = choose_from_list("\nServiceability limit:", ["L/360", "L/250"])
    mode = choose_from_list("\nSection selection:", ["Manual", "Automatic (recommend lightest)"])

    if mode == "Manual":
        material_name = choose_from_list("\nMaterial:", list(MATERIALS.keys()))
        E = MATERIALS[material_name]["E"]
        yield_stress = MATERIALS[material_name]["yield"]
        section_name, I, Z = choose_section(ipe_sections)

        print_configuration_summary(L, supports, loads, material_name, section_name,
                                     analysis_mode="Manual Section Check")

        result = evaluate_design(beam_type, loads, L, E, I, Z, yield_stress,
                                  deflection_limit_key=deflection_limit_key)
        print_result_report(result, section_name, material_name)
        maybe_run_advisor(result, beam_type, loads, L, E, yield_stress, section_name,
                          ipe_sections, deflection_limit_key)
        plot_results(result, beam_type, loads, L, material_name, section_name, yield_stress)

    else:
        material_name = choose_from_list("\nMaterial (for automatic section search):", ["Steel"])
        E = MATERIALS[material_name]["E"]
        yield_stress = MATERIALS[material_name]["yield"]

        print_configuration_summary(L, supports, loads, material_name, "(auto)",
                                     analysis_mode="Automatic Section Optimization")

        print("\n⏳ Searching IPE database for lightest adequate section...")
        section_name, result = recommend_section(beam_type, loads, L, E, yield_stress,
                                                   ipe_sections, deflection_limit_key=deflection_limit_key)
        if section_name is None:
            print("\n❌ No IPE section in the database satisfies stress and deflection "
                  "requirements for this span/load. Consider a larger beam length range, "
                  "reduced load, or a custom section.")
            # Run the advisor against the heaviest/strongest catalogue section so the
            # user still gets actionable guidance (e.g. reduce span, reduce load).
            heaviest_name = max(ipe_sections, key=lambda n: ipe_sections[n]["weight"])
            heaviest_props = ipe_sections[heaviest_name]
            fallback_result = evaluate_design(beam_type, loads, L, E, heaviest_props["I"],
                                              heaviest_props["Z"], yield_stress,
                                              deflection_limit_key=deflection_limit_key)
            print(f"\n(Diagnostics below use {heaviest_name}, the largest available section, "
                  f"as a reference point.)")
            maybe_run_advisor(fallback_result, beam_type, loads, L, E, yield_stress,
                              heaviest_name, ipe_sections, deflection_limit_key)
            return

        weight = ipe_sections[section_name]["weight"]
        print(f"\n✅ Recommended Section : {section_name}")
        print(f"   Weight per metre    : {weight:.1f} kg/m")
        print_result_report(result, section_name, material_name)
        plot_results(result, beam_type, loads, L, material_name, section_name, yield_stress)


def collect_supports_relative():
    """
    Variant of configure_beam() used when beam length L is itself the
    unknown parameter being solved for. Supports are entered as fractions
    of the (yet-unknown) span (0 to 1) rather than absolute metres, then
    classified using a unit span (L=1) -- classification only depends on
    support TYPES and relative ordering/distinctness, not absolute scale.

    Returns (beam_type, supports_as_fractions).
    """
    while True:
        supports = []
        print("\n--- Support Definition (length unknown -- use fractions of span) ---")
        print("Define supports as a FRACTION of the span (0 = left end, 1 = right end).")
        print("Valid configurations: Pin+Roller (Simply Supported), single Fixed")
        print("(Cantilever), or Fixed+Fixed (Fixed-Fixed). Enter 'done' when finished.\n")

        while True:
            choice = input(
                f"Add a support - [F]ixed, [P]in, [R]oller, or [done] "
                f"({len(supports)} added so far): "
            ).strip().lower()
            if choice == "done":
                break
            elif choice in ("f", "fixed"):
                stype = "Fixed"
            elif choice in ("p", "pin"):
                stype = "Pin"
            elif choice in ("r", "roller"):
                stype = "Roller"
            else:
                print("  Please enter 'F', 'P', 'R', or 'done'.")
                continue
            frac = ask_float(f"  Position of {stype} support as fraction of span (0 to 1): ")
            supports.append({"type": stype, "position": frac})

        try:
            beam_type = classify_supports(supports, L=1.0)
        except UnsupportedConfigurationError as e:
            print(f"\n❌ Invalid support configuration:\n   {e}\n")
            retry = input("Try defining supports again? [y/n]: ").strip().lower()
            if retry == "y":
                continue
            else:
                raise

        supports = sorted(supports, key=lambda s: s["position"])
        print(f"\n✅ Recognized configuration: {beam_type}")
        return beam_type, supports


# ───────────────────────────── Mode: Missing-Parameter Solver ──────────────
def run_missing_parameter_solver(ipe_sections):
    print("\n--- Intelligent Missing-Parameter Solver ---")
    print("Leave EXACTLY ONE of the following blank: Length, Section, Material, Load Magnitude.")

    L_raw = input("\nBeam Length (m) [blank if unknown]: ").strip()
    L = float(L_raw) if L_raw != "" else None

    if L is not None:
        try:
            beam_type, supports = configure_beam(L)
        except UnsupportedConfigurationError:
            print("\nReturning to main menu.")
            return
    else:
        try:
            beam_type, supports = collect_supports_relative()
        except UnsupportedConfigurationError:
            print("\nReturning to main menu.")
            return

    print("\nMaterial:")
    mat_raw = input("Material name (Steel/Aluminium/Concrete/Timber) [blank if unknown]: ").strip()
    material_name = mat_raw if mat_raw != "" else None
    if material_name and material_name not in MATERIALS:
        print(f"❌ Unknown material '{material_name}'. Must be one of {list(MATERIALS.keys())}.")
        return

    section_raw = input("IPE Section name (e.g. IPE200) [blank if unknown]: ").strip()
    section_name = section_raw if section_raw != "" else None
    if section_name and section_name not in ipe_sections:
        print(f"❌ Unknown section '{section_name}'.")
        return

    # For the missing-parameter mode we restrict to ONE load (point or UDL)
    # since solving simultaneously for an unknown load AND multiple fixed
    # loads is ambiguous -- this constraint is documented to the user.
    print("\nDefine the single governing load (this mode supports one load at a time):")
    load_kind = choose_from_list("", ["Point Load", "UDL"])

    if load_kind == "Point Load":
        mag_raw = input("  Point load magnitude (kN) [blank if unknown]: ").strip()
        P = float(mag_raw) * 1000 if mag_raw != "" else None
        if L is not None:
            a = ask_float(f"  Position from left support (0 to {L} m): ")
            rel_pos = a / L
        else:
            rel_frac = ask_float("  Position as a FRACTION of span (0 to 1, e.g. 0.5 for midspan): ")
            rel_pos = rel_frac
            a = None
        base_load = {"type": "point", "P": P if P is not None else 1000.0,
                     "a": a if a is not None else 0.0, "_relative_position": rel_pos}
    else:
        mag_raw = input("  UDL intensity (kN/m) [blank if unknown]: ").strip()
        w = float(mag_raw) * 1000 if mag_raw != "" else None
        base_load = {"type": "udl", "w": w if w is not None else 1000.0, "start": 0, "end": L if L else 1.0}

    unknowns = []
    if L is None:
        unknowns.append("length")
    if material_name is None:
        unknowns.append("material")
    if section_name is None:
        unknowns.append("section")
    if mag_raw == "":
        unknowns.append("load")

    if len(unknowns) == 0:
        print("\n⚠ All parameters are specified -- nothing to solve. "
              "Use Standard Analysis mode instead.")
        return
    if len(unknowns) > 1:
        print(f"\n❌ ERROR: {len(unknowns)} parameters are missing ({', '.join(unknowns)}). "
              "Only ONE parameter may be left blank at a time. Please re-run and specify all "
              "but one parameter.")
        return

    missing = unknowns[0]
    deflection_limit_key = "L/360"
    min_sf = 1.5

    # Resolve known I, Z, E, yield_stress where applicable
    if section_name:
        I, Z = ipe_sections[section_name]["I"], ipe_sections[section_name]["Z"]
    if material_name:
        E, yield_stress = MATERIALS[material_name]["E"], MATERIALS[material_name]["yield"]

    # Configuration summary (placeholders shown for whichever field is being solved for)
    if L is not None:
        print_configuration_summary(
            L, supports, [base_load],
            material_name if material_name else "(solving for this)",
            section_name if section_name else "(solving for this)",
            analysis_mode=f"Missing-Parameter Solver -- solving for {missing.upper()}"
        )
    else:
        print("\n" + "-" * 38)
        print("BEAM CONFIGURATION")
        print("Length : (solving for this)")
        print(f"Beam Type : {beam_type}")
        print("Supports (as fraction of span)")
        for s in supports:
            print(f"  • {s['type']} @ {s['position']:.2f} x span")
        print(f"Load : {'Point' if base_load['type']=='point' else 'UDL'} "
              f"{'(solving for this)' if missing == 'load' else ''}")
        print(f"Material : {material_name if material_name else '(solving for this)'}")
        print(f"Section : {section_name if section_name else '(solving for this)'}")
        print(f"Analysis Mode : Missing-Parameter Solver -- solving for {missing.upper()}")
        print("-" * 38)

    print(f"\n🔍 Missing parameter detected: '{missing.upper()}'")
    print("⏳ Solving iteratively for the safest feasible value...\n")

    if missing == "load":
        result = solve_max_allowable_load(beam_type, [base_load], L, E, I, Z, yield_stress,
                                           deflection_limit_key, min_sf)
        if "solved_factor" in result:
            solved_loads = result["solved_loads"]
            magnitude = solved_loads[0]["P"]/1000 if base_load["type"] == "point" else solved_loads[0]["w"]/1000
            unit = "kN" if base_load["type"] == "point" else "kN/m"
            print(f"✅ Maximum Allowable Load: {magnitude:.3f} {unit}")
            print_result_report(result, section_name, material_name)
            plot_results(result, beam_type, solved_loads, L, material_name, section_name, yield_stress)
        else:
            print("❌ Could not find a feasible load (design fails even with negligible load).")

    elif missing == "length":
        result = solve_max_span(beam_type, [base_load], E, I, Z, yield_stress,
                                deflection_limit_key, min_sf)
        if result.get("feasible"):
            print(f"✅ Maximum Permissible Span: {result['solved_length']:.3f} m")
            print_result_report(result, section_name, material_name)
            plot_results(result, beam_type, result["solved_loads"], result["solved_length"],
                        material_name, section_name, yield_stress)
        else:
            print(f"❌ {result['message']}")

    elif missing == "section":
        result_dict = solve_best_section(beam_type, [base_load], L, E, yield_stress,
                                         ipe_sections, deflection_limit_key, min_sf)
        if result_dict["section_name"]:
            name = result_dict["section_name"]
            result = result_dict["result"]
            weight = ipe_sections[name]["weight"]
            print(f"✅ Recommended Section: {name} ({weight:.1f} kg/m)")
            print_result_report(result, name, material_name)
            plot_results(result, beam_type, [base_load], L, material_name, name, yield_stress)
        else:
            print(f"❌ {result_dict['message']}")

    elif missing == "material":
        result_dict = solve_best_material(beam_type, [base_load], L, I, Z,
                                          deflection_limit_key, min_sf)
        if result_dict["material_name"]:
            name = result_dict["material_name"]
            result = result_dict["result"]
            print(f"✅ Recommended Material: {name}")
            print_result_report(result, section_name, name)
            plot_results(result, beam_type, [base_load], L, name, section_name, MATERIALS[name]["yield"])
        else:
            print(f"❌ {result_dict['message']}")


# ───────────────────────────── Mode: Design Optimization ──────────────────
def run_design_optimization(ipe_sections):
    print("\n--- Multi-Objective Design Optimization ---")
    print("Searches every (material x IPE section) combination and returns the")
    print("best design for your chosen objective, subject to stress, safety")
    print("factor, and serviceability constraints.\n")
    print("Note: each IPE section's geometry is evaluated using each material's own")
    print("E, yield strength, and density -- modeling 'what if this shape were made")
    print("of X instead of steel', which keeps the search space well-defined.\n")

    L = ask_float("\nBeam Length (m): ")
    try:
        beam_type, supports = configure_beam(L)
    except UnsupportedConfigurationError:
        print("\nReturning to main menu.")
        return

    loads, _ = collect_loads(L, allow_blank_magnitude=False)
    deflection_limit_key = choose_from_list("\nServiceability limit:", ["L/360", "L/250"])

    objective_choice = choose_from_list(
        "\nOptimization Objective:",
        ["Minimum Weight", "Minimum Material Cost", "Maximum Factor of Safety", "Minimum Deflection"]
    )
    objective_map = {
        "Minimum Weight": "weight",
        "Minimum Material Cost": "cost",
        "Maximum Factor of Safety": "safety",
        "Minimum Deflection": "deflection",
    }
    objective = objective_map[objective_choice]

    print_configuration_summary(L, supports, loads, "(optimizing)", "(optimizing)",
                                 analysis_mode=f"Design Optimization -- {objective_choice}")

    print(f"\n⏳ Evaluating all material x section combinations for: {objective_choice}...")
    best = optimize_design(beam_type, loads, L, MATERIALS, ipe_sections,
                           objective=objective, deflection_limit_key=deflection_limit_key)

    if best is None:
        print("\n❌ No (material, section) combination in the database satisfies the "
              "engineering constraints for this span/load. Consider a shorter span, "
              "a lighter load, or relaxing the serviceability limit (e.g. L/250).")
        return

    result = best["result"]
    print(f"\n✅ OPTIMIZED DESIGN  (Objective: {best['objective_label']})")
    print("=" * 52)
    print(f"  Selected Material      : {best['material']}")
    print(f"  Recommended Section    : {best['section_name']}")
    print(f"  Weight per metre       : {best['weight_per_m']:.2f} kg/m")
    print(f"  Estimated Material Cost: ${best['cost_per_m']:.2f} per metre")
    print(f"  Max Stress             : {result['max_stress']/1e6:.2f} MPa")
    print(f"  Max Deflection         : {result['max_deflection']*1000:.4f} mm")
    print(f"  Factor of Safety       : {result['safety_factor']:.2f}")
    print(f"  Optimization Objective : {best['objective_label']}")
    print(f"  Overall Design Status  : {'PASS ✓' if result['overall_pass'] else 'FAIL ✗'}")
    print(f"  (Searched {best['n_total']} combinations, {best['n_feasible']} were feasible)")
    print("=" * 52)

    E = MATERIALS[best["material"]]["E"]
    yield_stress = MATERIALS[best["material"]]["yield"]
    plot_results(result, beam_type, loads, L, best["material"], best["section_name"], yield_stress)


# ───────────────────────────── Main entry point ──────────────────────────────
def main():
    print("=" * 56)
    print("   STRUCTURAL BEAM ANALYSIS & DESIGN TOOLKIT  v4.0")
    print("=" * 56)

    ipe_sections = load_ipe_sections()

    mode = choose_from_list(
        "\nSelect Mode:",
        ["Standard Analysis (multi-load, manual/auto section)",
         "Intelligent Missing-Parameter Solver",
         "Multi-Objective Design Optimization"]
    )

    if mode.startswith("Standard"):
        run_standard_analysis(ipe_sections)
    elif mode.startswith("Intelligent"):
        run_missing_parameter_solver(ipe_sections)
    else:
        run_design_optimization(ipe_sections)


if __name__ == "__main__":
    main()
