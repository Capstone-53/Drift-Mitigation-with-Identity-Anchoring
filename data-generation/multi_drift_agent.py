#!/usr/bin/env python3
"""
Multi-Type Drift Agent for Kubernetes
Generates diverse behavioral patterns across 4 drift categories:
1. Performance Drift
2. Resource Drift  
3. Communication Drift
4. Operational Drift
"""

import time
import random
import csv
import os
import psutil
from datetime import datetime
from kubernetes import client, config

class MultiTypeDriftAgent:
    def __init__(self, agent_id, drift_type="normal", drift_delay=60):
        """
        Initialize agent with specific drift type
        
        Args:
            agent_id: Unique identifier
            drift_type: One of ["normal", "performance", "resource", "communication", "operational"]
            drift_delay: Seconds before drift activates (default 60)
        """
        self.agent_id = agent_id
        self.drift_type = drift_type
        self.drift_delay = drift_delay
        self.start_time = time.time()
        self.drift_active = False
        
        # Operational state
        self.task_count = 0
        self.error_count = 0
        self.state = "IDLE"
        self.state_transitions = 0
        self.request_count = 0
        
        # Kubernetes client
        try:
            config.load_incluster_config()
            self.k8s_api = client.CoreV1Api()
        except:
            self.k8s_api = None
        
        # Data file
        self.data_file = "/data/multi_drift_dataset.csv"
        self._init_csv()
    
    def _init_csv(self):
        """
        Initialize CSV with headers ONLY if the file doesn't exist or is empty.
        This is what makes data collection resumable: if the pod/script restarts,
        we detect existing data on disk and skip re-writing the header, so
        _write_row() (opened in 'a' mode) just keeps appending after wherever
        we left off, instead of wiping previously collected records.
        """
        try:
            if os.path.exists(self.data_file) and os.path.getsize(self.data_file) > 0:
                print(f"[{self.agent_id}] Existing dataset found at {self.data_file} - resuming, header preserved")
                return  # Header already exists - do NOT overwrite
        except Exception:
            pass

        with open(self.data_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'agent_id', 'drift_type', 'drift_active',
                'pod_count', 'cpu_percent', 'memory_usage_mib', 'memory_percent',
                'network_tx_bytes', 'network_rx_bytes', 
                'disk_read_bytes', 'disk_write_bytes', 'open_file_descriptors',
                'task_count', 'request_rate_per_min', 'error_count', 'error_rate',
                'state_transitions', 'avg_task_execution_ms', 'current_state'
            ])
        print(f"[{self.agent_id}] Created new dataset with headers at {self.data_file}")
    
    def _check_drift_activation(self):
        """Activate drift after delay period"""
        elapsed = time.time() - self.start_time
        if not self.drift_active and elapsed > self.drift_delay and self.drift_type != "normal":
            self.drift_active = True
            print(f"[{self.agent_id}] DRIFT ACTIVATED: {self.drift_type}")
    
    def _execute_task(self):
        """Execute a single task with drift-specific behavior"""
        self.task_count += 1
        self.request_count += 1
        
        # Base execution time
        base_exec_time = random.uniform(50, 150)
        
        # Determine if task fails
        task_failed = False
        exec_time = base_exec_time
        
        if self.drift_active:
            if self.drift_type == "performance":
                # PERFORMANCE DRIFT: High error rate + slow execution
                if random.random() < 0.40:  # 40% error rate
                    task_failed = True
                    self.error_count += 1
                exec_time = random.uniform(300, 800)  # 2-5x slower
                
            elif self.drift_type == "resource":
                # RESOURCE DRIFT: Normal errors but resource intensive
                if random.random() < 0.08:  # 8% error rate (slightly elevated)
                    task_failed = True
                    self.error_count += 1
                exec_time = random.uniform(100, 200)
                # Resource intensive operations simulated separately
                
            elif self.drift_type == "communication":
                # COMMUNICATION DRIFT: Normal performance but network anomalies
                if random.random() < 0.10:  # 10% error rate
                    task_failed = True
                    self.error_count += 1
                exec_time = random.uniform(80, 180)
                # Network anomalies simulated separately
                
            elif self.drift_type == "operational":
                # OPERATIONAL DRIFT: Erratic behavior, state confusion
                if random.random() < 0.25:  # 25% error rate
                    task_failed = True
                    self.error_count += 1
                exec_time = random.uniform(150, 400)
                # Erratic state changes simulated separately
        else:
            # Normal behavior
            if random.random() < 0.05:  # 5% error rate
                task_failed = True
                self.error_count += 1
        
        # Simulate task execution
        time.sleep(exec_time / 1000.0)
        
        return exec_time, task_failed
    
    def _change_state(self):
        """Change operational state with drift-specific patterns"""
        states = ["IDLE", "PROCESSING", "WAITING", "ACTIVE", "SUSPENDED"]
        
        if self.drift_active and self.drift_type == "operational":
            # OPERATIONAL DRIFT: Erratic state transitions
            if random.random() < 0.7:  # 70% chance to change state
                self.state = random.choice(states)
                self.state_transitions += 1
        else:
            # Normal: Change state every 5 tasks
            if self.task_count % 5 == 0:
                self.state = states[(states.index(self.state) + 1) % len(states)]
                self.state_transitions += 1
    
    def _get_container_metrics(self):
        """Get container-level metrics with drift-specific amplification"""
        process = psutil.Process()
        
        # Base metrics
        cpu_base = process.cpu_percent(interval=0.1)
        mem_info = process.memory_info()
        mem_percent = process.memory_percent()
        
        net_io = psutil.net_io_counters()
        disk_io = psutil.disk_io_counters()
        
        open_fds = process.num_fds() if hasattr(process, 'num_fds') else len(process.open_files())
        
        # Apply drift-specific modifications
        if self.drift_active:
            if self.drift_type == "resource":
                # RESOURCE DRIFT: CPU/Memory/FD spikes
                cpu_percent = min(cpu_base * random.uniform(5, 10), 95)  # 5-10x CPU
                mem_usage_mib = mem_info.rss / (1024 * 1024) * random.uniform(2, 4)  # 2-4x memory
                open_fds = int(open_fds * random.uniform(3, 6))  # 3-6x file descriptors
                
                # Simulate resource-intensive operations
                disk_write = disk_io.write_bytes + random.randint(5_000_000, 15_000_000)
                
            elif self.drift_type == "communication":
                # COMMUNICATION DRIFT: Network anomalies
                cpu_percent = cpu_base
                mem_usage_mib = mem_info.rss / (1024 * 1024)
                
                # Network bursts and unusual patterns
                network_tx = net_io.bytes_sent + random.randint(10_000_000, 50_000_000)  # Large sends
                network_rx = net_io.bytes_recv + random.randint(2_000_000, 8_000_000)
                disk_write = disk_io.write_bytes
                
                return (cpu_percent, mem_usage_mib, mem_percent, 
                       network_tx, network_rx,
                       disk_io.read_bytes, disk_write, open_fds)
                
            elif self.drift_type == "performance":
                # PERFORMANCE DRIFT: Moderate resource usage
                cpu_percent = min(cpu_base * random.uniform(2, 4), 75)
                mem_usage_mib = mem_info.rss / (1024 * 1024) * random.uniform(1.5, 2.5)
                disk_write = disk_io.write_bytes + random.randint(1_000_000, 5_000_000)
                
            elif self.drift_type == "operational":
                # OPERATIONAL DRIFT: Variable resource usage
                cpu_percent = cpu_base * random.uniform(1.2, 3.5)
                mem_usage_mib = mem_info.rss / (1024 * 1024) * random.uniform(1.3, 2.2)
                disk_write = disk_io.write_bytes + random.randint(500_000, 3_000_000)
        else:
            # Normal metrics
            cpu_percent = cpu_base
            mem_usage_mib = mem_info.rss / (1024 * 1024)
            disk_write = disk_io.write_bytes
        
        return (cpu_percent, mem_usage_mib, mem_percent, 
               net_io.bytes_sent, net_io.bytes_recv,
               disk_io.read_bytes, disk_write, open_fds)
    
    def _get_pod_count(self):
        """Get total pod count in cluster"""
        if not self.k8s_api:
            return 0
        try:
            pods = self.k8s_api.list_pod_for_all_namespaces(watch=False)
            return len(pods.items)
        except:
            return 0
    
    def collect_metrics(self):
        """Collect comprehensive metrics"""
        # Check drift activation
        self._check_drift_activation()
        
        # Execute tasks
        execution_times = []
        for _ in range(6):  # 6 tasks per collection cycle
            exec_time, failed = self._execute_task()
            execution_times.append(exec_time)
            self._change_state()
        
        avg_execution = sum(execution_times) / len(execution_times)
        
        # Get metrics
        cpu, mem_mib, mem_pct, net_tx, net_rx, disk_r, disk_w, fds = self._get_container_metrics()
        pod_count = self._get_pod_count()
        
        # Calculate rates
        elapsed_minutes = (time.time() - self.start_time) / 60.0
        request_rate = self.request_count / max(elapsed_minutes, 0.1)
        error_rate = self.error_count / max(self.task_count, 1)
        
        # Record data
        record = [
            datetime.now().isoformat(),
            self.agent_id,
            self.drift_type,
            1 if self.drift_active else 0,
            pod_count,
            round(cpu, 2),
            round(mem_mib, 2),
            round(mem_pct, 2),
            net_tx,
            net_rx,
            disk_r,
            disk_w,
            fds,
            self.task_count,
            round(request_rate, 2),
            self.error_count,
            round(error_rate, 4),
            self.state_transitions,
            round(avg_execution, 2),
            self.state
        ]
        
        # Write to CSV
        try:
            with open(self.data_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(record)
        except Exception as e:
            print(f"Error writing to CSV: {e}")
        
        return record
    
    def run(self, duration=600, interval=10):
        """
        Run agent for specified duration
        
        Args:
            duration: Total runtime in seconds (default 600 = 10 minutes)
            interval: Collection interval in seconds (default 10)
        """
        print(f"[{self.agent_id}] Starting agent - Type: {self.drift_type}")
        print(f"[{self.agent_id}] Drift will activate after {self.drift_delay}s")
        
        end_time = time.time() + duration
        iteration = 0
        
        while time.time() < end_time:
            iteration += 1

            try:
                # Collect metrics (this is what appends the row to disk)
                record = self.collect_metrics()

                # Log status
                status = "DRIFT" if self.drift_active else "NORMAL"
                print(f"[{self.agent_id}] Iter {iteration} | {status} | "
                      f"Tasks: {self.task_count} | Errors: {self.error_count} | "
                      f"Error Rate: {record[16]:.2%} | Exec Time: {record[18]:.0f}ms")
            except Exception as e:
                # A single failed cycle should never kill the whole agent -
                # log it and keep going so data collection is continuous
                print(f"[{self.agent_id}] Collection cycle failed: {e}")

            # Wait for next iteration - this is what makes it "automatic":
            # no manual command needed per record, it just keeps looping
            time.sleep(interval)
        
        print(f"[{self.agent_id}] Completed - Total tasks: {self.task_count}")


if __name__ == "__main__":
    import sys
    
    # Get agent configuration from environment
    agent_id = os.getenv("AGENT_ID", "drift-agent-unknown")
    drift_type = os.getenv("DRIFT_TYPE", "normal")
    drift_delay = int(os.getenv("DRIFT_DELAY", "60"))
    duration = int(os.getenv("DURATION", "600"))
    
    print("=" * 60)
    print(f"Multi-Type Drift Agent")
    print(f"Agent ID: {agent_id}")
    print(f"Drift Type: {drift_type}")
    print(f"Drift Delay: {drift_delay}s")
    print(f"Duration: {duration}s")
    print("=" * 60)
    
    agent = MultiTypeDriftAgent(
        agent_id=agent_id,
        drift_type=drift_type,
        drift_delay=drift_delay
    )
    
    agent.run(duration=duration, interval=10)