<!-- Introduces CNS and links users to installation, architecture, and troubleshooting docs. -->

# CNS

CNS deploys a single-node Kubernetes cluster on Ubuntu 24.04 with `kubeadm`, `containerd`, Calico, Helm, default NFS dynamic storage, default MetalLB load balancing, and optional NVIDIA GPU Operator support. GPU Operator installs use the stack-pinned CUDA driver container version by default, and `cns.sh` can override stack parameters for a specific install. The project is built around an Ansible playbook and a thin shell wrapper:

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
- Load balancing: MetalLB installed by default with a stack-pinned Layer 2 address pool
- GPU management: NVIDIA GPU Operator installed with Helm by default, using the stack-pinned CUDA driver container version unless overridden at install time

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
│   ├── roles/metallb/
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
| MetalLB | `0.15.3` | `0.15.3` | `0.15.3` | `0.15.3` |

The stack files under [`stacks/`](/nvidia/CODEX/CNS/stacks) are the single source of truth for component versions and default install choices. The CUDA driver container row is the default `driver.version` passed to GPU Operator; use `--set cuda_driver_container_version=<version>` only when a specific install needs a different driver container. The MetalLB address pool defaults to `10.86.6.94/32`; override `metallb_load_balancer_ip_range` when the target node needs a different load-balancer range.

## Prerequisites

- Ansible installed on the control machine
- `sshpass` installed if you use password-based SSH auth
- One reachable Ubuntu 24.04 target node
- Internet access from the target node to Kubernetes and GitHub artifact endpoints
- Internet access to Helm and the Kubernetes SIGs Helm repository when NFS provisioner is enabled
- Internet access to Helm and the MetalLB Helm repository when MetalLB is enabled
- Internet access to Helm and NVIDIA artifact endpoints when GPU Operator is enabled
- Internet access to the selected NVIDIA CUDA driver container image when GPU Operator is enabled
- NVIDIA GPU present on the target node for full GPU Operator validation
- When GPU Operator is enabled, CNS install removes active host CUDA/NVIDIA driver packages and disables Nouveau before Kubernetes deployment

## cns.sh Command

The `cns.sh` wrapper runs the CNS Ansible playbook with the selected action and stack parameter overrides.

| Command | Option or argument | Description |
| --- | --- | --- |
| `./cns.sh` | None | Prints command usage, install options, and supported stack versions. |
| `./cns.sh install <stack-version>` | `<stack-version>` | Deploys the selected CNS stack. Supported values are `1.36`, `1.35`, `1.34`, and `1.33`. |
| `./cns.sh install <stack-version> --set install_gpu_operator=false` | `--set install_gpu_operator=false` | Skips GPU Operator deployment, GPU Operator validation, and host CUDA/NVIDIA driver cleanup. |
| `./cns.sh install <stack-version> --set cuda_driver_container_version=<version>` | `--set cuda_driver_container_version=<version>` | Deploys the requested GPU Operator CUDA driver container version instead of the stack default. |
| `./cns.sh install <stack-version> --set install_nfs_provisioner=false` | `--set install_nfs_provisioner=false` | Skips NFS server setup, NFS export configuration, and NFS dynamic storage provisioner deployment. |
| `./cns.sh install <stack-version> --set install_metallb=false` | `--set install_metallb=false` | Skips MetalLB Helm deployment and Layer 2 address pool configuration. |
| `./cns.sh install <stack-version> --set metallb_load_balancer_ip_range=<range>` | `--set metallb_load_balancer_ip_range=<range>` | Uses the requested MetalLB address pool for LoadBalancer services. |
| `./cns.sh uninstall` | None | Removes the deployed CNS stack from the target node. This command does not require a stack version. |
| `./cns.sh help` | `help` | Prints command usage, install options, and supported stack versions. |
| `./cns.sh -h` | `-h` | Prints command usage, install options, and supported stack versions. |
| `./cns.sh --help` | `--help` | Prints command usage, install options, and supported stack versions. |

