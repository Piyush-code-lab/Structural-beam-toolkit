"""
app.py
======
Flask web server for the Structural Beam Analysis & Design Toolkit.
Wraps the existing Python modules (beam_solver, design_checks, optimizer,
design_advisor, missing_param_solver) as JSON API endpoints consumed by
the frontend. The toolkit logic is completely unchanged.
"""

import io
import base64
import traceback

import matplotlib
matplotlib.use("Agg")   # non-interactive backend — must be set before pyplot import
import matplotlib.pyplot as plt

from flask import Flask, request, jsonify, render_template

from materials import MATERIALS
from sections_db import load_ipe_sections
from beam_config import classify_supports, UnsupportedConfigurationError
from design_checks import evaluate_design, recommend_section
from optimizer import optimize_design, OBJECTIVE_LABELS
from design_advisor import generate_recommendations, format_advisor_report
from missing_param_solver import (
    solve_max_allowable_load, solve_max_span,
    solve_best_material, solve_best_section,
)
from plotting import plot_results as _plot_results

app = Flask(__name__)
IPE_SECTIONS = load_ipe_sections()


# ── helpers ──────────────────────────────────────────────────────────────────

def _fig_to_b64():
    """Capture current Matplotlib figure as a base64 PNG string, then close it."""
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=plt.gcf().get_facecolor())
    plt.close("all")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _make_plot(result, beam_type, loads, L, material_name, section_name, yield_stress):
    """Run plot_results (which calls plt.show internally) then capture the figure."""
    # Monkey-patch plt.show to a no-op so the server doesn't try to open a window
    _orig_show = plt.show
    plt.show = lambda *a, **kw: None
    try:
        _plot_results(result, beam_type, loads, L, material_name, section_name, yield_stress)
        img = _fig_to_b64()
    finally:
        plt.show = _orig_show
    return img


def _parse_supports(raw):
    """Convert list of {type, position} dicts from JSON into internal format."""
    return [{"type": s["type"], "position": float(s["position"])} for s in raw]


def _parse_loads(raw):
    """Convert JSON load list into internal format."""
    loads = []
    for ld in raw:
        if ld["type"] == "point":
            loads.append({"type": "point", "P": float(ld["P"]) * 1000,
                          "a": float(ld["a"])})
        else:
            loads.append({"type": "udl", "w": float(ld["w"]) * 1000,
                          "start": float(ld["start"]), "end": float(ld["end"])})
    return loads


def _result_summary(result):
    """Serialize an evaluate_design() result dict to JSON-safe form."""
    return {
        "max_shear":          round(float(result["max_shear"]) / 1000, 4),
        "max_moment":         round(float(result["max_moment"]) / 1000, 4),
        "max_deflection_mm":  round(float(result["max_deflection"]) * 1000, 4),
        "allowable_defl_mm":  round(float(result["allowable_deflection"]) * 1000, 4),
        "deflection_limit":   result["deflection_limit_key"],
        "max_stress_mpa":     round(float(result["max_stress"]) / 1e6, 2),
        "safety_factor":      round(float(result["safety_factor"]), 2),
        "stress_pass":        bool(result["stress_pass"]),
        "deflection_pass":    bool(result["deflection_pass"]),
        "overall_pass":       bool(result["overall_pass"]),
        "used_numerical":     bool(result.get("used_numerical_integration", False)),
    }


# ── routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html",
                           materials=list(MATERIALS.keys()),
                           sections=list(IPE_SECTIONS.keys()))


@app.route("/api/classify_supports", methods=["POST"])
def api_classify():
    data = request.get_json()
    try:
        supports = _parse_supports(data["supports"])
        L = float(data["L"])
        beam_type = classify_supports(supports, L)
        return jsonify({"beam_type": beam_type})
    except UnsupportedConfigurationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json()
    try:
        L            = float(data["L"])
        supports     = _parse_supports(data["supports"])
        loads        = _parse_loads(data["loads"])
        material     = data["material"]
        section_name = data["section"]
        defl_limit   = data.get("deflection_limit", "L/360")
        mode         = data.get("mode", "manual")   # "manual" | "auto"

        beam_type = classify_supports(supports, L)
        mat       = MATERIALS[material]
        E, yield_stress = mat["E"], mat["yield"]

        if mode == "auto":
            sec_name, result = recommend_section(
                beam_type, loads, L, E, yield_stress, IPE_SECTIONS,
                deflection_limit_key=defl_limit)
            if sec_name is None:
                # adviser against largest available section
                heaviest = max(IPE_SECTIONS, key=lambda n: IPE_SECTIONS[n]["weight"])
                props    = IPE_SECTIONS[heaviest]
                result   = evaluate_design(beam_type, loads, L, E, props["I"],
                                           props["Z"], yield_stress,
                                           deflection_limit_key=defl_limit)
                section_name = heaviest
                sec_name     = None   # signal to FE that nothing passed
            else:
                section_name = sec_name
        else:
            props  = IPE_SECTIONS[section_name]
            result = evaluate_design(beam_type, loads, L, E, props["I"], props["Z"],
                                     yield_stress, deflection_limit_key=defl_limit)

        img = _make_plot(result, beam_type, loads, L, material, section_name, yield_stress)

        # Advisor
        advisor_text = ""
        if not result["overall_pass"] and section_name in IPE_SECTIONS:
            diag, recs = generate_recommendations(
                beam_type, loads, L, E, yield_stress, section_name,
                IPE_SECTIONS, result, defl_limit)
            advisor_text = format_advisor_report(diag, recs, section_name)

        resp = {
            "beam_type":    beam_type,
            "section":      section_name,
            "auto_found":   (mode == "auto" and sec_name is not None),
            "result":       _result_summary(result),
            "plot_b64":     img,
            "advisor":      advisor_text,
        }
        if mode == "auto" and sec_name:
            resp["weight_per_m"] = round(IPE_SECTIONS[sec_name]["weight"], 1)
        return jsonify(resp)

    except UnsupportedConfigurationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500


