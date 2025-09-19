# HVDeploy Management Agent

This repository contains a small bootstrap agent that prepares an Ubuntu 24.04
host for management by the HVDeploy control plane.  The agent performs the
following tasks:

* Installs QEMU/KVM, libvirt and the supporting tooling required to host
  virtual machines.
* Registers the server with the HVDeploy management API using an API key.  The
  API response is expected to provide the SSH public key(s) that should be
  authorised for management access.
* Creates (or reuses) a privileged management user, provisions the authorized
  keys returned by the API and enables passwordless sudo.
* Hardens the OpenSSH daemon to only allow public-key authentication, disables
  direct root logins and (optionally) terminates any other active SSH sessions.

The end result is a host that is ready for remote administration and, in later
iterations, remote virtual machine lifecycle operations.

## Requirements

* Ubuntu 24.04 LTS (fresh install is assumed).
* Root access to the server.
* Python 3.10 or newer available in the environment.
* An API key for `https://api.playrservers.com` that has permission to register
  the server and return the correct SSH public keys.

## Installation

Clone the repository to the target host and install the Python package:

```bash
pip install .
```

This exposes an `hvdeploy-agent` command line entry point.  Alternatively, the
script can be executed directly via `python -m management_agent.cli`.

## Usage

Run the agent as `root` on the target server:

```bash
sudo hvdeploy-agent --api-key YOUR_API_KEY_HERE
```

The API key can also be supplied through the `HVDEPLOY_API_KEY` environment
variable.  Additional options include:

* `--api-base-url`: Override the default API base (`https://api.playrservers.com`).
* `--api-endpoint`: Change the endpoint path used for registration
  (`/v1/servers/connect` by default).
* `--management-user`: Specify the management account to configure (defaults to
  `hvdeploy`).  The username returned by the API takes precedence when provided.
* `--management-groups`: Comma-separated list of groups to assign to the
  management user (default: `sudo,libvirt,kvm`).
* `--metadata`: Send additional key/value metadata to the API when registering
  the server.  The flag can be specified multiple times, e.g.
  `--metadata site=lon1 --metadata rack=R1`.
* `--skip-close-sessions`: Skip termination of other SSH sessions after
  configuration.

On completion the host will have the virtualization stack installed, the
OpenSSH daemon restricted to key-based access and the management user granted
full sudo privileges.

## Notes on API Integration

The agent expects the HVDeploy API to return a JSON payload containing one or
more SSH public keys (under the `authorized_keys`, `authorized_key` or
`public_key` fields).  Optional fields recognised by the agent include:

* `username`: Overrides the CLI/default management username.
* `close_other_sessions`: When `true` (default) the agent attempts to terminate
  other SSH connections after configuration.

If the API does not return any SSH keys the agent aborts without modifying the
system to avoid locking administrators out of the server.
