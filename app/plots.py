from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from app import config  # noqa: E402


def write_qoi_vs_velocity_plot(run_id: str, rows: list[dict]) -> str | None:
    """rows: the same per-case dicts written to sweep_results.json. Plots
    pressure_drop vs inlet_velocity for medium-mesh cases only (the mesh
    level validated by the independence gate). Returns the written path, or
    None if there weren't at least two comparable points to plot."""
    medium_rows = sorted(
        (
            r for r in rows
            if r.get("mesh_level") == "medium"
            and r.get("inlet_velocity") is not None
            and r.get("pressure_drop") is not None
        ),
        key=lambda r: r["inlet_velocity"],
    )
    if len(medium_rows) < 2:
        return None

    velocities = [r["inlet_velocity"] for r in medium_rows]
    pressure_drops = [r["pressure_drop"] for r in medium_rows]

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(velocities, pressure_drops, marker="o")
    ax.set_xlabel("Inlet velocity (m/s)")
    ax.set_ylabel("Pressure drop, inlet - outlet (kinematic, m^2/s^2)")
    ax.set_title("Pressure drop vs inlet velocity (medium mesh)")
    ax.grid(True, alpha=0.3)

    plots_dir = config.RUNS_DIR / run_id / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    path = plots_dir / "qoi_vs_velocity.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return str(path)
