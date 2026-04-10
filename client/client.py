import socket
import json
import time
import logging
import os
import platform
import uuid
import sys

try:
    import psutil
except ImportError:
    print("psutil not found. Install it: pip install psutil")
    sys.exit(1)

SERVER_HOST = os.environ.get("MONITOR_SERVER", "192.168.1.100")
SERVER_PORT = int(os.environ.get("MONITOR_PORT", "8080"))
INTERVAL    = int(os.environ.get("MONITOR_INTERVAL", "10"))
CLIENT_ID   = os.environ.get("CLIENT_ID", str(uuid.uuid4())[:8] + "-" + platform.node())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("client.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── state kept between metric collections for throughput delta ─────────────
_prev_net_sent = None
_prev_net_recv = None
_prev_net_time = None
# ──────────────────────────────────────────────────────────────────────────


def collect_metrics():
    global _prev_net_sent, _prev_net_recv, _prev_net_time

    cpu  = psutil.cpu_percent(interval=1)
    mem  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net  = psutil.net_io_counters()
    now  = time.time()

    # ── throughput: bytes/sec since last reading ───────────────────────────
    if _prev_net_sent is not None:
        dt = now - _prev_net_time
        throughput_sent_bps = round((net.bytes_sent - _prev_net_sent) / dt, 2)
        throughput_recv_bps = round((net.bytes_recv - _prev_net_recv) / dt, 2)
    else:
        # first reading — no delta available yet
        throughput_sent_bps = 0.0
        throughput_recv_bps = 0.0

    _prev_net_sent = net.bytes_sent
    _prev_net_recv = net.bytes_recv
    _prev_net_time = now
    # ──────────────────────────────────────────────────────────────────────

    try:
        load1, load5, load15 = os.getloadavg()
    except (AttributeError, OSError):
        load1 = load5 = load15 = 0.0

    return {
        "client_id":            CLIENT_ID,
        "hostname":             platform.node(),
        "os":                   platform.system() + " " + platform.release(),
        "timestamp":            time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "cpu_percent":          round(cpu, 2),
        "mem_percent":          round(mem.percent, 2),
        "mem_used_mb":          round(mem.used / (1024 * 1024), 1),
        "mem_total_mb":         round(mem.total / (1024 * 1024), 1),
        "disk_percent":         round(disk.percent, 2),
        "disk_used_gb":         round(disk.used / (1024 ** 3), 2),
        "disk_total_gb":        round(disk.total / (1024 ** 3), 2),
        "net_bytes_sent":       net.bytes_sent,
        "net_bytes_recv":       net.bytes_recv,
        "net_packets_sent":     net.packets_sent,
        "net_packets_recv":     net.packets_recv,
        "throughput_sent_bps":  throughput_sent_bps,
        "throughput_recv_bps":  throughput_recv_bps,
        "load_avg_1":           round(load1, 3),
        "load_avg_5":           round(load5, 3),
        "load_avg_15":          round(load15, 3),
    }


def connect_with_retry():
    backoff = 2
    max_backoff = 60
    while True:
        try:
            log.info(f"Connecting to {SERVER_HOST}:{SERVER_PORT}")
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((SERVER_HOST, SERVER_PORT))
            s.settimeout(None)
            log.info(f"Connected. Client ID: {CLIENT_ID}")
            backoff = 2
            return s
        except (ConnectionRefusedError, OSError) as e:
            log.warning(f"Connection failed: {e}. Retrying in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)


def run():
    log.info(f"Agent starting | Server: {SERVER_HOST}:{SERVER_PORT} | Interval: {INTERVAL}s")
    sock   = None
    buffer = ""

    while True:
        try:
            if sock is None:
                sock = connect_with_retry()

            metrics = collect_metrics()
            payload = json.dumps(metrics) + "\n"

            # ── measure round-trip latency ─────────────────────────────────
            t_send = time.time()
            sock.sendall(payload.encode("utf-8"))

            sock.settimeout(5)
            latency_ms = None
            try:
                chunk = sock.recv(4096).decode("utf-8")
                t_recv     = time.time()
                latency_ms = round((t_recv - t_send) * 1000, 2)
                buffer    += chunk

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        resp   = json.loads(line)
                        alerts = resp.get("alerts", [])
                        if alerts:
                            for a in alerts:
                                log.warning(f"SERVER ALERT: {a}")
                        else:
                            log.info(
                                f"Sent | CPU:{metrics['cpu_percent']}% "
                                f"MEM:{metrics['mem_percent']}% "
                                f"DISK:{metrics['disk_percent']}% "
                                f"TX:{metrics['throughput_sent_bps']}B/s "
                                f"RX:{metrics['throughput_recv_bps']}B/s "
                                f"Latency:{latency_ms}ms"
                            )

            except socket.timeout:
                log.warning("No response from server within timeout")
            sock.settimeout(None)
            # ──────────────────────────────────────────────────────────────

            # send a small follow-up so the server can store latency
            if latency_ms is not None:
                followup = json.dumps({
                    "client_id":            CLIENT_ID,
                    "hostname":             platform.node(),
                    "timestamp":            time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                    "latency_ms":           latency_ms,
                    "throughput_sent_bps":  metrics["throughput_sent_bps"],
                    "throughput_recv_bps":  metrics["throughput_recv_bps"],
                    "_latency_update":      True,   # flag so server skips re-saving full metrics
                }) + "\n"
                try:
                    sock.sendall(followup.encode("utf-8"))
                except OSError:
                    pass

            time.sleep(INTERVAL)

        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            log.warning(f"Connection lost: {e}. Reconnecting...")
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
            sock   = None
            buffer = ""
            time.sleep(2)

        except KeyboardInterrupt:
            log.info("Agent stopped by user.")
            if sock:
                sock.close()
            break

        except Exception as e:
            log.error(f"Unexpected error: {e}")
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
            sock   = None
            buffer = ""
            time.sleep(5)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        SERVER_HOST = sys.argv[1]
    if len(sys.argv) > 2:
        SERVER_PORT = int(sys.argv[2])
    run()