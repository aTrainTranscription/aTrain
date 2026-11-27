# Operations

For administrators who run aTrain and need to know what it records.

## Event log

aTrain writes security-relevant events to a log in each user's profile. Nothing
sends this log anywhere. This is not a debug log. Each transcription keeps its own
`log.txt` with its steps. A debug mode is planned in
[#121](https://github.com/aTrainTranscription/aTrain/issues/121).

| Install             | File                                                                                  |
| ------------------- | ------------------------------------------------------------------------------------- |
| Windows (MSIX)      | `%LOCALAPPDATA%\Packages\<PackageFamilyName>\LocalCache\Local\aTrain\Logs\atrain.log` |
| Windows from source | `%LOCALAPPDATA%\aTrain\Logs\atrain.log`                                               |
| Linux (Flatpak)     | `~/.var/app/io.github.juergenfleiss.aTrain/.local/state/aTrain/log/atrain.log`        |
| Linux from source   | `~/.local/state/aTrain/log/atrain.log`                                                |
| macOS               | `~/Library/Logs/aTrain/atrain.log`                                                    |

Windows redirects what the MSIX writes under `%LOCALAPPDATA%` into the package
folder, so the file does not appear at the plain path. Uninstalling the MSIX
deletes the log with that folder. Microsoft
[documents one exception](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-behind-the-scenes):
a file that already exists under AppData, for example from a run from source, is
written in place and stays after uninstalling.

`aTrain start` writes this log. `aTrain init` and the `aTrain_core` command line
do not.

### Format

One line per event: time with UTC offset, level, event name, then `key=value`
fields. Unhandled exceptions add an indented traceback below their line.

```
2026-11-27 16:20:00+0100 INFO server_starting version='1.5.0' native=False host='127.0.0.1' port=8080 allow_any_host=False
2026-11-27 16:20:01+0100 INFO server_stopped
```

### Events

| Event                 | Fields                                                                                     |
| --------------------- | ------------------------------------------------------------------------------------------ |
| `server_starting`     | version, native, host, port, allow_any_host; written before the server binds the port      |
| `server_stopped`      |                                                                                            |
| `server_failed`       | exit code; the server did not start, for example because the port is taken                 |
| `unhandled_exception` | error, traceback; also when an import fails at start                                       |

### Personal data

Error messages and tracebacks can contain file paths and with them file names,
which often contain the name of the interviewee. To remove them, delete the log
files. Transcript text and the initial prompt are not logged.

### Retention

The file rotates at 1 MB. aTrain keeps `atrain.log` and up to four older files
(`atrain.log.1` to `atrain.log.4`) and deletes anything older. There is no limit
by age.

Run one instance per user. Two running instances write to the same file. On
Windows the rotation then fails while the other instance holds the file open.
Once the file is full, new events are lost until one instance ends.
aTrain keeps running and the lines stay intact.
