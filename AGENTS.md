<!-- Defines repository-specific instructions and constraints for CNS contributors. -->

# AGENTS

## Purpose

This repository builds and tests CNS, a single-node Kubernetes deployment for Ubuntu 24.04 using:

- `kubeadm`
- `containerd`
- Calico
- Helm when GPU Operator is enabled
- NVIDIA GPU Operator, enabled by default and optional at install time

The main user entrypoint is [`cns.sh`](/nvidia/CODEX/CNS/cns.sh:1), which wraps the Ansible playbook under [`ansible/`](/nvidia/CODEX/CNS/ansible/site.yml:1).

## Source Of Truth

- Stack definitions live only in [`stacks/`](/nvidia/CODEX/CNS/stacks/1.36.yml:1).
- One file exists per supported Kubernetes minor branch.
- Do not hardcode component versions in the roles or shell wrapper when they belong in a stack file.
- The currently pinned GPU Operator line is `v26.3.1`.

## Repo Structure

- [`cns.sh`](/nvidia/CODEX/CNS/cns.sh:1): CLI wrapper for `install`, `uninstall`, and `help`
- [`ansible/site.yml`](/nvidia/CODEX/CNS/ansible/site.yml:1): top-level playbook
- [`ansible/roles/precheck`](/nvidia/CODEX/CNS/ansible/roles/precheck/tasks/main.yml:1): install-time driver cleanup and validation
- [`ansible/roles/kubernetes`](/nvidia/CODEX/CNS/ansible/roles/kubernetes/tasks/main.yml:1): host prep, containerd, Kubernetes, Calico
- [`ansible/roles/gpu_operator`](/nvidia/CODEX/CNS/ansible/roles/gpu_operator/tasks/main.yml:1): Helm and GPU Operator deployment
- [`ansible/inventory/hosts.ini`](/nvidia/CODEX/CNS/ansible/inventory/hosts.ini:1): user-edited target inventory
- [`docs/`](/nvidia/CODEX/CNS/docs/usage.md:1): user documentation

## Change Rules

- Preserve Ubuntu 24.04 as the supported OS unless the project scope changes explicitly.
- Preserve the split between the `kubernetes` role and the `gpu_operator` role.
- Keep `cns.sh uninstall` runnable without requiring a stack file.
- Prefer reproducible pinned versions over dynamic `latest` lookups at runtime.
- Do not add hidden version logic outside the stack manifests.
- Keep GPU Operator enabled by default unless the user explicitly requests otherwise.
- Expose GPU Operator opt-out only as an install-time deployment choice, not as a separate stack manifest.
- Keep install-time driver cleanup in the `precheck` role, before Kubernetes and GPU Operator roles, and run it only when GPU Operator installation is enabled.
- Do not rely on `ansible_user_dir` to locate the selected admin user's home when `become` is active; resolve `cns_admin_user` through the target passwd database.
- Do not remove the containerd drop-in import flow without revalidating GPU Operator on a live host. `v26.3.1` required:
  - `/etc/containerd/conf.d`
  - `imports = ["/etc/containerd/conf.d/*.toml"]` in `/etc/containerd/config.toml`
  - `operator.defaultRuntime=containerd` in the Helm install path
- Containerd `2.3.0` requires a root config with `version = 4`; a v2 root config breaks GPU Operator generated v4 drop-ins.
- On already initialized nodes with a v4 containerd config, do not rewrite `/etc/containerd/config.toml`; GPU Operator may have added runtime settings that must survive steady-state reruns.
- Keep artifact downloads tolerant of transient upstream slowness by using `cns_download_timeout` and retries for `get_url` tasks.

## File Headers

- Keep concise file-purpose header comments at the top of every tracked text file.
- For shell scripts, preserve the shebang as the first line and place the header comment immediately after it.
- For YAML files, preserve the `---` document marker as the first line and place the header comment after it.
- For Markdown files with visible titles, use a short HTML comment before the title instead of adding another visible heading.
- For templates and config files, use the native comment syntax for the rendered file format.

## Install Flow

