---
title: "Install the CLI"
description: "Install, upgrade or remove the apiome command with one line."
sidebar_position: 3
tags: [cli]
---

The `apiome` command line installs with one line on Linux and macOS:

```bash
curl -fsSL https://get.apio.me | bash
```

When it finishes, run `apiome --version` to check it, then follow the [CLI quick-start](./cli-quickstart.md)
to point it at your Apiome server.

## What the installer does

1. Checks you are on Linux or macOS and have `curl` and `git`.
2. Installs [uv](https://docs.astral.sh/uv/) — the Python tool manager — with Astral's own installer, if
   it is not there already.
3. Downloads only the CLI's folder of the Apiome repository, at the version you asked for.
4. Installs `apiome` as an isolated tool: it gets its own Python 3.12+ (downloaded by uv if your machine
   does not have one) and the exact dependency versions the CLI is tested with. Your system Python is not
   touched.
5. Runs `apiome --version` to prove the command starts, and tells you if its folder is not on your `PATH`
   yet.

`apiome` lands in `~/.local/bin` (uv's tool folder). If the installer says that folder is not on your
`PATH`, **open a new terminal** — or run the `export PATH=…` line it prints.

:::tip Read before you pipe
The script is [`apiome-cli/install.sh`](https://github.com/apiome/apiome/blob/main/apiome-cli/install.sh)
in the Apiome repository. To read it before running it, download it first:

```bash
curl -fsSL https://get.apio.me -o install.sh
less install.sh
bash install.sh
```
:::

## Options

Pass options after `bash -s --`, or set the environment variable instead:

```bash
curl -fsSL https://get.apio.me | bash -s -- --version main
curl -fsSL https://get.apio.me | APIOME_VERSION=main bash
```

| Option | Environment variable | What it does |
| --- | --- | --- |
| `--version <ref>` | `APIOME_VERSION` | Install a tag, branch or commit of the Apiome repository. Default: `main`. |
| `--repo <url>` | `APIOME_REPO` | Install from another copy of the repository (an `https://` or `ssh://` URL), such as your own fork. |
| `--no-modify-path` | `APIOME_NO_MODIFY_PATH=1` | Stop the uv installer from adding its folder to your shell profile. |
| `--uninstall` | — | Remove the `apiome` command. |
| `-h`, `--help` | — | Show the options. |

## Upgrade

Run the installer again. It replaces the installed version with the one you ask for (`main` unless you
pass `--version`).

## Uninstall

```bash
curl -fsSL https://get.apio.me | bash -s -- --uninstall
```

This removes `apiome` and leaves uv in place. To remove uv too, run `uv self uninstall`.

## Install without the script

If you already use uv, you can install the CLI directly:

```bash
uv tool install --python 3.12 "apiome-cli @ git+https://github.com/apiome/apiome#subdirectory=apiome-cli"
```

This resolves the newest dependency versions the CLI allows rather than the exact tested set the
installer uses, so prefer the installer when you can.

To work on the CLI itself, clone the repository and use it from source — see the
[CLI quick-start](./cli-quickstart.md#from-a-clone-of-the-repository).

## Troubleshooting

| You see | What to do |
| --- | --- |
| `git is required` | Install git (`sudo apt install git`, or `xcode-select --install` on macOS) and run the installer again. |
| `Windows is not supported by this installer` | Run it inside [WSL](https://learn.microsoft.com/windows/wsl/install), or install uv on Windows and use the `uv tool install` line above. |
| `Could not fetch '…'` | The `--version` you passed is not a tag, branch or commit of the repository. |
| `apiome: command not found` after installing | Open a new terminal, or add the folder the installer named to your `PATH`. |
| `apiome was installed but does not start` | Report it with the output the installer printed. |
