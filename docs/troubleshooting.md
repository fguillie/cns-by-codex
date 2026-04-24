# Troubleshooting

## SSH Authentication Fails

- Verify the host IP, user, and password in `ansible/inventory/hosts.ini`.
- Install `sshpass` on the control node if you use `ansible_password`.

## Kubernetes Packages Not Found

- Confirm the target node has outbound access to `pkgs.k8s.io`.
- Confirm the selected stack file matches an active Kubernetes repository series.

## `kubeadm init` Fails

- Check `/var/log/syslog` and `journalctl -u kubelet`.
- Verify swap is disabled.
- Confirm the node hostname resolves correctly.

## Pre-Checks Fail

- If Nouveau is still active after cleanup, reboot the node and rerun `./cns.sh install <stack-version>`.
- If an NVIDIA/CUDA kernel module is still active after package removal, reboot the node and rerun the install.
- CNS removes host CUDA/NVIDIA driver packages before installing GPU Operator so the operator can manage the driver stack.

## Calico Pods Stay Pending

- Verify the pod CIDR is `192.168.0.0/16`.
- Check `kubectl get pods -n kube-system`.
- Inspect `kubectl describe pod -n kube-system <pod-name>`.

## GPU Operator Pods Fail

- Verify the node has an NVIDIA GPU.
- Check whether the host driver is already installed or whether the driver container can build/install.
- Inspect `kubectl get pods -n gpu-operator` and `kubectl logs -n gpu-operator <pod>`.

## Uninstall Leaves Residual State

Run:

```bash
sudo kubeadm reset -f
sudo rm -rf /etc/cni/net.d /var/lib/cni /var/lib/kubelet /etc/kubernetes
```

Use that only for manual cleanup when automated uninstall cannot finish because the cluster is already partially broken.
