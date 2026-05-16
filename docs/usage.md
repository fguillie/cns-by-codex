<!-- Explains CNS inventory setup and install/uninstall commands. -->

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
./cns.sh install 1.36
```

This runs `ansible/site.yml` with the selected stack definition and installs the GPU Operator by default.
It also installs an NFS server, exports `/srv/cns/nfs`, deploys `nfs-subdir-external-provisioner`, and creates the default `nfs-client` StorageClass.

To install only Kubernetes, containerd, and Calico without GPU Operator or host driver cleanup:

```bash
./cns.sh install 1.36 --set install_gpu_operator=false --set install_nfs_provisioner=false
```

To deploy a specific GPU Operator CUDA driver container version:

```bash
./cns.sh install 1.36 --set cuda_driver_container_version=580.126.20
```

To skip NFS server and dynamic storage provisioner setup:

```bash
./cns.sh install 1.36 --set install_nfs_provisioner=false
```

`--set` may override any top-level key defined in the selected stack file. Unknown keys fail before Ansible starts, and install toggle values must be `true` or `false`.

## Uninstall

```bash
./cns.sh uninstall
```

## Direct Ansible Execution

You can bypass the shell wrapper if needed:

```bash
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook -i ansible/inventory/hosts.ini ansible/site.yml \
  -e cns_action=install \
  -e cns_stack_version=1.36 \
  -e @stacks/1.36.yml
```

Set `-e install_gpu_operator=false` to skip GPU Operator deployment when running Ansible directly.
Set `-e cuda_driver_container_version=580.126.20` to override the stack default GPU Operator CUDA driver container version.
Set `-e install_nfs_provisioner=false` to skip NFS server and provisioner setup.
Place these override arguments after `-e @stacks/<version>.yml` so they take precedence over stack defaults.

## Expected Outcome

After a successful install:

- `kubectl get nodes` shows one `Ready` node
- Calico pods are healthy
- `kubectl get storageclass nfs-client` exists and is marked as the default StorageClass when NFS provisioner is enabled
- With GPU Operator enabled, GPU Operator resources exist in the `gpu-operator` namespace
- With `--set install_gpu_operator=false`, host GPU driver management remains outside CNS
- With `--set install_nfs_provisioner=false`, NFS server and dynamic storage management remain outside CNS
