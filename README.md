<!-- Introduces CNS and links users to installation, architecture, and troubleshooting docs. -->

# CNS

CNS deploys a single-node Kubernetes cluster on Ubuntu 24.04 with `kubeadm`, `containerd`, Calico, Helm, default NFS dynamic storage, and optional NVIDIA GPU Operator support. The project is built around an Ansible playbook and a thin shell wrapper:

```bash
./cns.sh install <stack-version>
```

## Scope

- Target user: lab platform admins
- Target host: one Ubuntu 24.04 node
- Kubernetes bootstrap: `kubeadm`
- Container runtime: `containerd`
- CNI: Calico
- Dynamic storage: NFS server and `nfs-subdir-external-provisioner` installed by default
- GPU management: NVIDIA GPU Operator installed with Helm by default

## Repository Layout

```text
.
├── cns.sh
├── stacks/
├── ansible/
│   ├── inventory/hosts.ini
│   ├── group_vars/all.yml
│   ├── roles/precheck/
│   ├── roles/kubernetes/
│   ├── roles/helm_client/
│   ├── roles/nfs_provisioner/
│   └── roles/gpu_operator/
└── docs/
```

## Stack Versions

CNS keeps one stack file per supported Kubernetes minor release branch.

| Component | CNS stack `1.36` | CNS stack `1.35` | CNS stack `1.34` | CNS stack `1.33` |
| --- | --- | --- | --- | --- |
| Kubernetes | `1.36.0` | `1.35.4` | `1.34.7` | `1.33.11` |
| Containerd | `2.3.0` | `2.3.0` | `2.3.0` | `2.3.0` |
| Calico | `3.32.0` | `3.32.0` | `3.32.0` | `3.32.0` |
| GPU Operator | `v26.3.1` | `v26.3.1` | `v26.3.1` | `v26.3.1` |
| CUDA driver container | `580.126.20` | `580.126.20` | `580.126.20` | `580.126.20` |
| Helm | `v4.1.4` | `v4.1.4` | `v4.1.4` | `v4.1.4` |
| NFS provisioner | `4.0.18` | `4.0.18` | `4.0.18` | `4.0.18` |

The stack files under [`stacks/`](/nvidia/CODEX/CNS/stacks) are the single source of truth.

## Prerequisites

- Ansible installed on the control machine
- `sshpass` installed if you use password-based SSH auth
- One reachable Ubuntu 24.04 target node
- Internet access from the target node to Kubernetes and GitHub artifact endpoints
- Internet access to Helm and the Kubernetes SIGs Helm repository when NFS provisioner is enabled
- Internet access to Helm and NVIDIA artifact endpoints when GPU Operator is enabled
- NVIDIA GPU present on the target node for full GPU Operator validation
- When GPU Operator is enabled, CNS install removes active host CUDA/NVIDIA driver packages and disables Nouveau before Kubernetes deployment

## cns.sh Command

The `cns.sh` wrapper runs the CNS Ansible playbook with the selected action and install options.

| Command | Option or argument | Description |
| --- | --- | --- |
| `./cns.sh` | None | Prints command usage, install options, and supported stack versions. |
| `./cns.sh install <stack-version>` | `<stack-version>` | Deploys the selected CNS stack. Supported values are `1.36`, `1.35`, `1.34`, and `1.33`. |
| `./cns.sh install <stack-version> --gpu-operator` | `--gpu-operator` | Installs the NVIDIA GPU Operator. This is the default install behavior. |
| `./cns.sh install <stack-version> --no-gpu-operator` | `--no-gpu-operator` | Skips GPU Operator deployment, GPU Operator validation, and host CUDA/NVIDIA driver cleanup. |
| `./cns.sh install <stack-version> --nfs-provisioner` | `--nfs-provisioner` | Installs the NFS server and `nfs-subdir-external-provisioner`. This is the default install behavior. |
| `./cns.sh install <stack-version> --no-nfs-provisioner` | `--no-nfs-provisioner` | Skips NFS server setup, NFS export configuration, and NFS dynamic storage provisioner deployment. |
| `./cns.sh uninstall` | None | Removes the deployed CNS stack from the target node. This command does not require a stack version. |
| `./cns.sh help` | `help` | Prints command usage, install options, and supported stack versions. |
| `./cns.sh -h` | `-h` | Prints command usage, install options, and supported stack versions. |
| `./cns.sh --help` | `--help` | Prints command usage, install options, and supported stack versions. |

Install options may be combined. The default install behavior is equivalent to `./cns.sh install <stack-version> --gpu-operator --nfs-provisioner`.

## Quick Start

1. Edit [`ansible/inventory/hosts.ini`](/nvidia/CODEX/CNS/ansible/inventory/hosts.ini:1) with your node details.
2. Review the stack file you want to deploy under [`stacks/`](/nvidia/CODEX/CNS/stacks).
3. Run:

```bash
chmod +x ./cns.sh
./cns.sh install 1.36
```

By default, CNS also enables the node as an NFS server, exports `/srv/cns/nfs`, deploys `nfs-subdir-external-provisioner`, and creates the default `nfs-client` StorageClass.

To skip GPU Operator installation and leave host GPU drivers unmanaged by CNS:

```bash
./cns.sh install 1.36 --no-gpu-operator
```

To skip NFS server and dynamic storage provisioner setup:

```bash
./cns.sh install 1.36 --no-nfs-provisioner
```

To remove the deployment:

```bash
./cns.sh uninstall
```

Uninstall removes the NFS provisioner release and CNS export configuration, but preserves PVC data under `/srv/cns/nfs`.

## Live Matrix Validation

The live validation script under [`tests/test_cns_matrix.py`](tests/test_cns_matrix.py) automates install, idempotency, validation, uninstall, and cleanup checks across every CNS stack and every GPU Operator/NFS provisioner option combination.

Set the target password with an environment variable so it is not committed or stored in shell scripts:

```bash
CNS_TEST_PASSWORD='<target-password>' ./tests/test_cns_matrix.py --host 10.86.6.94 --user nvidia
```

By default, the script discovers all releases from `stacks/*.yml` and runs the full matrix. To run a smaller smoke test:

```bash
CNS_TEST_PASSWORD='<target-password>' ./tests/test_cns_matrix.py \
  --host 10.86.6.94 \
  --user nvidia \
  --stack 1.36 \
  --gpu disabled \
  --nfs disabled \
  --fail-fast
```

The script prints a table with each case result and writes detailed command logs to a temporary directory unless `--log-dir` is provided. The control machine must have `python3`, `ansible-playbook`, `ssh`, and `sshpass` available.

## Documentation

- [Usage](docs/usage.md)
- [Architecture](docs/architecture.md)
- [Troubleshooting](docs/troubleshooting.md)

## Version Sources

The versions currently pinned in this repository are defined by the CNS 26.5.0 stack update:

- Kubernetes support/release pages: `1.36.0`, `1.35.4`, `1.34.7`, `1.33.11`
- containerd GitHub releases: `2.3.0`
- Project Calico GitHub releases: `3.32.0`
- Kubernetes SIGs nfs-subdir-external-provisioner chart: `4.0.18`
- NVIDIA GPU Operator docs/releases: `v26.3.1`
- Helm GitHub releases: `v4.1.4`
