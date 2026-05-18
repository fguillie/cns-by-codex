<!-- Documents CNS test runner service deployment and dashboard usage. -->

# CNS Test Matrix Service

This document explains how to deploy the CNS matrix test runner on a different control server so `test_cns_matrix.py` keeps running after SSH logout and publishes results through the web dashboard.

## Prepare The Server

Install the runtime dependencies on the control server:

```bash
sudo apt-get update
sudo apt-get install -y python3 sshpass openssh-client
python3 -m pip install --user ansible
```

Make sure `ansible-playbook` is available to the service user. The service wrapper prepends `~/.local/bin` to `PATH`, so a per-user Ansible install works.

## Put The Repo In Place

Clone or copy the CNS repo to the control server, then run the installer from the final repo location:

```bash
cd /path/to/cns-by-codex
```

The installer writes the current repo path into the systemd units. If the repo is moved later, rerun the installer.

## Configure Target Settings

Create or edit `/etc/cns-matrix.env`:

```bash
sudo install -m 0600 -o root -g root /dev/null /etc/cns-matrix.env
sudo editor /etc/cns-matrix.env
```

Example:

```bash
CNS_TEST_PASSWORD='target-password'
CNS_MATRIX_HOST='10.86.9.190'
CNS_MATRIX_USER='nvidia'
CNS_MATRIX_ARGS=''
```

`CNS_MATRIX_ARGS` is optional. Leave it empty to run the full default matrix across all discovered stack files with stack defaults.

For a smaller smoke run:

```bash
CNS_MATRIX_ARGS='--stack 1.36 --set install_gpu_operator=false --set install_nfs_provisioner=false --set install_metallb=false --set install_envoy_gateway=false --fail-fast'
```

## Install The Services

From the repo root:

```bash
sudo ./tools/install_cns_matrix_services.sh
```

The installer creates:

- `/etc/systemd/system/cns-matrix.service`
- `/etc/systemd/system/cns-matrix-web.service`
- `/var/lib/cns-matrix/runs`
- `/var/lib/cns-matrix/state`
- `/var/lib/cns-matrix/www`

It also enables and starts `cns-matrix-web.service`.

## Start A Background Matrix Run

```bash
sudo systemctl start --no-block cns-matrix.service
```

The matrix run continues after the SSH session exits.

## Open The Dashboard

Open the dashboard from a browser:

```text
http://<control-server-ip>:8888/
```

If a firewall is enabled, allow port `8888`:

```bash
sudo ufw allow 8888/tcp
```

The dashboard shows the current run status, completed cases, pass/fail counts, phase status, and links to raw logs.

The dashboard also includes a **Run Configuration** section. Use it to select stacks, component toggles including Envoy Gateway, CUDA driver container versions, Envoy Gateway versions, containerd versions, MetalLB address range, fail-fast behavior, and pre-clean behavior. The **Start test** button queues the generated `CNS_MATRIX_ARGS` and starts `cns-matrix.service` when it is not already active; the **Stop test** button stops the active matrix run. Recent runs also include **Start** buttons to queue a rerun with the same arguments. The **Queued Runs** section shows pending runs and lets an operator remove a queued item before it starts. The installer enables these controls with a sudoers rule limited to `systemctl start`, `systemctl stop`, and `tools/set_cns_matrix_args.sh`.

The dashboard does not implement authentication. Restrict port `8888` with host firewall rules or lab network policy if the control host is reachable by untrusted clients.

## Monitor Or Debug

Use systemd to inspect the services:

```bash
systemctl status cns-matrix.service
systemctl status cns-matrix-web.service
journalctl -u cns-matrix.service -f
```

Raw logs and JSON summaries are kept under:

```text
/var/lib/cns-matrix/runs/
```

The latest run state is stored at:

```text
/var/lib/cns-matrix/state/current.json
```
