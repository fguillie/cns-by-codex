<!-- Defines repository-specific instructions and constraints for CNS contributors. -->

# AGENTS

## Purpose

This repository builds and tests CNS, a single-node Kubernetes deployment for Ubuntu 24.04 using:

- `kubeadm`
- `containerd`
- Calico
- Helm when GPU Operator or NFS provisioner is enabled
- NFS server and `nfs-subdir-external-provisioner`, enabled by default and optional at install time
- NVIDIA GPU Operator, enabled by default and optional at install time

The main user entrypoint is [`cns.sh`](/nvidia/CODEX/CNS/cns.sh:1), which wraps the Ansible playbook under [`ansible/`](/nvidia/CODEX/CNS/ansible/site.yml:1).

## Source Of Truth

- Stack definitions live only in [`stacks/`](/nvidia/CODEX/CNS/stacks/1.36.yml:1).
- One file exists per supported Kubernetes minor branch.
- Do not hardcode component versions in the roles or shell wrapper when they belong in a stack file.
- Stack files also define default install choices with `install_gpu_operator` and `install_nfs_provisioner`.
- The currently pinned GPU Operator line is `v26.3.1`.
- The currently pinned CUDA driver container line is `580.126.20`.
- The currently pinned `nfs-subdir-external-provisioner` chart line is `4.0.18`.

## Repo Structure

- [`cns.sh`](/nvidia/CODEX/CNS/cns.sh:1): CLI wrapper for `install`, `uninstall`, and `help`
- [`ansible/site.yml`](/nvidia/CODEX/CNS/ansible/site.yml:1): top-level playbook
- [`ansible/roles/precheck`](/nvidia/CODEX/CNS/ansible/roles/precheck/tasks/main.yml:1): install-time driver cleanup and validation
- [`ansible/roles/kubernetes`](/nvidia/CODEX/CNS/ansible/roles/kubernetes/tasks/main.yml:1): host prep, containerd, Kubernetes, Calico
- [`ansible/roles/helm_client`](/nvidia/CODEX/CNS/ansible/roles/helm_client/tasks/main.yml:1): Helm client install and removal for Helm-backed roles
- [`ansible/roles/nfs_provisioner`](/nvidia/CODEX/CNS/ansible/roles/nfs_provisioner/tasks/main.yml:1): NFS server export and `nfs-subdir-external-provisioner` deployment
- [`ansible/roles/gpu_operator`](/nvidia/CODEX/CNS/ansible/roles/gpu_operator/tasks/main.yml:1): GPU Operator deployment
- [`ansible/inventory/hosts.ini`](/nvidia/CODEX/CNS/ansible/inventory/hosts.ini:1): user-edited target inventory
- [`tests/test_cns_matrix.py`](/nvidia/CODEX/CNS/tests/test_cns_matrix.py:1): live CNS release and option validation matrix
- [`docs/`](/nvidia/CODEX/CNS/docs/usage.md:1): user documentation

## Change Rules

- Preserve Ubuntu 24.04 as the supported OS unless the project scope changes explicitly.
- Preserve the split between the `kubernetes`, `helm_client`, `nfs_provisioner`, and `gpu_operator` roles.
- Keep `cns.sh uninstall` runnable without requiring a stack file.
- Prefer reproducible pinned versions over dynamic `latest` lookups at runtime.
- Do not add hidden version logic outside the stack manifests.
- Keep GPU Operator enabled by default unless the user explicitly requests otherwise.
- Expose GPU Operator opt-out only as an install-time stack parameter override, not as a separate stack manifest.
- Keep the CUDA driver container version in stack files, not in role logic or shell wrapper defaults.
- Expose CUDA driver container version override only as an install-time stack parameter override, not as a separate stack manifest.
- Do not add runtime registry lookups for CUDA driver container validation; invalid driver versions should fail through GPU Operator deployment.
- Keep `tests/test_cns_matrix.py --set` aligned with the stack parameter override behavior in `cns.sh`.
- Keep NFS provisioner enabled by default unless the user explicitly requests otherwise.
- Expose NFS provisioner opt-out only as an install-time stack parameter override, not as a separate stack manifest.
- Keep the NFS provisioner chart version in stack files, not in role logic.
- Preserve `/srv/cns/nfs` data on uninstall unless the user explicitly requests destructive cleanup.
- Keep install-time driver cleanup in the `precheck` role, before Kubernetes and GPU Operator roles, and run it only when GPU Operator installation is enabled.
- Do not rely on `ansible_user_dir` to locate the selected admin user's home when `become` is active; resolve `cns_admin_user` through the target passwd database.
- Do not remove the containerd drop-in import flow without revalidating GPU Operator on a live host. `v26.3.1` required:
  - `/etc/containerd/conf.d`
  - `imports = ["/etc/containerd/conf.d/*.toml"]` in `/etc/containerd/config.toml`
  - `operator.defaultRuntime=containerd` in the Helm install path
