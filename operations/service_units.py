"""Local systemd schedules; generated only for this deployment, without secrets."""
from pathlib import Path
from .configuration import ConfigurationError,private_write

MARKER='# Managed by Toshkent Invest portalctl\n'


def render_units(root):
    root=str(Path(root).resolve())
    if any(ord(character)<32 for character in root):raise ConfigurationError('Unsupported control character in release path')
    executable='"'+(root+'/portalctl').replace('\\','\\\\').replace('"','\\"')+'"'
    # systemd takes WorkingDirectory= literally; quotes make it a non-absolute path and the unit fails to load.
    base='[Unit]\nRequires=docker.service\nAfter=docker.service network-online.target\n\n[Service]\nType=oneshot\nWorkingDirectory='+root+'\nEnvironment=DOCKER_HOST=unix:///var/run/docker.sock\nUMask=0077\n'
    return {
        'toshkent-portal-backup.service':MARKER+base+'TimeoutStartSec=7200\nExecStart=/usr/bin/python3 '+executable+' backup\n',
        'toshkent-portal-backup.timer':MARKER+'[Unit]\nDescription=Encrypted portal backup\n\n[Timer]\nOnCalendar=daily\nRandomizedDelaySec=300\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n',
        'toshkent-portal-health.service':MARKER+base+'TimeoutStartSec=120\nExecStart=/usr/bin/python3 '+executable+' check\n',
        'toshkent-portal-health.timer':MARKER+'[Unit]\nDescription=Portal technical health\n\n[Timer]\nOnBootSec=2min\nOnUnitActiveSec=1min\n\n[Install]\nWantedBy=timers.target\n',
    }


def write_units(root,destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    units=render_units(root)
    for name in units:
        path=destination/name
        if path.exists() and not path.read_text().startswith(MARKER):raise ConfigurationError('Refusing to overwrite an unrelated systemd unit')
    for name,content in units.items():private_write(destination/name,content,0o644)
    return list(units)
