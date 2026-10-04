"""Bilgisayarda calisan bot sureci (stdin/stdout JSON satirlari)."""
import asyncio
import json
import os
import shlex
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bot_command(spec):
    """'bots/x.py' -> python ile calistir; digerleri oldugu gibi komut."""
    if spec.endswith(".py"):
        return [sys.executable, "-X", "utf8", spec]
    return shlex.split(spec)


def bot_name(spec):
    return os.path.splitext(os.path.basename(shlex.split(spec)[-1]))[0]


class LocalBot:
    latency = 0.0

    def __init__(self, spec, name=None):
        self.spec = spec
        self.name = name or bot_name(spec)
        self.inbox = asyncio.Queue()
        self.proc = None

    async def start(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=ROOT)
        self.proc = await asyncio.create_subprocess_exec(
            *bot_command(self.spec), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=None, env=env,
            limit=2**20)
        self._reader = asyncio.create_task(self._read())
        return self

    async def _read(self):
        # Varis zamanini satir okunur okunmaz damgala: hiz olcumu buna gore
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            t = time.perf_counter()
            try:
                self.inbox.put_nowait((t, json.loads(line)))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass  # botun debug ciktisi: yok say

    async def send(self, msg):
        try:
            self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())
            await self.proc.stdin.drain()
        except (OSError, ConnectionError, AttributeError):
            pass

    async def close(self):
        if not self.proc or self.proc.returncode is not None:
            return
        try:
            await asyncio.wait_for(self.proc.wait(), 2)
        except asyncio.TimeoutError:
            self.proc.kill()
