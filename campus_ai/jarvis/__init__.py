"""Campus AI — Jarvis core (stage 1): conversation, tools, local memory, reminders, operation log.

Entry point: ``Jarvis`` (agent.py). Storage: ``JarvisStore`` (jarvis.db, separate from live.db). No network, no
audio and no generative model in this stage; see docs/JARVIS_NUCLEO.md.
"""
from .agent import Jarvis, Reply  # noqa: F401
from .store import JarvisStore  # noqa: F401
