"""Safe subprocess wrapper — zero shell=True, zero automatic sudo."""

import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    returncode: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        return self.stdout.strip()

    @property
    def error(self) -> str:
        return self.stderr.strip()


def run(
    cmd: list[str],
    timeout: int = 10,
    input_text: Optional[str] = None,
) -> CommandResult:
    """Run a command safely and return its result. Never uses shell=True."""
    logger.debug("run: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
        )
        if proc.returncode != 0:
            logger.debug("exit %d: %s", proc.returncode, proc.stderr.strip()[:200])
        return CommandResult(stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)
    except subprocess.TimeoutExpired:
        logger.warning("timeout (%ds): %s", timeout, " ".join(cmd))
        return CommandResult(stdout="", stderr=f"Timeout après {timeout}s", returncode=-1)
    except FileNotFoundError:
        logger.warning("not found: %s", cmd[0])
        return CommandResult(stdout="", stderr=f"Commande introuvable : {cmd[0]}", returncode=127)
    except Exception as exc:
        logger.error("run error: %s", exc)
        return CommandResult(stdout="", stderr=str(exc), returncode=-1)


def launch_background(cmd: list[str]) -> Optional[subprocess.Popen]:
    """Launch a command in background (non-blocking). Returns Popen or None."""
    logger.debug("launch: %s", " ".join(cmd))
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info("launched pid=%d: %s", proc.pid, " ".join(cmd))
        return proc
    except FileNotFoundError:
        logger.warning("not found: %s", cmd[0])
        return None
    except Exception as exc:
        logger.error("launch error: %s", exc)
        return None


def is_installed(name: str) -> bool:
    """Return True if `name` is available in PATH."""
    return shutil.which(name) is not None