@app.route("/api/optimize", methods=["POST"])
def api_optimize():
    data = request.get_json()
    try:
        L         = float(data["L"])
        supports  = _parse_supports(data["supports"])
        loads     = _parse_loads(data["loads"])
        objective = data.get("objective", "weight")
        defl_limit= data.get("deflection_limit", "L/360")

        beam_type = classify_supports(supports, L)
        best = optimize_design(beam_type, loads, L, MATERIALS, IPE_SECTIONS,
                               objective=objective,
                               deflection_limit_key=defl_limit)
        if best is None:
            return jsonify({"error": "No feasible design found for these constraints. "
                            "Try a shorter span, lighter load, or relaxed serviceability limit."}), 400

        mat        = best["material"]
        sec        = best["section_name"]
        yield_s    = MATERIALS[mat]["yield"]
        result     = best["result"]

        img = _make_plot(result, beam_type, loads, L, mat, sec, yield_s)

        return jsonify({
            "beam_type":      beam_type,
            "material":       mat,
            "section":        sec,
            "weight_per_m":   round(best["weight_per_m"], 2),
            "cost_per_m":     round(best["cost_per_m"], 2),
            "objective_label":best["objective_label"],
            "n_feasible":     best["n_feasible"],
            "n_total":        best["n_total"],
            "result":         _result_summary(result),
            "plot_b64":       img,
        })

    except UnsupportedConfigurationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500


@app.route("/api/missing_param", methods=["POST"])
def api_missing_param():
    data = request.get_json()
    try:
        missing      = data["missing"]          # "length"|"section"|"material"|"load"
        beam_type    = data["beam_type"]        # already classified by FE
        loads_raw    = data["loads"]
        defl_limit   = data.get("deflection_limit", "L/360")
        min_sf       = float(data.get("min_sf", 1.5))

        L            = float(data["L"])         if data.get("L")        else None
        material     = data.get("material")
        section_name = data.get("section")

        loads = _parse_loads(loads_raw)
        # For missing-load mode the FE sends unit loads; solver scales them
        base_load = loads[0] if loads else None

        E = MATERIALS[material]["E"]         if material     else None
        yield_s = MATERIALS[material]["yield"] if material   else None
        I = IPE_SECTIONS[section_name]["I"]  if section_name else None
        Z = IPE_SECTIONS[section_name]["Z"]  if section_name else None

        if missing == "load":
            res = solve_max_allowable_load(beam_type, [base_load], L, E, I, Z,
                                           yield_s, defl_limit, min_sf)
            solved_val = res["solved_loads"][0]["P"]/1000 if base_load["type"]=="point" \
                         else res["solved_loads"][0]["w"]/1000
            unit = "kN" if base_load["type"] == "point" else "kN/m"
            img = _make_plot(res, beam_type, res["solved_loads"], L, material,
                             section_name, yield_s)
            return jsonify({"solved": f"{solved_val:.3f} {unit}",
                            "result": _result_summary(res), "plot_b64": img})

        elif missing == "length":
            base_load["_relative_position"] = float(data.get("load_position_fraction", 0.5))
            res = solve_max_span(beam_type, [base_load], E, I, Z, yield_s,
                                 defl_limit, min_sf)
            if not res.get("feasible"):
                return jsonify({"error": res.get("message", "No feasible span.")}), 400
            solved_L = res["solved_length"]
            img = _make_plot(res, beam_type, res["solved_loads"], solved_L,
                             material, section_name, yield_s)
            return jsonify({"solved": f"{solved_L:.3f} m",
                            "result": _result_summary(res), "plot_b64": img})

        elif missing == "section":
            res_dict = solve_best_section(beam_type, loads, L, E, yield_s,
                                          IPE_SECTIONS, defl_limit, min_sf)
            if not res_dict["section_name"]:
                return jsonify({"error": res_dict.get("message", "No section found.")}), 400
            sec  = res_dict["section_name"]
            res  = res_dict["result"]
            img  = _make_plot(res, beam_type, loads, L, material, sec, yield_s)
            return jsonify({"solved": sec,
                            "weight_per_m": IPE_SECTIONS[sec]["weight"],
                            "result": _result_summary(res), "plot_b64": img})

        elif missing == "material":
            res_dict = solve_best_material(beam_type, loads, L, I, Z,
                                           defl_limit, min_sf)
            if not res_dict["material_name"]:
                return jsonify({"error": res_dict.get("message", "No material found.")}), 400
            mat  = res_dict["material_name"]
            res  = res_dict["result"]
            img  = _make_plot(res, beam_type, loads, L, mat, section_name,
                              MATERIALS[mat]["yield"])
            return jsonify({"solved": mat,
                            "result": _result_summary(res), "plot_b64": img})

        return jsonify({"error": f"Unknown missing parameter '{missing}'"}), 400

    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
