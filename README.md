# Remote System Health Monitoring Service
CN Mini Project | PES2UG24AM066, AM046, AM053

---

## Project Structure

```
health-monitor/
    run_server.py         <- Launch everything from here
    requirements.txt
    server/
        server.py         <- TCP server + alert engine + SQLite storage
    dashboard/
        app.py            <- Flask web dashboard
        templates/
            index.html    <- Live monitoring UI
    client/
        client.py         <- Agent to run on each monitored laptop
```

---

## Setup on YOUR Laptop (Server)

```bash
pip install -r requirements.txt

python run_server.py
```

The script auto-detects your LAN IP and prints it. It starts:
- TCP server on port 8080
- Flask dashboard on port 5000

Open in browser: http://<YOUR_LAN_IP>:5000

---

## Setup on Each Client Laptop

Copy only `client/client.py` to each laptop.

```bash
pip install psutil

python client.py <SERVER_LAN_IP>
```

Example:
```bash
python client.py 192.168.1.15
```

The client will:
- Connect to the server via TCP
- Send CPU, memory, disk, network metrics every 10 seconds
- Auto-reconnect if the connection drops
- Show any threshold alerts received from server

---

## Environment Variables (optional overrides)

| Variable         | Default        | Description                  |
|------------------|----------------|------------------------------|
| MONITOR_SERVER   | 192.168.1.100  | Server IP                    |
| MONITOR_PORT     | 8080           | Server TCP port              |
| MONITOR_INTERVAL | 10             | Seconds between metric sends |
| CLIENT_ID        | auto-generated | Unique client identifier     |

Example:
```bash
MONITOR_SERVER=192.168.1.15 MONITOR_INTERVAL=5 python client.py
```

---

## Alert Thresholds (server.py)

```python
CPU_THRESHOLD  = 80.0   # percent
MEM_THRESHOLD  = 85.0   # percent
DISK_THRESHOLD = 90.0   # percent
```

Change these at the top of `server/server.py`.

---

## Email Alerts (optional)

In `server/server.py`, set:

```python
ALERT_EMAIL_ENABLED = True
SMTP_USER = "you@gmail.com"
SMTP_PASS = "your_app_password"
ALERT_TO  = "dest@example.com"
```

Use a Gmail App Password (not your main password).

---

## Performance Targets

| Metric      | Target         |
|-------------|----------------|
| Latency     | < 2s           |
| Throughput  | 100+ metrics/s |
| Clients     | Up to 10       |
| Interval    | 10s default    |

---

## CN Concepts Demonstrated

- TCP socket programming (AF_INET, SOCK_STREAM)
- Multi-threaded server (one thread per client)
- JSON data serialization over TCP
- Connection-oriented reliable communication
- Threshold-based alerting
- SQLite persistent storage
- HTTP serving via Flask (application layer)
