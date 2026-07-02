"""
beam_config.py
================
Interactive Beam Configuration.

Replaces the old "pick Simply Supported / Cantilever / Fixed-Fixed from a
list" interface with a structural-modelling-style workflow: the user places
supports (Fixed, Pin, Roller) at specific locations along the beam, and the
program classifies the resulting configuration into one of the THREE
internal beam types the existing solver already understands.

This module deliberately does NOT attempt to solve arbitrary or statically
indeterminate support arrangements -- the underlying beam_solver.py only
contains closed-form solutions for Simply Supported, Cantilever, and
Fixed-Fixed beams, so only support combinations that map cleanly onto one
of those three are accepted. Anything else is rejected with a clear
engineering explanation (see classify_supports()).

Valid mappings:
    Pin @ a  +  Roller @ b   (a != b)         -> Simply Supported
    Single Fixed @ a                          -> Cantilever
    Fixed @ a  +  Fixed @ b   (a != b)         -> Fixed-Fixed

Everything else (no supports, 3+ supports, Pin+Pin, Roller+Roller,
Fixed+Pin, Fixed+Roller, a single Pin or Roller, etc.) is rejected.
"""

SUPPORT_TYPES = ["Fixed", "Pin", "Roller"]


class UnsupportedConfigurationError(Exception):
    """Raised when the entered supports don't map to a solvable beam type."""
    pass


def classify_supports(supports, L, tol=1e-9):
    """
    Classify a list of supports into one of the solver's three internal
    beam types, or raise UnsupportedConfigurationError with an explanation.

    Parameters
    ----------
    supports : list of dicts {"type": "Fixed"|"Pin"|"Roller", "position": float}
    L : beam length (m), used only to validate support positions are on-beam

    Returns
    -------
    beam_type : str -> "Simply Supported" | "Cantilever" | "Fixed-Fixed"
    """
    n = len(supports)

    # --- Basic position validation ---
    for s in supports:
        if not (-tol <= s["position"] <= L + tol):
            raise UnsupportedConfigurationError(
                f"Support position {s['position']} m is outside the beam length (0 to {L} m)."
            )

    if n == 0:
        raise UnsupportedConfigurationError(
            "No supports were defined. A beam needs at least one support "
            "(a single Fixed support for a cantilever, or two supports for "
            "a simply supported / fixed-fixed beam)."
        )

    types = [s["type"] for s in supports]
    positions = [s["position"] for s in supports]

    # --- Single support: only a single Fixed support is solvable (Cantilever) ---
    if n == 1:
        if types[0] == "Fixed":
            return "Cantilever"
        raise UnsupportedConfigurationError(
            f"A single {types[0]} support cannot hold a beam in equilibrium on its own "
            f"(it cannot resist rotation). A single-support beam is only solvable here "
            f"if that support is Fixed (-> Cantilever). Add a second support, or change "
            f"this support to Fixed."
        )

    # --- Two supports: check for duplicate positions ---
    if n == 2:
        if abs(positions[0] - positions[1]) < tol:
            raise UnsupportedConfigurationError(
                "Both supports are at the same position -- a beam needs supports at "
                "two distinct locations (or a single Fixed support for a cantilever)."
            )

        type_set = set(types)

        # Pin + Roller -> Simply Supported (order-independent)
        if type_set == {"Pin", "Roller"}:
            return "Simply Supported"

        # Fixed + Fixed -> Fixed-Fixed
        if type_set == {"Fixed"}:
            return "Fixed-Fixed"

        # Anything else with 2 supports is statically indeterminate or
        # under-constrained for this toolkit's closed-form solver set.
        readable = " + ".join(types)
        raise UnsupportedConfigurationError(
            f"The combination '{readable}' is not supported by this toolkit's solver. "
            f"Only Pin + Roller (Simply Supported) or Fixed + Fixed (Fixed-Fixed) are "
            f"solvable with the available closed-form equations. Configurations such as "
            f"Fixed + Pin or Fixed + Roller are statically indeterminate in a way this "
            f"toolkit does not model, and Pin + Pin / Roller + Roller leave the beam "
            f"unable to resist horizontal thrust or rotation as modelled here."
        )

    # --- Three or more supports: always rejected (statically indeterminate / overconstrained) ---
    raise UnsupportedConfigurationError(
        f"{n} supports were defined. This toolkit only solves beams with ONE support "
        f"(Fixed -> Cantilever) or TWO supports (Pin+Roller -> Simply Supported, or "
        f"Fixed+Fixed -> Fixed-Fixed). Continuous/multi-span beams with 3+ supports are "
        f"statically indeterminate and are not modelled here."
    )


def collect_supports(L, ask_float, choose_from_list):
    """
    Interactively collect supports from the user and classify them.
    Re-prompts on invalid configurations (without restarting the whole
    beam definition) until a valid configuration is entered or the user
    gives up.

    `ask_float` and `choose_from_list` are passed in from the caller (the
    CLI module) so this function has no direct dependency on the rest of
    the CLI's input-handling implementation.

    Returns
    -------
    (beam_type, supports) on success
    """
    while True:
        supports = []
        print("\n--- Support Definition ---")
        print("Define the beam's supports (Fixed, Pin, or Roller) and their positions.")
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

            pos = ask_float(f"  Position of {stype} support (0 to {L} m): ")
            supports.append({"type": stype, "position": pos})

        try:
            beam_type = classify_supports(supports, L)
        except UnsupportedConfigurationError as e:
            print(f"\n❌ Invalid support configuration:\n   {e}\n")
            retry = input("Try defining supports again? [y/n]: ").strip().lower()
            if retry == "y":
                continue
            else:
                raise

        # Sort supports by position for clean display purposes downstream
        supports = sorted(supports, key=lambda s: s["position"])
        print(f"\n✅ Recognized configuration: {beam_type}")
        return beam_type, supports


def format_supports(supports):
    """Human-readable list of supports, one per line, for the config summary."""
    lines = []
    for s in supports:
        lines.append(f"  • {s['type']} @ {s['position']:.1f} m")
    return "\n".join(lines)


def format_loads(loads):
    """Human-readable list of loads, one per line, for the config summary."""
    lines = []
    for load in loads:
        if load["type"] == "point":
            lines.append(f"  • Point Load {load['P']/1000:.1f} kN @ {load['a']:.1f} m")
        else:
            lines.append(f"  • UDL {load['w']/1000:.2f} kN/m from {load['start']:.1f}\u2013{load['end']:.1f} m")
    return "\n".join(lines)


def print_configuration_summary(L, supports, loads, material_name, section_name, analysis_mode):
    """
    Print the full "Beam Configuration Summary" block shown before running
    any analysis, matching the structural-modelling-software feel requested.
    """
    print("\n" + "-" * 38)
    print("BEAM CONFIGURATION")
    print(f"Length : {L:.1f} m")
    print("Supports")
    print(format_supports(supports))
    print("Loads")
    print(format_loads(loads))
    print(f"Material : {material_name}")
    print(f"Section : {section_name}")
    print(f"Analysis Mode : {analysis_mode}")
    print("-" * 38)
