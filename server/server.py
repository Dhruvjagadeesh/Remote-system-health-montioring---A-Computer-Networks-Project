import socket
import threading
import json
import sqlite3
import time
import logging
import smtplib
import os
from datetime import datetime
from email.mime.text import MIMEText

HOST     = "0.0.0.0"
PORT     = 8080
DB_PATH  = "metrics.db"

CPU_THRESHOLD  = 80.0
MEM_THRESHOLD  = 85.0
DISK_THRESHOLD = 90.0

ALERT_EMAIL_ENABLED = False
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = ""
SMTP_PASS = ""
ALERT_TO  = ""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("server.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

connected_clients = {}
clients_lock      = threading.Lock()

MAX_CONNECTIONS_PER_IP  = 3
MAX_TOTAL_CONNECTIONS   = 20
MAX_MSG_PER_SEC_PER_IP  = 5
MAX_PAYLOAD_BYTES       = 8192

ip_connection_count = {}
ip_message_times    = {}
ip_lock             = threading.Lock()
total_connections   = 0
total_lock          = threading.Lock()
dos_blocked         = {}


def is_rate_limited(ip):
    now = time.time()
    with ip_lock:
        times = ip_message_times.get(ip, [])
        times = [t for t in times if now - t < 1.0]
        times.append(now)
        ip_message_times[ip] = times
        if len(times) > MAX_MSG_PER_SEC_PER_IP:
            dos_blocked[ip] = dos_blocked.get(ip, 0) + 1
            return True
    return False


def check_ip_conn_limit(ip):
    with ip_lock:
        count = ip_connection_count.get(ip, 0)
        if count >= MAX_CONNECTIONS_PER_IP:
            dos_blocked[ip] = dos_blocked.get(ip, 0) + 1
            return False
        ip_connection_count[ip] = count + 1
    return True


def release_ip_conn(ip):
    with ip_lock:
        count = ip_connection_count.get(ip, 1)
        ip_connection_count[ip] = max(0, count - 1)


def check_total_conn_limit():
    global total_connections
    with total_lock:
        if total_connections >= MAX_TOTAL_CONNECTIONS:
            return False
        total_connections += 1
    return True


def release_total_conn():
    global total_connections
    with total_lock:
        total_connections = max(0, total_connections - 1)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id           TEXT NOT NULL,
            hostname            TEXT,
            timestamp           TEXT NOT NULL,
            cpu_percent         REAL,
            mem_percent         REAL,
            disk_percent        REAL,
            net_bytes_sent      INTEGER,
            net_bytes_recv      INTEGER,
            throughput_sent_bps REAL,
            throughput_recv_bps REAL,
            latency_ms          REAL,
            load_avg_1          REAL,
            load_avg_5          REAL,
            load_avg_15         REAL
        )
    """)
    # add columns if upgrading from old schema (safe to run on existing DB)
    for col, coltype in [
        ("throughput_sent_bps", "REAL"),
        ("throughput_recv_bps", "REAL"),
        ("latency_ms",          "REAL"),
    ]:
        try:
            c.execute(f"ALTER TABLE metrics ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError:
            pass   # column already exists

    c.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id  TEXT NOT NULL,
            hostname   TEXT,
            timestamp  TEXT NOT NULL,
            alert_type TEXT,
            value      REAL,
            threshold  REAL,
            message    TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_metrics(data):
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("""
        INSERT INTO metrics (
            client_id, hostname, timestamp,
            cpu_percent, mem_percent, disk_percent,
            net_bytes_sent, net_bytes_recv,
            throughput_sent_bps, throughput_recv_bps, latency_ms,
            load_avg_1, load_avg_5, load_avg_15
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data.get("client_id",           "unknown"),
        data.get("hostname",            "unknown"),
        data.get("timestamp",           datetime.utcnow().isoformat()),
        data.get("cpu_percent",         0),
        data.get("mem_percent",         0),
        data.get("disk_percent",        0),
        data.get("net_bytes_sent",      0),
        data.get("net_bytes_recv",      0),
        data.get("throughput_sent_bps", 0),
        data.get("throughput_recv_bps", 0),
        data.get("latency_ms",          None),   # NULL until follow-up arrives
        data.get("load_avg_1",          0),
        data.get("load_avg_5",          0),
        data.get("load_avg_15",         0),
    ))
    conn.commit()
    conn.close()


def update_latency(client_id, latency_ms, throughput_sent_bps, throughput_recv_bps):
    """Back-fill latency + throughput onto the most recent row for this client."""
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("""
        UPDATE metrics
        SET    latency_ms          = ?,
               throughput_sent_bps = ?,
               throughput_recv_bps = ?
        WHERE  id = (
            SELECT id FROM metrics
            WHERE  client_id = ?
            ORDER  BY id DESC
            LIMIT  1
        )
    """, (latency_ms, throughput_sent_bps, throughput_recv_bps, client_id))
    conn.commit()
    conn.close()


def save_alert(client_id, hostname, alert_type, value, threshold, message):
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("""
        INSERT INTO alerts (client_id, hostname, timestamp, alert_type, value, threshold, message)
        VALUES (?,?,?,?,?,?,?)
    """, (client_id, hostname, datetime.utcnow().isoformat(), alert_type, value, threshold, message))
    conn.commit()
    conn.close()


