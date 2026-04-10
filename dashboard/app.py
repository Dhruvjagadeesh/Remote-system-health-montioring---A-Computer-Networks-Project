import os
from flask import Flask, render_template, jsonify, request
import sqlite3
from datetime import datetime, timedelta

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server", "metrics.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/clients")
def api_clients():
    conn = get_db()
    c = conn.cursor()
    cutoff = (datetime.utcnow() - timedelta(seconds=30)).isoformat()
    c.execute("""
        SELECT client_id, hostname, MAX(timestamp) as last_seen,
               cpu_percent, mem_percent, disk_percent
        FROM metrics
        WHERE timestamp > ?
        GROUP BY client_id
    """, (cutoff,))
    rows = c.fetchall()
    conn.close()
    clients = {}
    for r in rows:
        r = dict(r)
        cid = r["client_id"]
        clients[cid] = {
            "hostname": r["hostname"],
            "last_seen": r["last_seen"],
            "cpu_percent": r["cpu_percent"],
            "mem_percent": r["mem_percent"],
            "disk_percent": r["disk_percent"],
        }
    return jsonify({"clients": clients, "count": len(clients)})


@app.route("/api/metrics")
def api_metrics():
    client_id = request.args.get("client_id")
    minutes = int(request.args.get("minutes", 10))
    limit = int(request.args.get("limit", 100))
    cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()

    conn = get_db()
    c = conn.cursor()

    if client_id:
        c.execute("""
            SELECT * FROM metrics
            WHERE client_id = ? AND timestamp > ?
            ORDER BY timestamp DESC LIMIT ?
        """, (client_id, cutoff, limit))
    else:
        c.execute("""
            SELECT * FROM metrics
            WHERE timestamp > ?
            ORDER BY timestamp DESC LIMIT ?
        """, (cutoff, limit))

    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"metrics": rows[::-1]})


@app.route("/api/alerts")
def api_alerts():
    limit = int(request.args.get("limit", 50))
    client_id = request.args.get("client_id")
    conn = get_db()
    c = conn.cursor()
    if client_id:
        c.execute("SELECT * FROM alerts WHERE client_id=? ORDER BY timestamp DESC LIMIT ?", (client_id, limit))
    else:
        c.execute("SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"alerts": rows})


@app.route("/api/clients/list")
def api_clients_list():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT DISTINCT client_id, hostname FROM metrics ORDER BY client_id")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"clients": rows})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