- `./cns.sh install <stack-version>` sets `cns_action=install`, loads the selected stack file, and installs GPU Operator by default.
- `./cns.sh install <stack-version> --gpu-operator` is the explicit default-enabled form.
- `./cns.sh install <stack-version> --no-gpu-operator` sets `cns_gpu_operator_enabled=false`, skips GPU Operator validation, skips the `precheck` role, and skips the `gpu_operator` role.
- The playbook validates the action and stack variables first.
- The playbook validates `gpu_operator_version` and `helm_version` only when GPU Operator is enabled.
- The `precheck` role runs only when `cns_action == 'install' and cns_gpu_operator_enabled | bool`.
- The `precheck` role runs before the `kubernetes` and `gpu_operator` roles.
- The `precheck` role is not launched by `./cns.sh uninstall`.
- Inside the `precheck` role, cleanup is skipped when `/etc/kubernetes/admin.conf` already exists so steady-state install reruns do not remove GPU Operator-managed drivers.
- When GPU Operator is disabled, CNS must not remove existing host CUDA/NVIDIA driver packages or Nouveau state.
- The `kubernetes` role resolves `cns_admin_home` from `getent passwd <cns_admin_user>` before install or uninstall tasks.

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
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=install -e @stacks/1.33.yml
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=install -e @stacks/1.34.yml
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=install -e @stacks/1.35.yml
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=install -e @stacks/1.36.yml
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=install -e cns_gpu_operator_enabled=false -e @stacks/1.36.yml
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=uninstall
```

If remote QA is requested and credentials are available, use the target inventory and validate:

1. `install --no-gpu-operator`
2. immediate `install --no-gpu-operator` rerun for idempotency
3. `uninstall`
4. `./cns.sh install <stack-version> --gpu-operator`
5. immediate `./cns.sh install <stack-version> --gpu-operator` rerun for wrapper idempotency
6. `./cns.sh uninstall`
7. immediate `./cns.sh uninstall` rerun for partially-clean uninstall idempotency

For live install validation with GPU Operator disabled, confirm:

- the node reaches `Ready`
- Calico pods are running
- the `gpu-operator` namespace is absent
- the selected admin user can run `kubectl` without setting `KUBECONFIG`

For live install validation with GPU Operator enabled, confirm:

- the node reaches `Ready`
- Calico pods are running
- the GPU Operator Helm release is deployed at the pinned chart version
- `ClusterPolicy` reaches `ready`
- the node reports `nvidia.com/gpu`
- the selected admin user can run `kubectl` without setting `KUBECONFIG`

The reference QA host used during development was `10.86.9.190`.
The wrapper path `cns.sh` was validated directly against that host for `1.35`.
The GPU Operator toggle was validated against `10.86.6.94` for stacks `1.33`, `1.34`, `1.35`, and `1.36` with both `--gpu-operator` and `--no-gpu-operator`.
The 26.5.0 matrix was validated against `10.86.6.94` on May 9, 2026:

- `1.33`, `1.34`, `1.35`, and `1.36`
- `--no-gpu-operator` install, immediate rerun with `changed=0`, validation, and uninstall
- `--gpu-operator` install, immediate rerun with `changed=0`, validation, uninstall, and immediate uninstall rerun with `changed=0`
- final host state after validation: uninstalled, `containerd` inactive, `kubelet` inactive, and no `/etc/kubernetes/admin.conf`

## Idempotency Expectations

- An install rerun on an already deployed stack should converge cleanly.
- Uninstall should succeed even if the node is partially cleaned already.
- Avoid unconditional `kubectl apply`, `helm upgrade`, or config rewrites when the deployed state already matches the desired version.
- For the validated `1.35` path, a steady-state install rerun should complete with `changed=0`.
- For the validated GPU Operator toggle paths, steady-state reruns for each stack and option should complete with `changed=0`.
- GPU Operator reruns must not overwrite the GPU Operator managed containerd runtime configuration.

## Git

- Default branch is `main`.
- Current feature branch for CNS stack `26.5.0` work is `26.5.0`.
- The `26.5.0` branch is published as `origin/26.5.0`.
- Keep commits focused and non-interactive.
- Do not rewrite history unless explicitly requested.
