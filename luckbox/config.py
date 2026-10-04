"""Where luckbox keeps things. Everything personal lives under LUCKBOX_HOME (default ~/.luckbox)."""
import json
import os


def home():
    return os.path.expanduser(os.environ.get("LUCKBOX_HOME", "~/.luckbox"))


def path(*parts):
    return os.path.join(home(), *parts)


def load():
    """Read config.json and resolve every source path against LUCKBOX_HOME."""
    with open(path("config.json")) as f:
        cfg = json.load(f)
    cfg.setdefault("me", [])
    cfg["profile"] = os.path.expanduser(cfg.get("profile", ""))
    for src in cfg.get("sources", []):
        p = os.path.expanduser(src["path"])
        src["path"] = p if os.path.isabs(p) else path(p)
    return cfg


def write_private(file, text):
    """Write a file only the owner can read. Everything under LUCKBOX_HOME is about real people."""
    os.makedirs(os.path.dirname(file), exist_ok=True)
    fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
