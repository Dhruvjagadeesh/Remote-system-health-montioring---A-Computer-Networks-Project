#!/usr/bin/env python3
import subprocess
import sys
import os
import time
import socket

BASE = os.path.dirname(os.path.abspath(__file__))

def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"

def main():
    print("=" * 60)
    print("  Remote System Health Monitor - Server")
    print("=" * 60)

    ip = get_local_ip()
    print(f"\n  Your LAN IP: {ip}")
    print(f"  TCP Server  : {ip}:8080  (clients connect here)")
    print(f"  Dashboard   : http://{ip}:5000  (open in browser)")
    print(f"\n  On each client laptop, run:")
    print(f"    python client.py {ip}")
    print("=" * 60 + "\n")

    server_proc = subprocess.Popen(
        [sys.executable, os.path.join(BASE, "server", "server.py")],
        cwd=os.path.join(BASE, "server")
    )
    print(f"[+] TCP server started (PID {server_proc.pid})")

    time.sleep(1)

    dash_proc = subprocess.Popen(
        [sys.executable, os.path.join(BASE, "dashboard", "app.py")],
        cwd=os.path.join(BASE, "dashboard")
    )
    print(f"[+] Dashboard started  (PID {dash_proc.pid})")
    print(f"\n[*] Open browser: http://{ip}:5000")
    print("[*] Press Ctrl+C to stop all services\n")

    try:
        server_proc.wait()
    except KeyboardInterrupt:
        print("\n[!] Shutting down...")
        server_proc.terminate()
        dash_proc.terminate()
        server_proc.wait()
        dash_proc.wait()
        print("[+] Done.")

if __name__ == "__main__":
    main()
