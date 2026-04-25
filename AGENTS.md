# AGENTS

## Purpose

This repository builds and tests CNS, a single-node Kubernetes deployment for Ubuntu 24.04 using:

- `kubeadm`
- `containerd`
- Calico
- Helm
- NVIDIA GPU Operator

The main user entrypoint is [`cns.sh`](/nvidia/CODEX/CNS/cns.sh:1), which wraps the Ansible playbook under [`ansible/`](/nvidia/CODEX/CNS/ansible/site.yml:1).

## Source Of Truth

- Stack definitions live only in [`stacks/`](/nvidia/CODEX/CNS/stacks/1.35.yml:1).
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
- Keep install-time driver cleanup in the `precheck` role, before Kubernetes and GPU Operator roles.
- Do not rely on `ansible_user_dir` to locate the selected admin user's home when `become` is active; resolve `cns_admin_user` through the target passwd database.
- Do not remove the containerd drop-in import flow without revalidating GPU Operator on a live host. `v26.3.1` required:
  - `/etc/containerd/conf.d`
  - `imports = ["/etc/containerd/conf.d/*.toml"]` in `/etc/containerd/config.toml`
  - `operator.defaultRuntime=containerd` in the Helm install path

## Install Flow

- `./cns.sh install <stack-version>` sets `cns_action=install` and loads the selected stack file.
- The playbook validates the action and stack variables first.
- The `precheck` role runs only when `cns_action == 'install'`.
- The `precheck` role runs before the `kubernetes` and `gpu_operator` roles.
- The `precheck` role is not launched by `./cns.sh uninstall`.
- Inside the `precheck` role, cleanup is skipped when `/etc/kubernetes/admin.conf` already exists so steady-state install reruns do not remove GPU Operator-managed drivers.
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
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=install -e @stacks/1.35.yml
ansible-playbook --syntax-check -i ansible/inventory/hosts.ini ansible/site.yml -e cns_action=uninstall
```

If remote QA is requested and credentials are available, use the target inventory and validate:

1. `install`
2. immediate `install` rerun for idempotency
3. `uninstall`
4. `./cns.sh install <stack-version>`
5. immediate `./cns.sh install <stack-version>` rerun for wrapper idempotency
6. `./cns.sh uninstall`
7. immediate `./cns.sh uninstall` rerun for partially-clean uninstall idempotency

For live install validation, confirm:

- the node reaches `Ready`
- Calico pods are running
- the GPU Operator Helm release is deployed at the pinned chart version
- `ClusterPolicy` reaches `ready`
- the node reports `nvidia.com/gpu`
- the selected admin user can run `kubectl` without setting `KUBECONFIG`

The reference QA host used during development was `10.86.9.190`.
The wrapper path `cns.sh` was validated directly against that host for `1.35`.

## Idempotency Expectations

- An install rerun on an already deployed stack should converge cleanly.
- Uninstall should succeed even if the node is partially cleaned already.
- Avoid unconditional `kubectl apply`, `helm upgrade`, or config rewrites when the deployed state already matches the desired version.
- For the validated `1.35` path, a steady-state install rerun should complete with `changed=0`.

## Git

- Default branch is `main`.
- Current feature branch for GPU Operator `26.4.0` work is `26.4.0`.
- The `26.4.0` branch is published as `origin/26.4.0`.
- Keep commits focused and non-interactive.
- Do not rewrite history unless explicitly requested.
