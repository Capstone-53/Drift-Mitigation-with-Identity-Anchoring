# Integrated pipeline: data generation -> real-time detection -> mitigation

Identity (SPIFFE/SPIRE, in `agents/` + `identity/`) stays a separate layer,
untouched. It's optionally hookable into mitigation via `REVOKE_WEBHOOK_URL`
but nothing here requires it to be running.

## Folder additions

```
agent-trust-v2/
├── agents/, identity/        <- unchanged, your existing identity layer
├── data-generation/          <- your friend's multi_drift_agent.py + k8s yamls
├── detection/
│   ├── feature_extractor.py  <- shared feature logic (offline + real-time)
│   ├── train_baseline.py     <- fits Isolation Forest on normal-only data
│   └── drift_detector.py     <- scores live rows, categorizes drift type
├── mitigation/
│   └── enforcer.py           <- restart / isolate / quarantine actions
└── monitor/
    ├── realtime_monitor.py   <- tails the CSV, wires detector -> enforcer
    ├── Dockerfile.monitor
    ├── rbac-monitor.yaml
    └── monitor-deployment.yaml
```

## Run order

**1. Build and deploy the data generators (your friend's project, unchanged):**

```bash
cd data-generation
docker build -t multi-drift-agent:latest -f Dockerfile.multi-drift .
kind load docker-image multi-drift-agent:latest --name agent-trust-v2
kubectl apply -f k8s-normal-agents.yaml
kubectl apply -f k8s-performance-drift.yaml
kubectl apply -f k8s-resource-drift.yaml
kubectl apply -f k8s-communication-drift.yaml
kubectl apply -f k8s-operational-drift.yaml
```

Let these run for a few minutes so `/mnt/agent-data/multi_drift_dataset.csv`
accumulates real rows - the baseline model needs at least ~30 rows of
`drift_type=normal` data (about 5 minutes from one normal agent) before
training means anything.

**2. Build the monitor image:**

```bash
cd ../  # agent-trust-v2 root - build context needs detection/, mitigation/, monitor/
docker build -t drift-monitor:latest -f monitor/Dockerfile.monitor .
kind load docker-image drift-monitor:latest --name agent-trust-v2
```

**3. Deploy the monitor (trains baseline in an initContainer, then watches):**

```bash
kubectl apply -f monitor/rbac-monitor.yaml
kubectl apply -f monitor/monitor-deployment.yaml
kubectl logs -f deploy/drift-monitor -c train-baseline   # watch training
kubectl logs -f deploy/drift-monitor -c monitor           # watch detection + mitigation
```

You'll see lines like:

```
[monitor] agent=performance-drift-agents-xxx score=-0.183 predicted=DRIFT  category=performance    ground_truth=DRIFT  (match)
[MITIGATION] 2026-08-24T06:03:12+00:00 pod=performance-drift-agents-xxx category=performance/resource action=restart evidence={...}
```

## Sanity checks

- `ground_truth` in the monitor logs comes straight from the CSV's
  `drift_type`/`drift_active` columns your friend's agent writes - it's
  there so you can eyeball precision/recall live, the same way the
  documented `BehavioralDriftNet` evaluation did offline.
- Start with `DRY_RUN: "true"` in `monitor-deployment.yaml` the first
  time you run this, so you can confirm the detector's calls look right
  before it starts actually deleting/patching pods.
- If you rebuild `multi-drift-agent:latest` or `drift-monitor:latest`,
  bump the tag (like we did for the identity fix) - `imagePullPolicy: Never`
  won't force Kind to notice a same-tag rebuild.