- Preserve `driver.kernelModuleType=proprietary` and the CNS GPU Operator kernel module config unless GPU Operator is revalidated on a live host. Driver containers `580.159.03` and `595.71.05` required `NVreg_EnableGpuFirmware=0` on the QA host because the open kernel module path failed when GSP firmware files were unavailable.
- Containerd `2.3.0` requires a root config with `version = 4`; a v2 root config breaks GPU Operator generated v4 drop-ins.
- On already initialized nodes with a v4 containerd config, do not rewrite `/etc/containerd/config.toml`; GPU Operator may have added runtime settings that must survive steady-state reruns.
- Do not remove the shared `helm_client` role unless GPU Operator and NFS provisioner Helm lifecycle ordering is revalidated. Helm must remain available until both Helm-backed components have been removed during uninstall.
- Keep artifact downloads tolerant of transient upstream slowness by using `cns_download_timeout` and retries for `get_url` tasks.

## File Headers

- Keep concise file-purpose header comments at the top of every tracked text file.
- For shell scripts, preserve the shebang as the first line and place the header comment immediately after it.
- For YAML files, preserve the `---` document marker as the first line and place the header comment after it.
- For Markdown files with visible titles, use a short HTML comment before the title instead of adding another visible heading.
- For templates and config files, use the native comment syntax for the rendered file format.

## Install Flow

- `./cns.sh install <stack-version>` sets `cns_action=install`, loads the selected stack file, and uses the stack file's `install_gpu_operator` and `install_nfs_provisioner` defaults.
- `./cns.sh install <stack-version> --set install_gpu_operator=true` is the explicit default-enabled GPU Operator form.
- `./cns.sh install <stack-version> --set install_gpu_operator=false` skips GPU Operator validation, skips the `precheck` role, and skips the `gpu_operator` role.
- `./cns.sh install <stack-version> --set cuda_driver_container_version=<version>` overrides the selected stack file's `cuda_driver_container_version` for that install.
- `./cns.sh install <stack-version> --set cuda_driver_container_version=<version>` requires GPU Operator installation and must fail before Ansible when combined with `--set install_gpu_operator=false`.
- `./cns.sh install <stack-version> --set install_nfs_provisioner=true` is the explicit default-enabled NFS provisioner form.
- `./cns.sh install <stack-version> --set install_nfs_provisioner=false` skips NFS server setup and skips the `nfs_provisioner` role.
- `./cns.sh install <stack-version> --set <key>=<value>` may override only top-level keys present in the selected stack file.
- `install_gpu_operator` and `install_nfs_provisioner` override values must be `true` or `false`.
- The playbook validates the action and stack variables first.
- The playbook validates `gpu_operator_version`, `cuda_driver_container_version`, and `helm_version` only when GPU Operator is enabled.
- The playbook validates `nfs_subdir_external_provisioner_version` and `helm_version` only when NFS provisioner is enabled.
- The `precheck` role runs only when `cns_action == 'install' and install_gpu_operator | bool`.
- The `precheck` role runs before the `kubernetes`, `nfs_provisioner`, and `gpu_operator` roles.
- The `precheck` role is not launched by `./cns.sh uninstall`.
- Inside the `precheck` role, cleanup is skipped when `/etc/kubernetes/admin.conf` already exists so steady-state install reruns do not remove GPU Operator-managed drivers.
- When GPU Operator is disabled, CNS must not remove existing host CUDA/NVIDIA driver packages or Nouveau state.
- When GPU Operator is enabled, the `gpu_operator` role passes the effective CUDA driver container version to Helm as `driver.version`.
- When GPU Operator is enabled, the `gpu_operator` role creates the CNS driver kernel module config and passes it to Helm with `driver.kernelModuleConfig.name`.
- GPU Operator uninstall and fresh-install precheck remove CNS-managed GPU Operator runtime artifacts such as `/run/nvidia`, `/usr/local/nvidia`, `/var/run/cdi`, and `/etc/containerd/conf.d/99-nvidia.toml`; this prevents stale driver container libraries from carrying across CUDA driver version changes.
- The `kubernetes` role resolves `cns_admin_home` from `getent passwd <cns_admin_user>` before install or uninstall tasks.
- The `helm_client` role runs after Kubernetes install and before any enabled Helm-backed component.
- The `nfs_provisioner` role installs `nfs-kernel-server`, exports `/srv/cns/nfs`, deploys the `nfs-subdir-external-provisioner` Helm release, and creates the default `nfs-client` StorageClass.
- Uninstall removes GPU Operator first, then NFS provisioner, then Helm, then Kubernetes.
- NFS uninstall removes the Helm release, namespace, StorageClass, and CNS export config, but preserves `/srv/cns/nfs`.

