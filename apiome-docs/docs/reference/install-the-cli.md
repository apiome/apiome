---
title: "Install the CLI"
description: "Install, upgrade or remove the apiome command with one line."
sidebar_position: 3
tags: [cli]
---

The `apiome` command line installs on Linux and macOS without the rest of the Apiome suite. Download the
installer, then run it:

```bash
curl -fsSL https://get.apiome.dev -o get-apiome.sh
sh ./get-apiome.sh
```

Or pipe it straight to `sh`:

```bash
curl -fsSL https://get.apiome.dev | sh
```

When it finishes, run `apiome --version` to check it, then follow the [CLI quick-start](./cli-quickstart.md)
to point it at your Apiome server.

## What the installer does

1. Checks you are on Linux or macOS and, for a system install, that it can get root: it is root already or
   `sudo` is available. `sudo` may ask for your password.
2. Checks that you have `curl` and `git`.
3. Installs [uv](https://docs.astral.sh/uv/) — the Python tool manager — with Astral's own installer, if
   it is not there already.
4. Downloads only the CLI's folder of the Apiome repository, at the version you asked for.
5. Installs `apiome` as an isolated tool. It gets its own Python 3.12+ (uv downloads one if your machine
   does not have one) and the exact dependency versions the CLI is tested with. Your system Python is not
   touched.
6. Runs `apiome --version` to prove the command starts, and tells you if its folder is not on your `PATH`.

## Where it installs

| Install | `apiome` command | Tool and its Python | Needs |
| --- | --- | --- | --- |
| **System** (default) | `/usr/bin/apiome` on Linux, `/usr/local/bin/apiome` on macOS | `/opt/apiome` | root or `sudo` |
| **User** (`--user`) | `~/.local/bin/apiome` | `~/.local/share/uv/tools` | nothing extra |

A system install works for every user on the machine. On macOS it goes into `/usr/local/bin` because
macOS keeps `/usr/bin` read-only, even for root. To link the command somewhere else, pass
`--bin-dir`. For example, `--bin-dir /usr/local/bin` on Linux.

Use `--user` when you cannot use `sudo`, or want the CLI for yourself only:

```bash
sh ./get-apiome.sh --user
```

If the installer says `~/.local/bin` is not on your `PATH`, **open a new terminal**, or run the
`export PATH=…` line it prints.

:::tip Read before you run
The script is [`apiome-cli/install.sh`](https://github.com/apiome/apiome/blob/main/apiome-cli/install.sh)
in the Apiome repository. Downloading it first, as at the top of this page, lets you read it before you
run it:

```bash
curl -fsSL https://get.apiome.dev -o get-apiome.sh
less get-apiome.sh
sh ./get-apiome.sh
```
:::

## Options

Pass options after the script name, or after `sh -s --` when you pipe it. You can set the environment
variable instead:

```bash
sh ./get-apiome.sh --version main
curl -fsSL https://get.apiome.dev | sh -s -- --user
curl -fsSL https://get.apiome.dev | APIOME_VERSION=main sh
```

| Option | Environment variable | What it does |
| --- | --- | --- |
| `--version <ref>` | `APIOME_VERSION` | Install a tag, branch or commit of the Apiome repository. Default: `main`. |
| `--repo <url>` | `APIOME_REPO` | Install from another copy of the repository (an `https://` or `ssh://` URL), such as your own fork. |
| `--user` | `APIOME_USER_INSTALL=1` | Install for your user only, into `~/.local/bin`, without `sudo`. |
| `--bin-dir <dir>` | `APIOME_BIN_DIR` | Where a system install puts the `apiome` command. Default: `/usr/bin`, or `/usr/local/bin` on macOS. |
| `--no-modify-path` | `APIOME_NO_MODIFY_PATH=1` | Stop the uv installer from adding its folder to your shell profile. |
| `--uninstall` | — | Remove the `apiome` command. Add `--user` to remove a user install. |
| `-h`, `--help` | — | Show the options. |

## Upgrade

Run the installer again, with the same `--user` or `--bin-dir` you installed with. It replaces the
installed version with the one you ask for (`main` unless you pass `--version`).

## Uninstall

```bash
sh ./get-apiome.sh --uninstall           # a system install
sh ./get-apiome.sh --uninstall --user    # a user install
```

A system uninstall removes the `apiome` command and `/opt/apiome`. Either way, uv stays in place. To
remove uv too, run `uv self uninstall`.

## Install without the script

If you already use uv, you can install the CLI directly, for your user:

```bash
uv tool install --python 3.12 "apiome-cli @ git+https://github.com/apiome/apiome#subdirectory=apiome-cli"
```

This uses the newest dependency versions the CLI allows, not the exact tested set the installer uses.
Prefer the installer when you can.

To work on the CLI itself, clone the repository and use it from source — see the
[CLI quick-start](./cli-quickstart.md#from-a-clone-of-the-repository).

## Troubleshooting

| You see | What to do |
| --- | --- |
| `A system install needs root, and sudo is not available` | Run the installer as root, or install for your user with `--user`. |
| `git is required` | Install git (`sudo apt install git`, or `xcode-select --install` on macOS) and run the installer again. |
| `Windows is not supported by this installer` | Run it inside [WSL](https://learn.microsoft.com/windows/wsl/install), or install uv on Windows and use the `uv tool install` line above. |
| `Could not fetch '…'` | The `--version` you passed is not a tag, branch or commit of the repository. |
| `There is no system install in /opt/apiome` | You installed with `--user`; uninstall with `--uninstall --user`. |
| `apiome: command not found` after installing | Open a new terminal, or add the folder the installer named to your `PATH`. |
| `apiome was installed but does not start` | Report it with the output the installer printed. |
