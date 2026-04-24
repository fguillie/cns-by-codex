# CNS Architecture

## Deployment Model

CNS targets one Ubuntu 24.04 node and turns it into a combined control-plane and workload node.

The deployment sequence is:

1. Prepare the host for Kubernetes.
2. Install and configure `containerd`.
3. Install `kubeadm`, `kubelet`, and `kubectl`.
4. Bootstrap the cluster with `kubeadm init`.
5. Install Calico.
6. Install Helm.
7. Deploy the NVIDIA GPU Operator.

## Main Components

- `cns.sh`
  - Validates CLI input.
  - Selects the requested stack file.
  - Calls `ansible-playbook`.
- `stacks/*.yml`
  - Hold pinned component versions for each CNS stack.
- `ansible/roles/kubernetes`
  - Handles host prep, containerd, Kubernetes, and Calico.
- `ansible/roles/gpu_operator`
  - Handles Helm and GPU Operator deployment.

## Assumptions

- One node only.
- Ubuntu 24.04 only.
- One active cluster per target node.
- Internet-connected installation.
- Default Calico pod CIDR: `192.168.0.0/16`.

## Uninstall Model

The uninstall flow removes GPU Operator resources first, then tears down the Kubernetes cluster and the runtime components that CNS installed.
