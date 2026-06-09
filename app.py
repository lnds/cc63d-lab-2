import os
import logging
from datetime import datetime, date, timezone

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import errors as pg_errors
from flask import Flask, request, jsonify, g
from flask.json.provider import DefaultJSONProvider


# --- JSON: fechas como ISO-8601 (UTC con 'Z') para que el frontend las parsee ---

class ISOJSONProvider(DefaultJSONProvider):
    def default(self, o):
        if isinstance(o, datetime):
            if o.tzinfo is None:
                o = o.replace(tzinfo=timezone.utc)
            return o.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if isinstance(o, date):
            return o.strftime("%Y-%m-%d")
        return super().default(o)


app = Flask(__name__)
app.json = ISOJSONProvider(app)
logging.basicConfig(level=logging.INFO)

# Factor III (12-Factor): la configuración vive en el environment.
# La app no sabe *dónde* está la base de datos: lo dice DATABASE_URL.
DATABASE_URL = os.environ["DATABASE_URL"]


def get_db():
    if "db" not in g:
        g.db = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# El schema ya no se crea aquí: lo gestiona Flyway antes de que arranque la app.


def now():
    return datetime.now(timezone.utc)


def query_all(sql, params=()):
    with get_db().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def query_one(sql, params=()):
    with get_db().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


# --- Health ---

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# --- Services ---

@app.route("/services", methods=["GET"])
def list_services():
    rows = query_all("SELECT * FROM services ORDER BY name")
    return jsonify([dict(r) for r in rows])


@app.route("/services", methods=["POST"])
def create_service():
    data = request.json
    if not data or not data.get("name") or not data.get("team"):
        return jsonify({"error": "name and team are required"}), 400
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO services (name, team, slo_target, sli_type) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (data["name"], data["team"],
                 data.get("slo_target", 99.9), data.get("sli_type", "availability")),
            )
            new_id = cur.fetchone()["id"]
        db.commit()
    except pg_errors.UniqueViolation:
        db.rollback()
        return jsonify({"error": f"service '{data['name']}' already exists"}), 409
    return jsonify({"id": new_id}), 201


@app.route("/services/<int:service_id>", methods=["GET"])
def get_service(service_id):
    row = query_one("SELECT * FROM services WHERE id = %s", (service_id,))
    if not row:
        return jsonify({"error": "service not found"}), 404
    return jsonify(dict(row))


# --- On-Call ---

@app.route("/oncall", methods=["GET"])
def list_oncall():
    rows = query_all("""
        SELECT o.*, s.name as service_name
        FROM oncall o JOIN services s ON o.service_id = s.id
        ORDER BY o.start_date DESC
    """)
    return jsonify([dict(r) for r in rows])


@app.route("/oncall", methods=["POST"])
def create_oncall():
    data = request.json
    if not data or not all(k in data for k in ("service_id", "person", "email", "start_date", "end_date")):
        return jsonify({"error": "service_id, person, email, start_date and end_date are required"}), 400
    db = get_db()
    service = query_one("SELECT id FROM services WHERE id = %s", (data["service_id"],))
    if not service:
        return jsonify({"error": "service not found"}), 404
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO oncall (service_id, person, email, start_date, end_date) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (data["service_id"], data["person"], data["email"], data["start_date"], data["end_date"]),
        )
        new_id = cur.fetchone()["id"]
    db.commit()
    return jsonify({"id": new_id}), 201


@app.route("/oncall/current/<int:service_id>", methods=["GET"])
def get_current_oncall(service_id):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = query_one(
        "SELECT * FROM oncall WHERE service_id = %s AND start_date <= %s AND end_date >= %s LIMIT 1",
        (service_id, today, today),
    )
    if not row:
        return jsonify({"error": "no one on-call for this service today"}), 404
    return jsonify(dict(row))


# --- Incidents ---

@app.route("/incidents", methods=["GET"])
def list_incidents():
    status = request.args.get("status")
    if status:
        rows = query_all("""
            SELECT i.*, s.name as service_name
            FROM incidents i JOIN services s ON i.service_id = s.id
            WHERE i.status = %s ORDER BY i.started_at DESC
        """, (status,))
    else:
        rows = query_all("""
            SELECT i.*, s.name as service_name
            FROM incidents i JOIN services s ON i.service_id = s.id
            ORDER BY i.started_at DESC
        """)
    return jsonify([dict(r) for r in rows])


