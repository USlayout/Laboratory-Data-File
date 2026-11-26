"""Shared environment choices and compatibility with older saved reports."""
import re

ENVIRONMENTS = ("Host", "KVM", "Docker", "DOK")


def canonical_environment(value):
    value = str(value).strip()
    aliases = {name.lower(): name for name in ENVIRONMENTS}
    aliases.update({"kvm上docker": "DOK", "kvm-docker": "DOK", "dockeronkvm": "DOK", "kvm上のdocker": "DOK"})
    return aliases.get(value.lower())


def environment_filename(value):
    return canonical_environment(value) or re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_")
