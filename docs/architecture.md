<!-- Documents the CNS deployment model and component flow. -->

# CNS Architecture

## Deployment Model

CNS targets one Ubuntu 24.04 node and turns it into a combined control-plane and workload node.

The default deployment sequence is:

1. Run pre-checks to remove host CUDA/NVIDIA drivers and disable Nouveau.
2. Prepare the host for Kubernetes.
3. Install and configure `containerd`.
4. Install `kubeadm`, `kubelet`, and `kubectl`.
5. Bootstrap the cluster with `kubeadm init`.
6. Install Calico.
7. Install Helm.
8. Configure the node NFS server export.
9. Deploy `nfs-subdir-external-provisioner`.
10. Deploy the NVIDIA GPU Operator.

When `--no-gpu-operator` is passed to `cns.sh install`, CNS skips the driver cleanup pre-checks and GPU Operator deployment.
When `--no-nfs-provisioner` is passed, CNS skips NFS server setup and the NFS provisioner Helm release.

## Main Components

- `cns.sh`
  - Validates CLI input.
  - Selects the requested stack file.
  - Calls `ansible-playbook`.
- `stacks/*.yml`
  - Hold pinned component versions for each CNS stack.
- `ansible/roles/kubernetes`
  - Handles host prep, containerd, Kubernetes, and Calico.
- `ansible/roles/helm_client`
  - Installs the Helm client when a Helm-backed component is enabled.
- `ansible/roles/nfs_provisioner`
  - Enables the node NFS server and deploys the default storage provisioner when enabled.
- `ansible/roles/precheck`
  - Removes active host CUDA/NVIDIA driver packages and disables Nouveau before install when GPU Operator is enabled.
- `ansible/roles/gpu_operator`
  - Handles Helm and GPU Operator deployment when enabled.

## Assumptions

- One node only.
- Ubuntu 24.04 only.
- One active cluster per target node.
- Internet-connected installation.
- Default Calico pod CIDR: `192.168.0.0/16`.

## Uninstall Model

The uninstall flow removes GPU Operator resources first, removes NFS provisioner resources and CNS export configuration, then tears down the Kubernetes cluster and the runtime components that CNS installed. NFS data under `/srv/cns/nfs` is preserved.
