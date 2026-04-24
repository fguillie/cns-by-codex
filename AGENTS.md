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

## Repo Structure

- [`cns.sh`](/nvidia/CODEX/CNS/cns.sh:1): CLI wrapper for `install`, `uninstall`, and `help`
- [`ansible/site.yml`](/nvidia/CODEX/CNS/ansible/site.yml:1): top-level playbook
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

The reference QA host used during development was `10.86.9.190`.

## Idempotency Expectations

- An install rerun on an already deployed stack should converge cleanly.
- Uninstall should succeed even if the node is partially cleaned already.
- Avoid unconditional `kubectl apply`, `helm upgrade`, or config rewrites when the deployed state already matches the desired version.

## Git

- Default branch is `main`.
- Keep commits focused and non-interactive.
- Do not rewrite history unless explicitly requested.