@app.route("/incidents", methods=["POST"])
def create_incident():
    data = request.json
    if not data or not data.get("title") or not data.get("service_id") or not data.get("severity"):
        return jsonify({"error": "title, service_id and severity are required"}), 400
    if data["severity"] not in (1, 2, 3, 4):
        return jsonify({"error": "severity must be between 1 and 4"}), 400

    db = get_db()
    service = query_one("SELECT * FROM services WHERE id = %s", (data["service_id"],))
    if not service:
        return jsonify({"error": "service not found"}), 404

    ts = now()
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO incidents (service_id, title, severity, status, started_at, created_by) "
            "VALUES (%s, %s, %s, 'open', %s, %s) RETURNING id",
            (data["service_id"], data["title"], data["severity"], ts, data.get("created_by", "system")),
        )
        incident_id = cur.fetchone()["id"]

        cur.execute(
            "INSERT INTO incident_timeline (incident_id, timestamp, author, message) VALUES (%s, %s, %s, %s)",
            (incident_id, ts, data.get("created_by", "system"), f"Incident created: {data['title']}"),
        )

        # notify on-call
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cur.execute(
            "SELECT * FROM oncall WHERE service_id = %s AND start_date <= %s AND end_date >= %s LIMIT 1",
            (data["service_id"], today, today),
        )
        oncall = cur.fetchone()

        notification = None
        if oncall:
            notification = {
                "person": oncall["person"],
                "email": oncall["email"],
                "message": f"[SEV{data['severity']}] {data['title']} on {service['name']}",
            }
            cur.execute(
                "INSERT INTO incident_timeline (incident_id, timestamp, author, message) VALUES (%s, %s, %s, %s)",
                (incident_id, ts, "system", f"Notified {oncall['person']} ({oncall['email']})"),
            )
            app.logger.info(f"NOTIFICATION: {notification['message']} -> {oncall['person']} <{oncall['email']}>")
        else:
            cur.execute(
                "INSERT INTO incident_timeline (incident_id, timestamp, author, message) VALUES (%s, %s, %s, %s)",
                (incident_id, ts, "system", "WARNING: No on-call found for this service"),
            )
            app.logger.warning(f"No on-call found for service {service['name']}")

    db.commit()
    return jsonify({"id": incident_id, "notification": notification}), 201


@app.route("/incidents/<int:incident_id>", methods=["GET"])
def get_incident(incident_id):
    incident = query_one("""
        SELECT i.*, s.name as service_name, s.team
        FROM incidents i JOIN services s ON i.service_id = s.id
        WHERE i.id = %s
    """, (incident_id,))
    if not incident:
        return jsonify({"error": "incident not found"}), 404

    timeline = query_all(
        "SELECT * FROM incident_timeline WHERE incident_id = %s ORDER BY timestamp",
        (incident_id,),
    )

    result = dict(incident)
    result["timeline"] = [dict(t) for t in timeline]
    return jsonify(result)


@app.route("/incidents/<int:incident_id>", methods=["PATCH"])
def update_incident(incident_id):
    data = request.json
    if not data:
        return jsonify({"error": "request body required"}), 400

    db = get_db()
    incident = query_one("SELECT * FROM incidents WHERE id = %s", (incident_id,))
    if not incident:
        return jsonify({"error": "incident not found"}), 404

    ts = now()
    author = data.get("author", "system")

    with db.cursor() as cur:
        if "status" in data:
            new_status = data["status"]
            if new_status not in ("open", "investigating", "mitigated", "resolved"):
                return jsonify({"error": "invalid status"}), 400
            resolved_at = ts if new_status == "resolved" else None
            cur.execute(
                "UPDATE incidents SET status = %s, resolved_at = COALESCE(%s, resolved_at) WHERE id = %s",
                (new_status, resolved_at, incident_id),
            )
            cur.execute(
                "INSERT INTO incident_timeline (incident_id, timestamp, author, message) VALUES (%s, %s, %s, %s)",
                (incident_id, ts, author, f"Status changed to {new_status}"),
            )

        if "message" in data:
            cur.execute(
                "INSERT INTO incident_timeline (incident_id, timestamp, author, message) VALUES (%s, %s, %s, %s)",
                (incident_id, ts, author, data["message"]),
            )

    db.commit()
    return jsonify({"ok": True})


# --- Post-Mortems ---

@app.route("/postmortems", methods=["POST"])
def create_postmortem():
    data = request.json
    required = ("incident_id", "summary", "root_cause", "impact", "action_items")
    if not data or not all(k in data for k in required):
        return jsonify({"error": f"{', '.join(required)} are required"}), 400

    db = get_db()
    incident = query_one("SELECT * FROM incidents WHERE id = %s", (data["incident_id"],))
    if not incident:
        return jsonify({"error": "incident not found"}), 404
    if incident["status"] != "resolved":
        return jsonify({"error": "incident must be resolved before writing a post-mortem"}), 400

    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO postmortems (incident_id, summary, root_cause, impact, action_items, lessons) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (data["incident_id"], data["summary"], data["root_cause"],
                 data["impact"], data["action_items"], data.get("lessons", "")),
            )
            new_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO incident_timeline (incident_id, timestamp, author, message) VALUES (%s, %s, %s, %s)",
                (data["incident_id"], now(), data.get("author", "system"), "Post-mortem published"),
            )
        db.commit()
    except pg_errors.UniqueViolation:
        db.rollback()
        return jsonify({"error": "post-mortem already exists for this incident"}), 409

    return jsonify({"id": new_id}), 201


@app.route("/postmortems/<int:postmortem_id>", methods=["GET"])
def get_postmortem(postmortem_id):
    row = query_one("""
        SELECT p.*, i.title as incident_title, i.severity, s.name as service_name
        FROM postmortems p
        JOIN incidents i ON p.incident_id = i.id
        JOIN services s ON i.service_id = s.id
        WHERE p.id = %s
    """, (postmortem_id,))
    if not row:
        return jsonify({"error": "post-mortem not found"}), 404
    return jsonify(dict(row))


@app.route("/postmortems", methods=["GET"])
def list_postmortems():
    rows = query_all("""
        SELECT p.*, i.title as incident_title, i.severity, s.name as service_name
        FROM postmortems p
        JOIN incidents i ON p.incident_id = i.id
        JOIN services s ON i.service_id = s.id
        ORDER BY p.created_at DESC
    """)
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    # Solo para desarrollo local. En contenedor corre gunicorn (ver Dockerfile).
    app.run(host="0.0.0.0", port=8080, debug=True)
