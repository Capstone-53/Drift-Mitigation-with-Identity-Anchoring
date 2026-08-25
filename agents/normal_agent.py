import time
import requests
import psutil
import os
import json
import random
from datetime import datetime
from collections import defaultdict

WINDOW_SECONDS = 10
OUTPUT_FILE = "/data/dataset.json"

request_counter = 0
error_counter = 0
domains_contacted = defaultdict(int)
last_action = None
state_transition_counter = 0

NORMAL_ACTIONS = [
    "list-pods",
    "get-namespaces",
    "read-configmap",
    "health-ping",
    "config-check",
]


def simulate_work():
    global request_counter, error_counter
    try:
        r = requests.get("http://httpbin.org/get", timeout=2)
        request_counter += 1
        return len(r.content)
    except Exception:
        error_counter += 1
        return 0


def collect_k8s_metrics():
    try:
        from kubernetes import client, config
        config.load_incluster_config()
        v1 = client.CoreV1Api()
        pods = v1.list_pod_for_all_namespaces()
        namespaces = v1.list_namespace()
        return {
            "k8s_pod_count": len(pods.items),
            "k8s_namespace_count": len(namespaces.items),
            "k8s_action": "list-pods+namespaces",
            "k8s_status": "ok"
        }
    except Exception as e:
        return {
            "k8s_pod_count": 0,
            "k8s_namespace_count": 0,
            "k8s_action": "list-pods+namespaces",
            "k8s_status": f"error:{e}"
        }


def pick_action():
    global last_action, state_transition_counter
    action = random.choice(NORMAL_ACTIONS)
    if action != last_action:
        state_transition_counter += 1
    last_action = action
    return action


def collect_metrics(start_time, bytes_received, identity, k8s, action):
    global request_counter, error_counter, domains_contacted
    global state_transition_counter

    cpu = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory().percent
    net_io = psutil.net_io_counters()
    exec_time = (time.time() - start_time) * 1000

    total_requests = request_counter + error_counter
    error_rate = (error_counter / total_requests) if total_requests > 0 else 0.0

    data = {
        "timestamp": datetime.utcnow().isoformat(),
        # Behavioral
        "error_rate": round(error_rate, 4),
        "avg_exec_time_ms": round(exec_time, 2),
        # Resource
        "cpu_percent": cpu,
        "memory_percent": memory,
        # Communication
        "network_bytes_sent": net_io.bytes_sent,
        "network_bytes_recv": net_io.bytes_recv,
        # Operational
        "state_transitions": state_transition_counter,
        "request_count": request_counter,
        "unique_domains": len(domains_contacted),
        # Kubernetes
        "k8s_pod_count": k8s["k8s_pod_count"],
        "k8s_namespace_count": k8s["k8s_namespace_count"],
        "k8s_action": action,
        "k8s_status": k8s["k8s_status"],
        # Identity
        "spiffe_id": identity["spiffe_id"] or "",
        "spiffe_present": int(identity["svid_valid"]),
        "svid_verified": int(identity["verified"]),
        "cert_expiry": identity["cert_expiry"] or "",
        "identity_source": identity["source"],
        # Label
        "label": "normal"
    }

    # Reset window counters
    request_counter = 0
    error_counter = 0
    state_transition_counter = 0
    domains_contacted.clear()

    return data


def main():
    print("=== Normal agent starting ===", flush=True)
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    from spiffe_client import fetch_and_verify_svid
    print("[INIT] Connecting to SPIRE workload API...", flush=True)

    while True:
        start = time.time()
        identity = fetch_and_verify_svid()
        print(f"[IDENTITY] verified={identity['verified']} "
              f"source={identity['source']} "
              f"id={identity['spiffe_id'] or 'none'}",
              flush=True)

        action = pick_action()
        simulate_work()
        k8s = collect_k8s_metrics()
        metrics = collect_metrics(start, 0, identity, k8s, action)

        with open(OUTPUT_FILE, "a") as f:
            f.write(json.dumps(metrics) + "\n")

        print(f"[METRICS] label={metrics['label']} "
              f"error_rate={metrics['error_rate']} "
              f"cpu={metrics['cpu_percent']} "
              f"state_transitions={metrics['state_transitions']}",
              flush=True)

        time.sleep(WINDOW_SECONDS)


if __name__ == "__main__":
    main()