## Kubeconfig Handling

- Role-level `kubectl` and cluster-touching `helm` commands must use `KUBECONFIG=/etc/kubernetes/admin.conf`.
- Do not assume root's default kubeconfig is valid; stale `/root/.kube/config` files can point at an old cluster CA after reinstall.
- The selected non-root admin user's kubeconfig is copied from `/etc/kubernetes/admin.conf` to `{{ cns_admin_home }}/.kube/config`.
- If a legacy `/root/.kube/config` is owned by the selected non-root admin user, the `kubernetes` role may remove it as cleanup for older broken installs.

## Inventory

- [`ansible/inventory/hosts.ini`](/nvidia/CODEX/CNS/ansible/inventory/hosts.ini:1) is currently checked in with the tested QA host and working credentials.
- If that inventory is changed for local development, be explicit about whether the repo should keep the live QA values or revert to a commented example before committing.

## Testing

Minimum local checks before pushing:

```bash
bash -n ./cns.sh
python3 -m py_compile tests/test_cns_matrix.py
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=install -e @stacks/1.33.yml
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=install -e @stacks/1.34.yml
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=install -e @stacks/1.35.yml
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=install -e @stacks/1.36.yml
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=install -e @stacks/1.36.yml -e install_gpu_operator=false
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=install -e @stacks/1.36.yml -e install_nfs_provisioner=false
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=install -e @stacks/1.36.yml -e install_gpu_operator=false -e install_nfs_provisioner=false
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=install -e @stacks/1.36.yml -e cuda_driver_container_version=580.126.20
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=uninstall
```

The live matrix script can automate the remote QA install, rerun, validation, uninstall, and cleanup checks. It discovers supported releases from `stacks/*.yml`, creates a temporary inventory instead of editing `ansible/inventory/hosts.ini`, runs `./cns.sh uninstall` before the matrix by default, and expects the target password from `CNS_TEST_PASSWORD` or `--password`.

```bash
CNS_TEST_PASSWORD='<target-password>' ./tests/test_cns_matrix.py --host 10.86.6.94 --user nvidia
```

Use `--stack` to limit releases and `--set <key>=<value>` to override top-level stack parameters such as `install_gpu_operator`, `install_nfs_provisioner`, or `cuda_driver_container_version`. Use `--fail-fast` when iterating on a failure. Run one matrix invocation per CUDA driver container version when validating several values.

```bash
CNS_TEST_PASSWORD='<target-password>' ./tests/test_cns_matrix.py \
  --host 10.86.9.190 \
  --user nvidia \
  --stack 1.36 \
  --set install_gpu_operator=true \
  --set install_nfs_provisioner=false \
  --set cuda_driver_container_version=580.159.03 \
  --fail-fast
```

If full remote QA is requested and credentials are available, use the target inventory and validate:

1. `install --set install_gpu_operator=false --set install_nfs_provisioner=false`
2. immediate rerun for idempotency
3. validation and `uninstall`
4. `install --set install_gpu_operator=false --set install_nfs_provisioner=true`
5. immediate rerun, validation, and `uninstall`
6. `install --set install_gpu_operator=true --set install_nfs_provisioner=false`
7. immediate rerun, validation, and `uninstall`
8. `install --set install_gpu_operator=true --set install_nfs_provisioner=true`
9. immediate rerun, validation, `uninstall`, and immediate uninstall rerun for partially-clean uninstall idempotency

For live install validation with GPU Operator disabled, confirm:

- the node reaches `Ready`
- Calico pods are running
- the `gpu-operator` namespace is absent
- the selected admin user can run `kubectl` without setting `KUBECONFIG`

For live install validation with NFS provisioner enabled, confirm:

- the node reaches `Ready`
- Calico pods are running
- the NFS provisioner Helm release is deployed at the pinned chart version
- the `nfs-client` StorageClass exists and is marked as the default StorageClass
- a PVC without `storageClassName` binds successfully
- the selected admin user can run `kubectl` without setting `KUBECONFIG`

For live install validation with NFS provisioner disabled, confirm:

- the `nfs-provisioner` namespace is absent
- the `nfs-client` StorageClass is absent

