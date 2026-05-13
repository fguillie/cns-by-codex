<!-- Introduces CNS and links users to installation, architecture, and troubleshooting docs. -->

# CNS

CNS deploys a single-node Kubernetes cluster on Ubuntu 24.04 with `kubeadm`, `containerd`, Calico, Helm, and the NVIDIA GPU Operator. The project is built around an Ansible playbook and a thin shell wrapper:

```bash
./cns.sh install <stack-version>
```

## Scope

- Target user: lab platform admins
- Target host: one Ubuntu 24.04 node
- Kubernetes bootstrap: `kubeadm`
- Container runtime: `containerd`
- CNI: Calico
- GPU management: NVIDIA GPU Operator installed with Helm

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
| `1.35` | `1.35.3` | `2.2.3` | `3.31.3` | `v26.3.1` | `v4.0.5` |
| `1.34` | `1.34.6` | `2.2.3` | `3.31.3` | `v26.3.1` | `v4.0.5` |
| `1.33` | `1.33.10` | `2.2.3` | `3.31.3` | `v26.3.1` | `v4.0.5` |

The stack files under [`stacks/`](/nvidia/CODEX/CNS/stacks) are the single source of truth.

## Prerequisites

- Ansible installed on the control machine
- `sshpass` installed if you use password-based SSH auth
- One reachable Ubuntu 24.04 target node
- Internet access from the target node to Kubernetes, GitHub, Helm, and NVIDIA artifact endpoints
- NVIDIA GPU present on the target node for full GPU Operator validation
- CNS install removes active host CUDA/NVIDIA driver packages and disables Nouveau before Kubernetes deployment

## Quick Start

1. Edit [`ansible/inventory/hosts.ini`](/nvidia/CODEX/CNS/ansible/inventory/hosts.ini:1) with your node details.
2. Review the stack file you want to deploy under [`stacks/`](/nvidia/CODEX/CNS/stacks).
3. Run:

```bash
chmod +x ./cns.sh
./cns.sh install 1.35
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

The versions currently pinned in this repository were selected from the latest upstream releases visible on April 24, 2026:

- Kubernetes support/release pages: `1.35.3`, `1.34.6`, `1.33.10`
- containerd GitHub releases: `2.2.3`
- Project Calico GitHub releases: `3.31.3`
- NVIDIA GPU Operator docs/releases: `v26.3.1`
- Helm GitHub releases: `v4.0.5`