`--set` may be repeated and may override any top-level key defined in the selected stack file. The default install behavior uses the selected stack file's `install_gpu_operator`, `install_nfs_provisioner`, `install_metallb`, `cuda_driver_container_version`, and `metallb_load_balancer_ip_range` values. Install toggle values must be `true` or `false`. `--set cuda_driver_container_version=<version>` requires GPU Operator installation and cannot be combined with `--set install_gpu_operator=false`.

## Quick Start

1. Edit [`ansible/inventory/hosts.ini`](/nvidia/CODEX/CNS/ansible/inventory/hosts.ini:1) with your node details.
2. Review the stack file you want to deploy under [`stacks/`](/nvidia/CODEX/CNS/stacks).
3. Run:

```bash
chmod +x ./cns.sh
./cns.sh install 1.36
```

By default, CNS installs GPU Operator with the selected stack file's CUDA driver container version. CNS also enables the node as an NFS server, exports `/srv/cns/nfs`, deploys `nfs-subdir-external-provisioner`, creates the default `nfs-client` StorageClass, installs MetalLB, and configures a Layer 2 load-balancer address pool.

To skip GPU Operator installation and leave host GPU drivers unmanaged by CNS:

```bash
./cns.sh install 1.36 --set install_gpu_operator=false
```

To override the stack default CUDA driver container version used by GPU Operator:

```bash
./cns.sh install 1.36 --set cuda_driver_container_version=580.126.20
```

The requested version is passed to the GPU Operator Helm release as `driver.version`. If the version does not exist in NVIDIA's registry or is not compatible with the target node, GPU Operator deployment can fail during install validation.

To skip NFS server and dynamic storage provisioner setup:

```bash
./cns.sh install 1.36 --set install_nfs_provisioner=false
```

To skip MetalLB load-balancer setup:

```bash
./cns.sh install 1.36 --set install_metallb=false
```

To override the stack default MetalLB address pool:

```bash
./cns.sh install 1.36 --set metallb_load_balancer_ip_range=10.86.6.94/32
```

To remove the deployment:

```bash
./cns.sh uninstall
```

Uninstall removes the MetalLB release, NFS provisioner release, and CNS export configuration, but preserves PVC data under `/srv/cns/nfs`.

## Live Matrix Validation

The live validation script under [`tests/test_cns_matrix.py`](tests/test_cns_matrix.py) automates install, idempotency, validation, uninstall, and cleanup checks across selected CNS stacks. By default, each selected stack is one case. Repeating the same `--set` key adds one case per value, and multiple repeated keys are combined as a matrix.

Set the target password with an environment variable so it is not committed or stored in shell scripts:

```bash
CNS_TEST_PASSWORD='<target-password>' ./tests/test_cns_matrix.py --host 10.86.6.94 --user nvidia
```

By default, the script discovers all releases from `stacks/*.yml`, runs `./cns.sh uninstall` before the matrix starts, and tests each selected stack's default parameters. Each case runs install, immediate install rerun for idempotency, live validation, uninstall, cleanup validation, and an uninstall rerun.

Use `--stack` to limit releases and repeat `--set <key>=<value>` to override top-level parameters from the selected stack file. The matrix script uses the same stack-parameter model as `cns.sh`: unknown keys fail before remote work starts, and install toggle values must be `true` or `false`. Repeating an identical `--set` value is ignored so accidental duplicates do not add duplicate cases. To run a smaller smoke test without GPU Operator, NFS provisioner, or MetalLB:

```bash
CNS_TEST_PASSWORD='<target-password>' ./tests/test_cns_matrix.py \
  --host 10.86.6.94 \
  --user nvidia \
  --stack 1.36 \
  --set install_gpu_operator=false \
  --set install_nfs_provisioner=false \
  --set install_metallb=false \
  --fail-fast
```

Use `--set cuda_driver_container_version=<version>` to validate a specific GPU Operator CUDA driver container version. This override requires `install_gpu_operator=true`. Repeat `--set cuda_driver_container_version=<version>` to validate several driver containers in one run. Repeating another key, such as `containerd_version`, combines those values with the driver versions.

```bash
CNS_TEST_PASSWORD='<target-password>' ./tests/test_cns_matrix.py \
  --host 10.86.9.190 \
  --user nvidia \
  --stack 1.36 \
  --set install_gpu_operator=true \
  --set install_nfs_provisioner=false \
  --set install_metallb=true \
  --set cuda_driver_container_version=580.159.03 \
  --set cuda_driver_container_version=580.126.20 \
  --fail-fast
```

