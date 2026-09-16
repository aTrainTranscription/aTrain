# Run aTrain as Linux Service

Install uv as root.

```bash
sudo -i
# install script from uv docs.
```

Clone or extract aTrain to `/opt/`.

```bash
sudo -i
cd /opt
git clone https://github.com/aTrainTranscription/aTrain.git
cd aTrain
uv sync --extra gui
logout
```

Create aTrain folder in `/srv`.

```bash
sudo -i
cd /srv
mkdir aTrain
logout
```

Place the following file as `aTrain.service` at `/etc/systemd/system`.

```ini
[Unit]
Description=Runs aTrain as a service
After=network.target
Wants=network-online.target

[Service]
Restart=always
Type=simple
ExecStart=/opt/aTrain/.venv/bin/aTrain start --no-native --no-show
Environment='ATRAIN_USER_DIR=/srv/aTrain'
Environment='WAKEPY_FAKE_SUCCESS=yes'
Environment='HF_TOKEN=<your-token>'

[Install]
WantedBy=multi-user.target
```

```bash
sudo nano /etc/systemd/system/aTrain.service
# paste
# CTRL + X, CTRL + Y, Enter
```

Append `--host` and `--port` in the 'ExecStart' line to configure those settings.

A Hugging Face token is required to successfully download the speaker detection model. If the download fails, remove the `/srv/aTrain/models/speaker-detection` folder, check the token, and if you have accepted the terms on Hugging Face, retry. After the first successful transcription with speaker detection, that environment variable can be removed.

Enable and run the service

```bash
sudo systemctl enable --now aTrain.service
```

Check if it works

```bash
# try to access in the browser

# check service status
sudo systemctl status aTrain.service

# see aTrain output
sudo journalctl -e -u aTrain.service
```

You can put this behind a reverse proxy, but prefix-path is currently not supported.