For live install validation with GPU Operator enabled, confirm:

- the node reaches `Ready`
- Calico pods are running
- the GPU Operator Helm release is deployed at the pinned chart version
- the GPU Operator Helm release values include the expected `driver.version`
- the GPU Operator Helm release values include `driver.kernelModuleType=proprietary` and the CNS `driver.kernelModuleConfig.name`
- `ClusterPolicy` reaches `ready`
- the node reports `nvidia.com/gpu`
- the selected admin user can run `kubectl` without setting `KUBECONFIG`

The reference QA host used during development was `10.86.9.190`.
The wrapper path `cns.sh` was validated directly against that host for `1.35`.
The GPU Operator toggle was validated against `10.86.6.94` for stacks `1.33`, `1.34`, `1.35`, and `1.36` with GPU Operator enabled and disabled.
The 26.5.0 matrix was validated against `10.86.6.94` on May 9, 2026:

- `1.33`, `1.34`, `1.35`, and `1.36`
- GPU Operator disabled install, immediate rerun with `changed=0`, validation, and uninstall
- GPU Operator enabled install, immediate rerun with `changed=0`, validation, uninstall, and immediate uninstall rerun with `changed=0`
- final host state after validation: uninstalled, `containerd` inactive, `kubelet` inactive, and no `/etc/kubernetes/admin.conf`

The NFS provisioner matrix was validated against `10.86.6.94` on May 9-10, 2026 UTC:

- `1.33`, `1.34`, `1.35`, and `1.36`
- all combinations of `install_gpu_operator=true|false` and `install_nfs_provisioner=true|false`
- install, validation, immediate install rerun with `changed=0`, uninstall, and immediate uninstall rerun with `changed=0`
- NFS-enabled paths confirmed chart `nfs-subdir-external-provisioner-4.0.18`, default `nfs-client` StorageClass, and a bound test PVC
- GPU-enabled paths confirmed chart `gpu-operator-v26.3.1`, `ClusterPolicy` ready, and `nvidia.com/gpu` allocatable
- final host state after validation: uninstalled, `containerd` inactive, `kubelet` inactive, no `/etc/kubernetes/admin.conf`, CNS NFS export removed, and `/srv/cns/nfs` preserved

The CUDA driver override matrix was validated against `10.86.9.190` on May 13, 2026:

- stack `1.36`
- GPU Operator enabled and NFS provisioner disabled
- CUDA driver versions `580.159.03`, `580.126.20`, and `595.71.05`
- install, immediate install rerun, validation, uninstall, uninstall rerun, and cleanup checks passed for all three driver versions
- GPU-enabled paths confirmed chart `gpu-operator-v26.3.1`, requested `driver.version`, `driver.kernelModuleType=proprietary`, CNS `driver.kernelModuleConfig.name`, `ClusterPolicy` ready, and `nvidia.com/gpu` allocatable
- final host state after validation: uninstalled with `/run/nvidia`, `/usr/local/nvidia`, `/var/run/cdi`, and `/etc/containerd/conf.d/99-nvidia.toml` absent

## Idempotency Expectations

- An install rerun on an already deployed stack should converge cleanly.
- Uninstall should succeed even if the node is partially cleaned already.
- Avoid unconditional `kubectl apply`, `helm upgrade`, or config rewrites when the deployed state already matches the desired version.
- For the validated `1.35` path, a steady-state install rerun should complete with `changed=0`.
- For the validated GPU Operator toggle paths, steady-state reruns for each stack and option should complete with `changed=0`.
- GPU Operator reruns must not overwrite the GPU Operator managed containerd runtime configuration.
- GPU Operator reruns must not reinstall or upgrade the Helm release when the deployed chart version and `driver.version` already match the selected stack or install-time override.
- GPU Operator reruns must not reinstall or upgrade the Helm release when the deployed kernel module type and config name already match CNS defaults.
- Changing `cuda_driver_container_version` on a GPU-enabled install rerun should trigger a Helm upgrade so the requested `driver.version` is applied.
- For the validated NFS provisioner toggle paths, steady-state reruns for each stack and option should complete with `changed=0`.
- NFS provisioner reruns must not reinstall or upgrade the Helm release when the deployed chart version already matches the selected stack.
- Uninstall reruns should complete with `changed=0` after CNS has already been removed.

## Git

- Default branch is `main`.
- Current feature branch for CNS stack `26.5.0` work is `26.5.0`.
- The `26.5.0` branch is published as `origin/26.5.0`.
- Keep commits focused and non-interactive.
- Do not rewrite history unless explicitly requested.
