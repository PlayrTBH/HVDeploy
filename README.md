# HVDeploy Management Agent (Assume this is garbage, do not use)

This repository contains a small bootstrap agent that prepares an Ubuntu 24.04
host for management by the HVDeploy control plane.  The agent performs the
following tasks:

* Installs QEMU/KVM, libvirt and the supporting tooling required to host
  virtual machines.
* Queries the management API for the account that owns the API key and retrieves
  the SSH public keys that should be authorised for management access.
* Registers the server with the HVDeploy management API using the resolved
  account identity and authorised keys.
* Creates (or reuses) a privileged management user, provisions the authorized
  keys returned by the API and enables passwordless sudo.
* Leaves the existing OpenSSH daemon authentication settings unchanged while
  (optionally) terminating any other active SSH sessions.

The end result is a host that is ready for remote administration and, in later
iterations, remote virtual machine lifecycle operations.

## Requirements

* Ubuntu 24.04 LTS (fresh install is assumed).
* Root access to the server.
* Python 3.10 or newer available in the environment.
* An API key for `https://api.playrservers.com` that has permission to register
  the server and return the correct SSH public keys.

## Installation

Install the agent with a single command (requires `sudo` and an internet
connection):

```bash
curl -fsSL https://raw.githubusercontent.com/PlayrTBH/HVDeploy/main/install.sh | sudo bash
```

The installer bootstraps Python tooling via `apt`, installs the latest version
of the agent from the public repository and exposes the `hvdeploy-agent`
command line entry point.  After the API key is validated the installer
automatically runs the agent using that key so no additional manual command is
required.  The branch can be overridden with the `HVDEPLOY_BRANCH` environment
variable, and `HVDEPLOY_PACKAGE_URL` may be set to install from a specific
tarball or release.

During installation the script prompts for an HVDeploy API key and validates it
against the management API.  Leaving the prompt blank, providing an invalid key
or running in a non-interactive environment without the `HVDEPLOY_API_KEY`
environment variable set will abort the installation.

To install manually instead of using the helper script, clone the repository on
the target host and run `pip install .` from the project root.  The script can
also be executed directly via `python -m management_agent.cli`.

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

When invoked the agent performs a two-step handshake with the HVDeploy API:

1. `GET /v1/account/profile` using the supplied API key to determine the owning
   account and retrieve the SSH public keys that should be provisioned on the
   host.
2. `POST /v1/servers/connect` to register the current server, including the
   metadata gathered locally alongside the username/keys retrieved in step 1.

The registration response may optionally include overrides recognised by the
agent:

* `username`: Overrides the CLI/default management username.
* `close_other_sessions`: When `true` (default) the agent attempts to terminate
  other SSH connections after configuration.

If either API call does not return any SSH keys the agent aborts without
modifying the system to avoid locking administrators out of the server.
