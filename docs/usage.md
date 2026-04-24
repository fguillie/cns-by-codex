# Usage

## Inventory

Edit [`ansible/inventory/hosts.ini`](/nvidia/CODEX/CNS/ansible/inventory/hosts.ini:1) and set the target node details.

Example:

```ini
[cns_nodes]
gpu-node ansible_host=10.86.9.190

[cns_nodes:vars]
ansible_user=nvidia
ansible_password=nvidia
ansible_become=true
ansible_become_password=nvidia
ansible_python_interpreter=/usr/bin/python3
```

## Install

```bash
./cns.sh install 1.35
```

This runs `ansible/site.yml` with the selected stack definition.

## Uninstall

```bash
./cns.sh uninstall
```

## Direct Ansible Execution

You can bypass the shell wrapper if needed:

```bash
ansible-playbook -i ansible/inventory/hosts.ini ansible/site.yml \
  -e cns_action=install \
  -e cns_stack_version=1.35 \
  -e @stacks/1.35.yml
```

## Expected Outcome

After a successful install:

- `kubectl get nodes` shows one `Ready` node
- Calico pods are healthy
- GPU Operator resources exist in the `gpu-operator` namespace
