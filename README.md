<!-- Introduces CNS and links users to installation, architecture, and troubleshooting docs. -->

# CNS

CNS deploys a single-node Kubernetes cluster on Ubuntu 24.04 with `kubeadm`, `containerd`, Calico, Helm, and optional NVIDIA GPU Operator support. The project is built around an Ansible playbook and a thin shell wrapper:

```bash
./cns.sh install <stack-version>
```

## Scope

- Target user: lab platform admins
- Target host: one Ubuntu 24.04 node
- Kubernetes bootstrap: `kubeadm`
- Container runtime: `containerd`
- CNI: Calico
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
│   └── roles/gpu_operator/
└── docs/
```

## Stack Versions

CNS keeps one stack file per supported Kubernetes minor release branch.

| CNS stack | Kubernetes | Containerd | Calico | GPU Operator | Helm |
| --- | --- | --- | --- | --- | --- |
| `1.36` | `1.36.0` | `2.3.0` | `3.32.0` | `v26.3.1` | `v4.1.4` |
| `1.35` | `1.35.4` | `2.3.0` | `3.32.0` | `v26.3.1` | `v4.1.4` |
| `1.34` | `1.34.7` | `2.3.0` | `3.32.0` | `v26.3.1` | `v4.1.4` |
| `1.33` | `1.33.11` | `2.3.0` | `3.32.0` | `v26.3.1` | `v4.1.4` |

The stack files under [`stacks/`](/nvidia/CODEX/CNS/stacks) are the single source of truth.

## Prerequisites

- Ansible installed on the control machine
- `sshpass` installed if you use password-based SSH auth
- One reachable Ubuntu 24.04 target node
- Internet access from the target node to Kubernetes and GitHub artifact endpoints
- Internet access to Helm and NVIDIA artifact endpoints when GPU Operator is enabled
- NVIDIA GPU present on the target node for full GPU Operator validation
- When GPU Operator is enabled, CNS install removes active host CUDA/NVIDIA driver packages and disables Nouveau before Kubernetes deployment

## Quick Start

1. Edit [`ansible/inventory/hosts.ini`](/nvidia/CODEX/CNS/ansible/inventory/hosts.ini:1) with your node details.
2. Review the stack file you want to deploy under [`stacks/`](/nvidia/CODEX/CNS/stacks).
3. Run:

```bash
chmod +x ./cns.sh
./cns.sh install 1.36
```

To skip GPU Operator installation and leave host GPU drivers unmanaged by CNS:

```bash
./cns.sh install 1.36 --no-gpu-operator
```

To remove the deployment:

```bash
./cns.sh uninstall
```

## Documentation

- [Usage](docs/usage.md)
- [Architecture](docs/architecture.md)
- [Troubleshooting](docs/troubleshooting.md)

## Version Sources

The versions currently pinned in this repository are defined by the CNS 26.5.0 stack update:

- Kubernetes support/release pages: `1.36.0`, `1.35.4`, `1.34.7`, `1.33.11`
- containerd GitHub releases: `2.3.0`
- Project Calico GitHub releases: `3.32.0`
- NVIDIA GPU Operator docs/releases: `v26.3.1`
- Helm GitHub releases: `v4.1.4`
