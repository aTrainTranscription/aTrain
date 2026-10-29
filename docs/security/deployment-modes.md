# Deployment modes and their security model

For administrators and security officers. aTrain is a desktop application
whose user interface comes from a small web server inside the application.
This page describes, for each way of running aTrain, who can reach that
server, where the data lives and what aTrain leaves to the operating system.

## Overview

| Mode                    | Started with                                  | Listens on                | Reachable by                                        |
| ----------------------- | --------------------------------------------- | ------------------------- | --------------------------------------------------- |
| Native window (default) | the installed apps                            | `127.0.0.1`, a free port  | processes on the same machine                       |
| Browser on localhost    | `aTrain start --no-native --host 127.0.0.1`   | `127.0.0.1`, port 8080    | processes on the same machine                       |
| Network mode            | `aTrain start --no-native`, the Linux service | all interfaces, port 8080 | everyone who can reach the machine over the network |

## Native window

This is how the installed apps run.

**Access.** The server listens only on the loopback interface, so traffic
between window and server never leaves the machine and there is nothing for
TLS to protect. The server has no login. While aTrain runs, every process on
the machine can operate it: read and delete transcripts, download and remove
models and, on Windows, start transcriptions. The trust boundary is therefore
the machine. On a machine with several simultaneous sessions, such as a
terminal server, all signed-in users can reach the server and aTrain cannot
keep them apart. Where that is not acceptable, run aTrain on a machine or VM
with a single user session.

**Data.** Transcripts are stored under `Documents\aTrain` or the folder set in
`ATRAIN_USER_DIR`, settings and models next to them. The Flatpak keeps
settings and models in its app folder under `~/.var/app`. The file
permissions of the user's profile protect all of it.
[Uninstalling aTrain](../uninstall.md) lists every location.

**Recordings.** aTrain does not keep recordings. On Windows the selected file
is uploaded from the window to the local server. During the transcription a
copy can sit in the system's temporary folder and another one sits in a
temporary folder of aTrain's own. Both are deleted when the transcription
ends, but stay behind if the process is killed. On Linux, macOS and in the
Flatpak aTrain reads the file where it is.

**Network traffic.** aTrain only goes online to download a model from
huggingface.co, with a reachability check before the download; see the
privacy section of the [Code signing policy](../code-signing-policy.md#privacy).
With all models in place, bundled or copied into the models folder, aTrain
makes no network request at all and can also run on an air-gapped machine.

**Flatpak.** The sandbox limits file access to the documents folder, the
app's own folder and files picked in the file dialog. It shares the host's
network, which the model download needs, so other processes on the host reach
the server as described above.

## Browser on localhost

If the native window does not work on a machine, aTrain can open in the
default browser instead, with `aTrain start --no-native --host 127.0.0.1`.
This works in the Flatpak and from source; the Windows app always opens the
native window. The server still listens only on `127.0.0.1`, so the trust
boundary is the same as above. The recording is uploaded on every platform,
with the temporary copies described above, and browser extensions see the
page like any other page.

Without `--host 127.0.0.1`, `--no-native` listens on all interfaces and
aTrain runs in network mode.

## Network mode

`aTrain start --no-native` without `--host 127.0.0.1` and the
[Linux service](../linux/service.md) make aTrain reachable over the network.
aTrain has no login and no TLS. Do not expose it without a reverse proxy that
terminates TLS and authenticates users. What a shared setup needs beyond that,
such as separating the users' data, the service account and model downloads,
is not documented yet; [#150](https://github.com/aTrainTranscription/aTrain/issues/150)
tracks it.

## Encryption at rest

aTrain stores transcripts as plain files: text, SRT and JSON, with metadata
and a log. It also stores a ZIP of a transcript when you use **Download**, the
last used settings and the models. While a Windows or browser transcription
runs, the temporary copies of the recording described above exist as well.
Deleting transcripts in the archive, one by one or with **Delete All**,
removes the files without overwriting them, so the data stays on the disk
until the space is reused.

aTrain does not encrypt any of this and relies on the operating system's disk
encryption instead, such as BitLocker, LUKS or FileVault:

- A key inside aTrain would sit on the same machine, readable by the same
  account and outside the organisation's key management. Disk encryption
  already covers a stolen or discarded disk and file permissions cover other
  accounts on the machine.
- Disk encryption also covers what aTrain cannot reach: the temporary copies,
  deleted transcripts, swap and hibernation files and the browser cache.
- Users open transcripts in other programs, from text editors to QDA
  software (see [Tutorials](../tutorials.md)), and those need plain files.

Transcripts are personal data. Full-disk encryption on every machine that runs
aTrain, and on the file server when `Documents` is redirected there, is
therefore a requirement on the deploying organisation; aTrain cannot enforce
it. For deleting transcripts when a machine is decommissioned, see
[Uninstalling aTrain](../uninstall.md).
