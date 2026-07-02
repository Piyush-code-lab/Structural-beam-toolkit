"""
plotting.py
============
Preserves the original dark-mode Matplotlib plotting style from the v1
Beam Deflection Analyzer, extended to:
  - annotate multiple loads on the diagrams
  - show serviceability (deflection limit) status
  - show PASS/FAIL design status banner
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

AX_COLOR = "#161b22"
GRID_COL = "#30363d"
TEXT_COL = "#e6edf3"
MUTED_COL = "#8b949e"


def plot_results(result, beam_type, loads, L, material_name, section_name,
                  yield_stress, save_path="beam_output.png"):
    """
    result: dict returned by design_checks.evaluate_design()
    loads: original list of load dicts (for annotation)
    """
    x, V, M, delta, sigma = result["x"], result["V"], result["M"], result["delta"], result["sigma"]
    max_def_mm = result["max_deflection"] * 1000
    max_mom_kNm = result["max_moment"] / 1000
    max_shear_kN = result["max_shear"] / 1000
    max_sig_MPa = result["max_stress"] / 1e6
    sf = result["safety_factor"]
    allowable_defl_mm = result["allowable_deflection"] * 1000
    deflection_limit_key = result["deflection_limit_key"]

    fig = plt.figure(figsize=(14, 11), facecolor="#0d1117")
    fig.patch.set_facecolor("#0d1117")
    gs = gridspec.GridSpec(3, 2, figure=fig, left=0.08, right=0.96,
                            top=0.86, bottom=0.08, hspace=0.55, wspace=0.35)

    ax_sfd = fig.add_subplot(gs[0, 0])
    ax_bmd = fig.add_subplot(gs[1, 0])
    ax_def = fig.add_subplot(gs[2, 0])
    ax_met = fig.add_subplot(gs[:, 1])

    for ax in [ax_sfd, ax_bmd, ax_def]:
        ax.set_facecolor(AX_COLOR)
        ax.tick_params(colors=MUTED_COL, labelsize=8)
        ax.spines[:].set_color(GRID_COL)
        ax.grid(True, color=GRID_COL, linewidth=0.5, linestyle="--", alpha=0.7)
        ax.axhline(0, color=MUTED_COL, linewidth=0.8)

    # SFD
    ax_sfd.fill_between(x, V / 1000, 0, where=(V >= 0), color="#388bfd", alpha=0.3)
    ax_sfd.fill_between(x, V / 1000, 0, where=(V < 0), color="#f85149", alpha=0.3)
    ax_sfd.plot(x, V / 1000, color="#388bfd", linewidth=1.8)
    ax_sfd.set_ylabel("Shear (kN)", color=TEXT_COL, fontsize=9)
    ax_sfd.set_title("Shear Force Diagram", color=TEXT_COL, fontsize=10, pad=6)
    ax_sfd.set_xlabel("Position (m)", color=MUTED_COL, fontsize=8)

    # BMD
    ax_bmd.fill_between(x, M / 1000, 0, where=(M >= 0), color="#3fb950", alpha=0.3)
    ax_bmd.fill_between(x, M / 1000, 0, where=(M < 0), color="#d29922", alpha=0.3)
    ax_bmd.plot(x, M / 1000, color="#3fb950", linewidth=1.8)
    ax_bmd.set_ylabel("Moment (kN·m)", color=TEXT_COL, fontsize=9)
    ax_bmd.set_title("Bending Moment Diagram", color=TEXT_COL, fontsize=10, pad=6)
    ax_bmd.set_xlabel("Position (m)", color=MUTED_COL, fontsize=8)

    # Mark point load positions on SFD/BMD
    for load in loads:
        if load["type"] == "point":
            a = load["a"]
            ax_sfd.axvline(a, color="#f0883e", linewidth=0.8, linestyle=":")
            ax_bmd.axvline(a, color="#f0883e", linewidth=0.8, linestyle=":")

    # Deflection
    ax_def.fill_between(x, delta * 1000, 0, color="#bc8cff", alpha=0.25)
    ax_def.plot(x, delta * 1000, color="#bc8cff", linewidth=2)
    idx_max = np.argmax(np.abs(delta))
    ax_def.scatter(x[idx_max], delta[idx_max] * 1000, color="#bc8cff", s=60, zorder=5)
    ax_def.annotate(f"  {delta[idx_max] * 1000:.3f} mm",
                     (x[idx_max], delta[idx_max] * 1000), color="#bc8cff", fontsize=8)
    # Allowable deflection reference line
    ax_def.axhline(allowable_defl_mm, color="#d29922", linewidth=1, linestyle="--", alpha=0.8)
    ax_def.axhline(-allowable_defl_mm, color="#d29922", linewidth=1, linestyle="--", alpha=0.8)
    ax_def.text(x[-1] * 0.98, allowable_defl_mm, f" {deflection_limit_key} limit",
                color="#d29922", fontsize=7, ha="right", va="bottom")
    ax_def.set_ylabel("Deflection (mm)", color=TEXT_COL, fontsize=9)
    ax_def.set_title("Deflection Curve", color=TEXT_COL, fontsize=10, pad=6)
    ax_def.set_xlabel("Position (m)", color=MUTED_COL, fontsize=8)

    # Metrics panel
    ax_met.set_facecolor(AX_COLOR)
    ax_met.set_xticks([])
    ax_met.set_yticks([])
    ax_met.spines[:].set_color(GRID_COL)

    sf_color = "#3fb950" if sf >= 2 else "#d29922" if sf >= 1.2 else "#f85149"
    stress_status = "PASS ✓" if result["stress_pass"] else "FAIL ✗"
    stress_color = "#3fb950" if result["stress_pass"] else "#f85149"
    defl_status = "PASS ✓" if result["deflection_pass"] else "FAIL ✗"
    defl_color = "#3fb950" if result["deflection_pass"] else "#f85149"
    overall_status = "PASS ✓" if result["overall_pass"] else "FAIL ✗"
    overall_color = "#3fb950" if result["overall_pass"] else "#f85149"

    n_point = sum(1 for l in loads if l["type"] == "point")
    n_udl = sum(1 for l in loads if l["type"] == "udl")
    load_summary = f"{n_point} Point Load(s), {n_udl} UDL(s)"

    metrics = [
        ("BEAM TYPE", beam_type, MUTED_COL),
        ("LOADING", load_summary, MUTED_COL),
        ("MATERIAL", material_name, MUTED_COL),
        ("SECTION", section_name, MUTED_COL),
        ("", "", MUTED_COL),
        ("MAX SHEAR", f"{max_shear_kN:.2f} kN", "#388bfd"),
        ("MAX MOMENT", f"{max_mom_kNm:.2f} kN·m", "#3fb950"),
        ("MAX DEFLECTION", f"{max_def_mm:.4f} mm", "#bc8cff"),
        ("ALLOWABLE DEFLECTION", f"{allowable_defl_mm:.2f} mm ({deflection_limit_key})", MUTED_COL),
        ("MAX BENDING STRESS", f"{max_sig_MPa:.2f} MPa", "#d29922"),
        ("YIELD STRESS", f"{yield_stress / 1e6:.0f} MPa", MUTED_COL),
        ("", "", MUTED_COL),
        ("SAFETY FACTOR", f"{sf:.2f}", sf_color),
        ("STRESS CHECK", stress_status, stress_color),
        ("DEFLECTION CHECK", defl_status, defl_color),
        ("OVERALL DESIGN STATUS", overall_status, overall_color),
    ]

    y_start = 0.97
    dy = 0.061
    ax_met.set_title("Analysis Summary", color=TEXT_COL, fontsize=11, pad=10)
    for label, value, color in metrics:
        if label == "":
            y_start -= dy * 0.4
            continue
        ax_met.text(0.05, y_start, label, transform=ax_met.transAxes,
                    color=MUTED_COL, fontsize=8, fontweight="bold", va="top")
        ax_met.text(0.05, y_start - 0.026, str(value), transform=ax_met.transAxes,
                    color=color, fontsize=9.5, fontweight="bold", va="top")
        y_start -= dy

    fig.suptitle(
        f"Structural Beam Analysis Toolkit  ·  {beam_type}  ·  L = {L:.2f} m  ·  {load_summary}",
        color=TEXT_COL, fontsize=13, fontweight="bold", y=0.94
    )

    plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.show()
    print(f"\n✅ Plot saved as {save_path}")
