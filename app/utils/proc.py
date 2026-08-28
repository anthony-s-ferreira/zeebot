"""Execução segura de processos externos.

Regras do projeto: nunca ``shell=True``, sempre lista de argumentos, sempre
com timeout, e nada de segredos no log.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Iterable, List, Optional, Sequence

log = logging.getLogger(__name__)


class CommandResult:
    __slots__ = ("args", "returncode", "stdout", "stderr", "timed_out")

    def __init__(
        self,
        args: Sequence[str],
        returncode: int,
        stdout: str = "",
        stderr: str = "",
        timed_out: bool = False,
    ) -> None:
        self.args = list(args)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<CommandResult {self.args[0] if self.args else '?'} rc={self.returncode}>"


def which(binary: str) -> Optional[str]:
    return shutil.which(binary)


def run(
    args: Sequence[str],
    timeout: float = 20.0,
    input_text: Optional[str] = None,
    log_args: Optional[Sequence[str]] = None,
    check: bool = False,
) -> CommandResult:
    """Executa ``args`` com timeout e captura de saída.

    ``log_args`` permite registrar uma versão sanitizada do comando (por
    exemplo, escondendo a senha do Wi-Fi).
    """
    args = [str(a) for a in args]
    printable = " ".join(log_args) if log_args else " ".join(args)
    log.debug("exec: %s", printable)

    if not args:
        return CommandResult(args, 1, stderr="comando vazio")

    if which(args[0]) is None and not os.path.isabs(args[0]):
        message = f"binário não encontrado: {args[0]}"
        log.warning(message)
        return CommandResult(args, 127, stderr=message)

    try:
        completed = subprocess.run(  # noqa: S603 - lista de argumentos, sem shell
            args,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.warning("timeout (%.0fs) ao executar: %s", timeout, printable)
        return CommandResult(args, 124, timed_out=True, stderr="timeout")
    except OSError as exc:
        log.warning("falha ao executar %s: %s", printable, exc)
        return CommandResult(args, 126, stderr=str(exc))

    result = CommandResult(
        args,
        completed.returncode,
        (completed.stdout or "").strip(),
        (completed.stderr or "").strip(),
    )
    if not result.ok:
        log.debug("comando falhou (rc=%s): %s | %s", result.returncode, printable, result.stderr)
    if check and not result.ok:
        raise RuntimeError(f"comando falhou: {printable} ({result.stderr})")
    return result


def with_privileges(args: Sequence[str], use_sudo: bool = True) -> List[str]:
    """Prefixa ``sudo -n`` quando o processo não roda como root."""
    args = [str(a) for a in args]
    if os.geteuid() == 0 or not use_sudo:
        return args
    if which("sudo") is None:
        return args
    return ["sudo", "-n", *args]


def sanitize_for_log(args: Iterable[str], secret: Optional[str]) -> List[str]:
    """Substitui o segredo pelo marcador ``***`` na versão registrada."""
    out = []
    for arg in args:
        out.append("***" if secret and arg == secret else str(arg))
    return out