def send_email_alert(subject, body):
    if not ALERT_EMAIL_ENABLED:
        return
    try:
        msg            = MIMEText(body)
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = ALERT_TO
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, ALERT_TO, msg.as_string())
    except Exception as e:
        log.error(f"Email alert failed: {e}")


def check_thresholds(data):
    client_id = data.get("client_id", "unknown")
    hostname  = data.get("hostname",  "unknown")
    alerts    = []

    checks = [
        ("CPU",    data.get("cpu_percent",  0), CPU_THRESHOLD),
        ("Memory", data.get("mem_percent",  0), MEM_THRESHOLD),
        ("Disk",   data.get("disk_percent", 0), DISK_THRESHOLD),
    ]

    for metric, value, threshold in checks:
        if value > threshold:
            msg = f"[ALERT] {hostname} ({client_id}): {metric} at {value:.1f}% exceeds {threshold}%"
            log.warning(msg)
            save_alert(client_id, hostname, metric, value, threshold, msg)
            alerts.append(msg)
            send_email_alert(f"Health Alert: {metric} on {hostname}", msg)

    return alerts


DEFENSE_ENABLED = True


def handle_client(conn, addr):
    ip        = addr[0]
    client_id = None
    buffer    = ""

    try:
        log.info(f"Connection from {addr}")
        conn.settimeout(15)

        while True:
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                log.warning(f"Timeout / possible slowloris from {ip}, dropping")
                break

            if not chunk:
                break

            if DEFENSE_ENABLED and len(chunk) > MAX_PAYLOAD_BYTES:
                log.warning(f"Oversized payload ({len(chunk)}B) from {ip}, dropping connection")
                dos_blocked[ip] = dos_blocked.get(ip, 0) + 1
                break

            try:
                buffer += chunk.decode("utf-8")
            except UnicodeDecodeError:
                log.warning(f"Non-UTF8 data from {ip}, dropping")
                break

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                if DEFENSE_ENABLED and is_rate_limited(ip):
                    log.warning(f"Rate limit hit for {ip} -- dropping message")
                    continue

                try:
                    data = json.loads(line)

                    # ── latency follow-up packet (small, no full metrics) ──
                    if data.get("_latency_update"):
                        cid = data.get("client_id", str(addr))
                        update_latency(
                            cid,
                            data.get("latency_ms",          None),
                            data.get("throughput_sent_bps",  0),
                            data.get("throughput_recv_bps",  0),
                        )
                        log.info(
                            f"Latency update for {cid}: "
                            f"{data.get('latency_ms')}ms "
                            f"TX:{data.get('throughput_sent_bps')}B/s "
                            f"RX:{data.get('throughput_recv_bps')}B/s"
                        )
                        continue   # no response needed for follow-up
                    # ──────────────────────────────────────────────────────

                    client_id = data.get("client_id", str(addr))
                    hostname  = data.get("hostname",  "unknown")

                    with clients_lock:
                        connected_clients[client_id] = {
                            "addr":         str(addr),
                            "hostname":     hostname,
                            "last_seen":    datetime.utcnow().isoformat(),
                            "last_metrics": data,
                        }

                    save_metrics(data)
                    alerts = check_thresholds(data)

                    response = json.dumps({
                        "status":      "ok",
                        "alerts":      alerts,
                        "server_time": datetime.utcnow().isoformat()
                    }) + "\n"
                    conn.sendall(response.encode("utf-8"))

                    log.info(
                        f"{hostname} | CPU:{data.get('cpu_percent',0):.1f}% "
                        f"MEM:{data.get('mem_percent',0):.1f}% "
                        f"DISK:{data.get('disk_percent',0):.1f}% "
                        f"TX:{data.get('throughput_sent_bps',0)}B/s "
                        f"RX:{data.get('throughput_recv_bps',0)}B/s"
                    )

                except json.JSONDecodeError as e:
                    log.error(f"JSON parse error from {addr}: {e}")

    except ConnectionResetError:
        log.info(f"Client {addr} disconnected abruptly")
    except Exception as e:
        log.error(f"Error handling client {addr}: {e}")
    finally:
        conn.close()
        release_ip_conn(ip)
        release_total_conn()
        if client_id:
            with clients_lock:
                connected_clients.pop(client_id, None)
        log.info(f"Connection closed: {addr}")


def run_server():
    init_db()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen(100)
        log.info(f"Server listening on {HOST}:{PORT}")
        log.info(
            f"Defense {'ENABLED' if DEFENSE_ENABLED else 'DISABLED'} | "
            f"max_conn_per_ip={MAX_CONNECTIONS_PER_IP} "
            f"max_total={MAX_TOTAL_CONNECTIONS} "
            f"rate_limit={MAX_MSG_PER_SEC_PER_IP}msg/s"
        )
        while True:
            conn, addr = s.accept()
            ip = addr[0]

            if DEFENSE_ENABLED:
                if not check_total_conn_limit():
                    log.warning(f"Total connection limit reached, rejecting {addr}")
                    conn.close()
                    continue
                if not check_ip_conn_limit(ip):
                    log.warning(f"Per-IP connection limit reached for {ip}, rejecting")
                    conn.close()
                    release_total_conn()
                    continue

            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-defense", action="store_true",
                        help="Disable DoS defenses (for demo: show attack impact)")
    args = parser.parse_args()
    if args.no_defense:
        DEFENSE_ENABLED = False
        log.warning("DoS defenses DISABLED -- demo mode")
    run_server()