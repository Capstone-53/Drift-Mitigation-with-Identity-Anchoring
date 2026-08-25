#!/bin/bash
# Complete Multi-Type Drift Agent Deployment Script

set -e

echo "=========================================="
echo "Multi-Type Drift Agent Deployment"
echo "=========================================="

# Configuration
IMAGE_NAME="multi-drift-agent:latest"
DATA_DIR="/agent-data"

echo ""
echo "Step 1: Creating local data directory..."
sudo mkdir -p $DATA_DIR
sudo chmod 777 $DATA_DIR

echo ""
echo "Step 2: Building Docker image..."
docker build -t $IMAGE_NAME -f Dockerfile.multi-drift .

echo ""
echo "Step 3: Loading image into Minikube..."
minikube image load $IMAGE_NAME

echo ""
echo "Step 4: Starting Minikube mount (in background)..."
# Kill any existing mount processes
pkill -f "minikube mount" || true
sleep 2

# Start mount in background
nohup minikube mount $DATA_DIR:/mnt/agent-data > /tmp/minikube-mount.log 2>&1 &
MOUNT_PID=$!
echo "Mount started with PID: $MOUNT_PID"
sleep 5

echo ""
echo "Step 5: Creating ServiceAccount and RBAC..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: agent-sa
  namespace: default
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: agent-role
rules:
- apiGroups: [""]
  resources: ["pods", "namespaces", "configmaps", "services"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: agent-rolebinding
subjects:
- kind: ServiceAccount
  name: agent-sa
  namespace: default
roleRef:
  kind: ClusterRole
  name: agent-role
  apiGroup: rbac.authorization.k8s.io
EOF

echo ""
echo "Step 6: Deploying agents..."

# Deploy normal agents
echo "  - Deploying 3 normal agents..."
kubectl apply -f k8s-normal-agents.yaml

# Deploy drift agents
echo "  - Deploying 2 performance drift agents..."
kubectl apply -f k8s-performance-drift.yaml

echo "  - Deploying 2 resource drift agents..."
kubectl apply -f k8s-resource-drift.yaml

echo "  - Deploying 2 communication drift agents..."
kubectl apply -f k8s-communication-drift.yaml

echo "  - Deploying 2 operational drift agents..."
kubectl apply -f k8s-operational-drift.yaml

echo ""
echo "Step 7: Waiting for pods to start..."
sleep 10

echo ""
echo "=========================================="
echo "Deployment Summary"
echo "=========================================="
kubectl get pods -l app=agent

echo ""
echo "Agent Distribution:"
echo "  - Normal:         3 agents"
echo "  - Performance:    2 agents (drift type 1)"
echo "  - Resource:       2 agents (drift type 2)"
echo "  - Communication:  2 agents (drift type 3)"
echo "  - Operational:    2 agents (drift type 4)"
echo "  - TOTAL:          11 agents"

echo ""
echo "Data collection location: $DATA_DIR/multi_drift_dataset.csv"
echo ""
echo "Monitoring commands:"
echo "  Watch pods:      kubectl get pods -l app=agent -w"
echo "  View logs:       kubectl logs -l app=agent --tail=20 -f"
echo "  Check data:      sudo tail -f $DATA_DIR/multi_drift_dataset.csv"
echo "  Pod by type:     kubectl get pods -l drift-category=performance"
echo ""
echo "Drift will activate after 60 seconds in each drift agent."
echo "Agents will run for 1 hour (3600 seconds)."
echo ""

# Monitor function
monitor_data() {
    echo "=========================================="
    echo "Monitoring Data Collection"
    echo "=========================================="
    echo "Press Ctrl+C to stop monitoring"
    echo ""
    
    while true; do
        if [ -f "$DATA_DIR/multi_drift_dataset.csv" ]; then
            LINES=$(wc -l < "$DATA_DIR/multi_drift_dataset.csv")
            NORMAL=$(grep ",normal," "$DATA_DIR/multi_drift_dataset.csv" | wc -l || echo 0)
            PERF=$(grep ",performance," "$DATA_DIR/multi_drift_dataset.csv" | wc -l || echo 0)
            RESOURCE=$(grep ",resource," "$DATA_DIR/multi_drift_dataset.csv" | wc -l || echo 0)
            COMM=$(grep ",communication," "$DATA_DIR/multi_drift_dataset.csv" | wc -l || echo 0)
            OPER=$(grep ",operational," "$DATA_DIR/multi_drift_dataset.csv" | wc -l || echo 0)
            
            clear
            echo "Data Collection Status"
            echo "======================"
            echo "Total Records:        $LINES"
            echo ""
            echo "By Drift Type:"
            echo "  Normal:             $NORMAL"
            echo "  Performance:        $PERF"
            echo "  Resource:           $RESOURCE"
            echo "  Communication:      $COMM"
            echo "  Operational:        $OPER"
            echo ""
            echo "Latest 5 records:"
            echo "----------------"
            sudo tail -5 "$DATA_DIR/multi_drift_dataset.csv" | column -t -s ','
        else
            echo "Waiting for data file to be created..."
        fi
        sleep 5
    done
}

echo "Would you like to monitor data collection? (y/n)"
read -r response
if [[ "$response" =~ ^[Yy]$ ]]; then
    monitor_data
fi
