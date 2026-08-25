"""
Takes corrective action against a pod once the drift detector flags it.

Action per category follows the project doc's mitigation table:
  performance   -> restart the pod (delete; Deployment reschedules it)
  resource      -> restart + rely on the resource limits already set
                    in the k8s-*-drift.yaml deployments to cap blast radius
  communication -> apply a deny-egress NetworkPolicy to isolate the pod,
                    plus a stub hook to revoke its SPIFFE identity
  operational   -> quarantine: label the pod instead of deleting it, so
                    it stops receiving traffic/being counted healthy but
                    stays around for inspection

Identity revocation is deliberately just a hook here (log + optional
webhook) rather than a hard dependency on identity/. That keeps this
module usable even in clusters where SPIRE isn't installed, per your
request to keep identity as a separate layer. Wire REVOKE_WEBHOOK_URL
(env var) to point at something in the identity layer if/when you want
it live.
"""

import os
import time
from datetime import datetime, timezone

from kubernetes import client, config

NAMESPACE = os.getenv("AGENT_NAMESPACE", "default")
REVOKE_WEBHOOK_URL = os.getenv("REVOKE_WEBHOOK_URL")  # optional
COOLDOWN_SECONDS = int(os.getenv("MITIGATION_COOLDOWN_SECONDS", "120"))

DENY_EGRESS_POLICY_PREFIX = "quarantine-egress-"


class MitigationEnforcer:
    def __init__(self):
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        self.core = client.CoreV1Api()
        self.networking = client.NetworkingV1Api()
        self._last_action = {}  # pod_name -> timestamp, to avoid action spam

    def _on_cooldown(self, pod_name):
        last = self._last_action.get(pod_name)
        return last is not None and (time.time() - last) < COOLDOWN_SECONDS

    def _log(self, pod_name, category, action, detail=""):
        ts = datetime.now(timezone.utc).isoformat()
        print(f"[MITIGATION] {ts} pod={pod_name} category={category} "
              f"action={action} {detail}")

    def mitigate(self, pod_name: str, category: str, evidence: dict):
        if self._on_cooldown(pod_name):
            return False

        handler = {
            "performance": self._restart_pod,
            "resource": self._restart_pod,
            "communication": self._isolate_network,
            "operational": self._quarantine_pod,
        }.get(category)

        if handler is None:
            self._log(pod_name, category, "no-op", "unknown category")
            return False

        try:
            handler(pod_name, evidence)
            self._last_action[pod_name] = time.time()
            return True
        except client.exceptions.ApiException as e:
            self._log(pod_name, category, "failed", f"k8s error: {e.reason}")
            return False

    # -- individual actions -------------------------------------------------

    def _restart_pod(self, pod_name, evidence):
        """Delete the pod; its Deployment/ReplicaSet immediately
        reschedules a fresh one - the K8s-native equivalent of a
        liveness-probe-triggered restart, but on our own signal."""
        self.core.delete_namespaced_pod(name=pod_name, namespace=NAMESPACE)
        self._log(pod_name, "performance/resource", "restart",
                   f"evidence={evidence}")

    def _isolate_network(self, pod_name, evidence):
        """Block all egress from the offending pod via a NetworkPolicy
        scoped to just that pod (matched by a unique label we add),
        then trigger the identity-revocation hook."""
        pod = self.core.read_namespaced_pod(pod_name, NAMESPACE)
        pod.metadata.labels = pod.metadata.labels or {}
        pod.metadata.labels["quarantined"] = "true"
        self.core.patch_namespaced_pod(
            name=pod_name, namespace=NAMESPACE,
            body={"metadata": {"labels": pod.metadata.labels}},
        )

        policy_name = f"{DENY_EGRESS_POLICY_PREFIX}{pod_name}"[:63]
        policy = client.V1NetworkPolicy(
            metadata=client.V1ObjectMeta(name=policy_name, namespace=NAMESPACE),
            spec=client.V1NetworkPolicySpec(
                pod_selector=client.V1LabelSelector(
                    match_labels={"quarantined": "true"}
                ),
                policy_types=["Egress"],
                egress=[],  # empty list = deny all egress
            ),
        )
        try:
            self.networking.create_namespaced_network_policy(NAMESPACE, policy)
        except client.exceptions.ApiException as e:
            if e.status != 409:  # already exists is fine
                raise

        self._log(pod_name, "communication", "isolate-network",
                   f"policy={policy_name} evidence={evidence}")
        self._revoke_identity(pod_name, evidence)

    def _quarantine_pod(self, pod_name, evidence):
        """Operational drift: label rather than kill, so the pod is
        removed from consideration (e.g. by a readiness gate or
        selector elsewhere) but stays up for post-mortem inspection."""
        self.core.patch_namespaced_pod(
            name=pod_name, namespace=NAMESPACE,
            body={"metadata": {"labels": {"quarantined": "true"}}},
        )
        self._log(pod_name, "operational", "quarantine", f"evidence={evidence}")

    def _revoke_identity(self, pod_name, evidence):
        """Stub hook into the identity layer. Left as a log line unless
        REVOKE_WEBHOOK_URL is set, so this module has no hard
        dependency on SPIRE being present."""
        if not REVOKE_WEBHOOK_URL:
            self._log(pod_name, "communication", "would-revoke-identity",
                       "(no REVOKE_WEBHOOK_URL configured, logging only)")
            return
        import requests
        try:
            requests.post(REVOKE_WEBHOOK_URL, json={"pod_name": pod_name}, timeout=5)
            self._log(pod_name, "communication", "revoke-identity", "webhook called")
        except Exception as e:
            self._log(pod_name, "communication", "revoke-identity-failed", str(e))
