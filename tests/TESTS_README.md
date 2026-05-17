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
CNS_MATRIX_ARGS='--stack 1.36 --set install_gpu_operator=false --set install_nfs_provisioner=false --set install_metallb=false --fail-fast'
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
