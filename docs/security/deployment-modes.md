# Deployment modes and their security model

For administrators and security officers who assess aTrain before a rollout.
aTrain is a desktop application whose user interface is a web page. A web
server inside the application (NiceGUI on uvicorn) serves that page to a
native window. This page describes, for each way of running aTrain, who can
reach that server, where the data lives and what aTrain leaves to the
operating system. It covers the local modes in full. For network mode it only
states the requirement; the details are not documented yet.

## Overview

| Mode                    | Started by                                                                                     | Listens on                                    | Reachable by                                        |
| ----------------------- | ---------------------------------------------------------------------------------------------- | --------------------------------------------- | --------------------------------------------------- |
| Native window (default) | `aTrain start`; the Microsoft Store, GitHub/Zenodo and Flathub packages                        | `127.0.0.1`, the first free port from 8000 up | processes on the same machine                       |
| Browser on localhost    | `aTrain start --no-native --host 127.0.0.1`                                                    | `127.0.0.1:8080`                              | processes on the same machine                       |
| Network mode            | `aTrain start --no-native` without `--host 127.0.0.1`, the Linux service, the Docker container | all interfaces, port 8080                     | everyone who can reach the machine over the network |

## Native window

This is the mode of the packaged apps (e.g. MSIX) and of a plain
`aTrain start` from source.

**Listener.** The server binds to the loopback interface (`127.0.0.1`) on
the first free port from 8000 upward and a pywebview window shows the page.
No external interface is involved and the traffic between window and server
never leaves the machine. The server offers no TLS and there is no network
path for it to protect.

**Who can use it.** The server has no authentication. Every process that can
open a connection to the loopback interface can operate the application while
it runs: read and delete the archive, download and remove models and submit
recordings for transcription where the file goes through the browser upload
(see below). Loopback connections carry no account check, so the trust
boundary is the machine: on a workstation with one signed-in user, that user's
own processes and the system's services. On a machine with several
simultaneous sessions, such as a terminal server, every signed-in user can
reach the port, which `netstat` lists. All of them form one trust group and
aTrain has no mechanism to keep them apart. Where that is not acceptable, run
aTrain on a machine or VM with a single user session.

**Data.** Transcripts are files under `Documents\aTrain` or the path in
`ATRAIN_USER_DIR`, settings and models next to them or, in the Flatpak, in the
app's own folder under `~/.var/app`. All of them are protected by the file
permissions of the user's profile. [Uninstalling aTrain](../uninstall.md)
lists every location and what it contains.

**The recording.** aTrain does not store recordings. On Windows and macOS the
file selected in the window goes through a browser upload to the local server:
NiceGUI spools it into the system temporary directory once it exceeds 1 MB,
and aTrain copies it once more into a temporary directory of its own for the
run. Both copies are removed when the run ends; a process killed mid-run
leaves them behind. On Linux and in the Flatpak the file dialog hands over a
path and the engine reads the file in place.

**Outbound traffic.** A reachability check and the model downloads, both to
huggingface.co and both only when a model is downloaded; see the privacy
section of the [Code signing policy](../code-signing-policy.md#privacy). With
the models in place, from a build that bundles them or copied into the models
folder, aTrain makes no network request at all and can also run on an
air-gapped machine.

**Flatpak.** The sandbox limits file access to the documents folder, the app's
own folder under `~/.var/app` and files picked through the portal. It shares
the host's network namespace, which the model download needs, so other
processes on the host reach the loopback server as described above.

## Browser on localhost

```bash
aTrain start --no-native --host 127.0.0.1
```

Runs the same server without the native window and opens a tab in the default
browser, on port 8080 unless `--port` says otherwise. The flags work when
running from source and in the Flatpak; the MSIX package always starts the
native window. Use this mode when the native window does not work on a
machine. The trust boundary is the same as in the native window: the loopback
interface, every local process. The recording goes through the browser upload
on every platform, with the temporary copies described above. The page runs in
a regular browser, where extensions see it like any other page.

Pass `--host 127.0.0.1`. Without it, `--no-native` binds to all interfaces
and the application is in network mode.

## Network mode

Three ways of starting aTrain make the server reachable over the network:

- `aTrain start --no-native` without `--host 127.0.0.1`
- the [Linux service](../linux/service.md)
- the Docker development container from
  [CONTRIBUTING.md](../../CONTRIBUTING.md), which publishes port 8080 on all
  host interfaces

aTrain has no authentication and no TLS. Do not expose it without a reverse
proxy that terminates TLS and authenticates users. The requirements for that
proxy and for operating aTrain as a shared service, such as data separation
between users, the service account and model downloads, are not documented
yet; [#150](https://github.com/aTrainTranscription/aTrain/issues/150) (Task H)
tracks them.

## Encryption at rest

aTrain writes transcripts as plain text files (`transcription.txt` and its
variants, `.srt`, `.json`, with `metadata.txt` and `log.txt`) into the
transcriptions folder, a `.zip` of that folder next to it when you use
**Download**, the last used options into the settings folder and models into
the models folder. While a transcription runs, the temporary copies of the
recording described above exist whenever the file came in through the browser
upload. Deleting a transcription in the archive, or all of them with **Delete
All**, removes the files like any file deletion and does not overwrite them,
so the data stays on the disk until the blocks are reused.

aTrain does not encrypt any of this and relies on the operating system's disk
encryption instead, such as BitLocker on Windows, LUKS on Linux or FileVault
on macOS. The reasons:

- A key inside aTrain would live on the same machine, readable by the same
  account and outside the organisation's key management. It adds nothing to
  what disk encryption (a stolen or discarded disk) and file permissions
  (other accounts on the machine) already cover.
- Disk encryption also covers what the application cannot reach: the
  temporary copies of the recording, deleted transcripts, swap and
  hibernation files, the browser's cache.
- Users open transcripts in other programs, from text editors to QDA software
  (see [Tutorials](../tutorials.md)), which read plain files.

Transcripts are personal data. Full-disk encryption on every machine that runs
aTrain and on the file server when `Documents` is redirected there is
therefore a requirement on the deploying organisation; aTrain cannot enforce
it. For the deletion of transcripts when a machine is decommissioned, see
[Uninstalling aTrain](../uninstall.md).
