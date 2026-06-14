"""
Starter Flask app on top of TeslaMate's Postgres DB (read-only).

Two ideas to grow from here:
  - /api/drives      -> last N drives as JSON (distance, duration, efficiency)
  - /api/efficiency  -> efficiency per drive over time (powers the chart on /)

NOTE ON SCHEMA: TeslaMate's columns drift between releases. The queries below
target stable, long-standing columns on `drives` and `charging_processes`.
If a query 500s, run `\d drives` in psql and adjust the column names.
"""
import os

from flask import Flask, jsonify, render_template
from sqlalchemy import create_engine, text

app = Flask(__name__)

engine = create_engine(
    os.environ["DATABASE_URL"],
    pool_pre_ping=True,   # survive the DB restarting under us
    pool_size=5,
)

# --- efficiency = rated km consumed per km driven, scaled to Wh/km ---
# TeslaMate stores range in km; a Model Y's rated efficiency is ~152 Wh/km.
# This is a proxy, good enough for trend-spotting (which is the whole point).
RATED_WH_PER_KM = 152

DRIVES_SQL = text("""
    SELECT
        id,
        start_date,
        end_date,
        distance,
        duration_min,
        start_rated_range_km,
        end_rated_range_km
    FROM drives
    WHERE distance > 1                       -- ignore parking-lot shuffles
    ORDER BY start_date DESC
    LIMIT :limit
""")

CHARGES_SQL = text("""
    SELECT
        id,
        start_date,
        end_date,
        charge_energy_added,
        start_battery_level,
        end_battery_level,
        cost
    FROM charging_processes
    ORDER BY start_date DESC
    LIMIT :limit
""")

# Battery health: project each charge's end state to a full pack.
# Filter to charges that finished above a sensible SOC — projecting a 100%
# range from a 12% reading amplifies noise badly. Same idea as TeslaMate's
# Battery Health dashboard.
DEGRADATION_SQL = text("""
    SELECT
        end_date,
        end_battery_level,
        end_rated_range_km
    FROM charging_processes
    WHERE end_battery_level >= :min_soc
      AND end_rated_range_km IS NOT NULL
      AND end_battery_level > 0
    ORDER BY end_date ASC
""")


def _drive_to_dict(row):
    rated_used = None
    efficiency = None
    if row.start_rated_range_km is not None and row.end_rated_range_km is not None:
        rated_used = row.start_rated_range_km - row.end_rated_range_km
        if row.distance and row.distance > 0:
            efficiency = round(rated_used / row.distance * RATED_WH_PER_KM, 1)

    avg_speed = None
    if row.duration_min and row.duration_min > 0:
        avg_speed = round(row.distance / row.duration_min * 60, 1)

    return {
        "id": row.id,
        "start": row.start_date.isoformat() if row.start_date else None,
        "end": row.end_date.isoformat() if row.end_date else None,
        "distance_km": round(row.distance, 1) if row.distance else None,
        "duration_min": row.duration_min,
        "avg_speed_kmh": avg_speed,
        "efficiency_wh_per_km": efficiency,
    }


@app.get("/healthz")
def healthz():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/api/drives")
def api_drives():
    with engine.connect() as conn:
        rows = conn.execute(DRIVES_SQL, {"limit": 10}).fetchall()
    return jsonify([_drive_to_dict(r) for r in rows])


@app.get("/api/charges")
def api_charges():
    with engine.connect() as conn:
        rows = conn.execute(CHARGES_SQL, {"limit": 10}).fetchall()
    return jsonify([
        {
            "id": r.id,
            "start": r.start_date.isoformat() if r.start_date else None,
            "end": r.end_date.isoformat() if r.end_date else None,
            "kwh_added": round(r.charge_energy_added, 2) if r.charge_energy_added else None,
            "battery": f"{r.start_battery_level}% -> {r.end_battery_level}%",
            "cost": float(r.cost) if r.cost is not None else None,
        }
        for r in rows
    ])


@app.get("/api/efficiency")
def api_efficiency():
    """Efficiency per drive, oldest-first, for the trend chart."""
    with engine.connect() as conn:
        rows = conn.execute(DRIVES_SQL, {"limit": 200}).fetchall()
    points = [
        {"x": d["start"], "y": d["efficiency_wh_per_km"]}
        for d in (_drive_to_dict(r) for r in rows)
        if d["efficiency_wh_per_km"] is not None
    ]
    points.reverse()  # chronological
    return jsonify(points)


@app.get("/api/degradation")
def api_degradation():
    """Projected full-pack rated range over time → the degradation curve.

    Each point is one charge's range extrapolated to 100% SOC. New-car
    baseline for a Model Y is ~455 km rated; `pct_of_new` shows health.
    """
    new_car_range_km = 455
    with engine.connect() as conn:
        rows = conn.execute(DEGRADATION_SQL, {"min_soc": 50}).fetchall()
    points = []
    for r in rows:
        projected = round(r.end_rated_range_km * 100 / r.end_battery_level, 1)
        points.append({
            "x": r.end_date.isoformat() if r.end_date else None,
            "y": projected,
            "soc": r.end_battery_level,
            "pct_of_new": round(projected / new_car_range_km * 100, 1),
        })
    return jsonify(points)


@app.get("/")
def dashboard():
    return render_template("dashboard.html")


if __name__ == "__main__":
    # dev only; in the container gunicorn runs this
    app.run(host="0.0.0.0", port=8000, debug=True)