To validate GPU Operator and NFS provisioner together across multiple CUDA driver container and containerd versions:

```bash
CNS_TEST_PASSWORD='<target-password>' ./tests/test_cns_matrix.py \
  --host 10.86.6.94 \
  --user nvidia \
  --stack 1.36 \
  --set install_gpu_operator=true \
  --set install_nfs_provisioner=true \
  --set install_metallb=true \
  --set cuda_driver_container_version="580.126.20" \
  --set cuda_driver_container_version="580.159.03" \
  --set cuda_driver_container_version="595.71.05" \
  --set containerd_version="2.3.0" \
  --set containerd_version="2.2.3" \
  --set containerd_version="2.1.7" \
  --fail-fast
```

GPU-enabled validation checks the GPU Operator Helm chart version, the effective `driver.version`, `driver.kernelModuleType=proprietary`, the CNS driver kernel module ConfigMap name, `ClusterPolicy` readiness, node `nvidia.com/gpu` allocatable resources, Calico, node readiness, and non-root admin kubeconfig access. NFS-enabled validation checks the pinned NFS provisioner chart, default `nfs-client` StorageClass, and a bound test PVC. MetalLB-enabled validation checks the pinned MetalLB chart, the configured `IPAddressPool`, the `L2Advertisement`, and a temporary `LoadBalancer` Service external IP.

The script prints a table with each case result and writes detailed command logs to a temporary directory unless `--log-dir` is provided. Use `--no-pre-clean` to skip the initial uninstall, `--command-timeout` to adjust the per-command timeout, and `--wait-interval` to adjust validation polling. The control machine must have `python3`, `ansible-playbook`, `ssh`, and `sshpass` available.

## Matrix Dashboard Service

The matrix runner can be installed as a systemd service so it continues after the SSH session exits, with results published through a static dashboard on port `8888`:

```bash
sudo ./tools/install_cns_matrix_services.sh
sudo systemctl start --no-block cns-matrix.service
```

The installer creates `/etc/cns-matrix.env` with mode `0600` if it does not already exist. Review that file before starting a run:

```bash
CNS_TEST_PASSWORD='<target-password>'
CNS_MATRIX_HOST='10.86.6.94'
CNS_MATRIX_USER='nvidia'
CNS_MATRIX_ARGS=''
```

By default, `cns-matrix.service` runs the full matrix across all discovered stack files with stack defaults. Set `CNS_MATRIX_ARGS` to pass the same options accepted by `tests/test_cns_matrix.py`, for example `--stack 1.36 --set install_gpu_operator=false --set install_nfs_provisioner=false --set install_metallb=false --fail-fast`.

The dashboard is served from `/var/lib/cns-matrix/www` and links to durable run artifacts under `/var/lib/cns-matrix/runs`. Open `http://<control-host>:8888/` to watch progress, or inspect the service directly:

```bash
systemctl status cns-matrix.service
journalctl -u cns-matrix.service -f
```

The CUDA driver override matrix was last validated on May 13, 2026 against `10.86.9.190` for stack `1.36` with GPU Operator enabled, NFS provisioner disabled, and driver container versions `580.159.03`, `580.126.20`, and `595.71.05`; all install, rerun, validation, uninstall, and cleanup checks passed.

## Documentation

- [Usage](docs/usage.md)
- [Architecture](docs/architecture.md)
- [Troubleshooting](docs/troubleshooting.md)

## Version Sources

The versions currently pinned in this repository are defined by the CNS 26.5.0 stack update:

- Kubernetes support/release pages: `1.36.0`, `1.35.4`, `1.34.7`, `1.33.11`
- containerd GitHub releases: `2.3.0`
- Project Calico GitHub releases: `3.32.0`
- NVIDIA CUDA driver container: `580.126.20`
- Kubernetes SIGs nfs-subdir-external-provisioner chart: `4.0.18`
- MetalLB Helm chart: `0.15.3`
- NVIDIA GPU Operator docs/releases: `v26.3.1`
- Helm GitHub releases: `v4.1.4`
