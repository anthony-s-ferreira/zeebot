"""Camada sobre o NetworkManager (nmcli).

Tudo aqui usa ``subprocess`` com lista de argumentos — nunca ``shell=True`` —
e a senha do Wi-Fi jamais chega ao log (nem ao ``ps``, pois é argumento direto
do processo filho e é substituída por ``***`` na versão registrada).
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..utils.proc import CommandResult, run, sanitize_for_log, which, with_privileges

log = logging.getLogger(__name__)

NMCLI = "nmcli"
SSID_MAX_LENGTH = 32
_INVALID_SSID_RE = re.compile(r"[\x00-\x1f\x7f]")


# --------------------------------------------------------------------- helpers
def nmcli_available() -> bool:
    return which(NMCLI) is not None


def _nmcli(
    args: Sequence[str],
    privileged: bool = False,
    timeout: float = 20.0,
    use_sudo: bool = True,
    secret: Optional[str] = None,
) -> CommandResult:
    command = [NMCLI, *[str(a) for a in args]]
    if privileged:
        command = with_privileges(command, use_sudo=use_sudo)
    log_args = sanitize_for_log(command, secret) if secret else None
    return run(command, timeout=timeout, log_args=log_args)


def parse_terse_line(line: str) -> List[str]:
    """Divide uma linha ``nmcli -t`` respeitando ``\\:`` e ``\\\\``."""
    fields: List[str] = []
    current: List[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields


def validate_ssid(ssid: Any) -> str:
    """Valida o SSID recebido do formulário antes de virar argumento."""
    if ssid is None:
        raise ValueError("SSID não informado")
    text = str(ssid).strip()
    if not text:
        raise ValueError("SSID não informado")
    if len(text.encode("utf-8")) > SSID_MAX_LENGTH:
        raise ValueError("SSID muito longo")
    if _INVALID_SSID_RE.search(text):
        raise ValueError("SSID contém caracteres inválidos")
    if text.startswith("-"):
        raise ValueError("SSID não suportado (não pode começar com '-')")
    return text


def validate_password(password: Any) -> str:
    if password is None:
        return ""
    text = str(password)
    if text and not (8 <= len(text) <= 63):
        raise ValueError("A senha deve ter entre 8 e 63 caracteres")
    if _INVALID_SSID_RE.search(text):
        raise ValueError("Senha contém caracteres inválidos")
    return text


def device_suffix() -> str:
    """Sufixo estável para o SSID do Access Point (serial ou MAC)."""
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.lower().startswith("serial"):
                    serial = line.split(":", 1)[1].strip()
                    if serial and set(serial) != {"0"}:
                        return serial[-4:].upper()
    except OSError:
        pass
    return f"{uuid.getnode() & 0xFFFF:04X}"


def ap_ssid(prefix: str = "Zee-Setup") -> str:
    return f"{prefix}-{device_suffix()}"


def wifi_qr_payload(ssid: str, password: str = "") -> str:
    """Payload padrão de QR Code para redes Wi-Fi."""

    def escape(value: str) -> str:
        for char in ("\\", ";", ",", ":", '"'):
            value = value.replace(char, "\\" + char)
        return value

    auth = "WPA" if password else "nopass"
    payload = f"WIFI:T:{auth};S:{escape(ssid)};"
    if password:
        payload += f"P:{escape(password)};"
    return payload + ";"


# ------------------------------------------------------------------- consultas
def scan_networks(interface: str = "wlan0", rescan: bool = True, use_sudo: bool = True) -> List[Dict[str, Any]]:
    """Lista as redes visíveis, deduplicadas por SSID e ordenadas por sinal."""
    if not nmcli_available():
        log.error("nmcli não encontrado — NetworkManager está instalado?")
        return []

    args = [
        "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY,FREQ",
        "device", "wifi", "list",
        "ifname", interface,
        "--rescan", "yes" if rescan else "no",
    ]
    result = _nmcli(args, timeout=30.0, use_sudo=use_sudo)
    if not result.ok:
        # Sem rescan costuma funcionar mesmo sem privilégios elevados.
        result = _nmcli(
            ["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY,FREQ", "device", "wifi", "list"],
            timeout=15.0,
            use_sudo=use_sudo,
        )
        if not result.ok:
            log.error("falha ao listar redes: %s", result.stderr)
            return []

    networks: Dict[str, Dict[str, Any]] = {}
    for line in result.stdout.splitlines():
        fields = parse_terse_line(line)
        if len(fields) < 4:
            continue
        in_use, ssid, signal, security = fields[0], fields[1], fields[2], fields[3]
        ssid = ssid.strip()
        if not ssid:
            continue  # rede oculta
        try:
            strength = int(signal)
        except (TypeError, ValueError):
            strength = 0
        security = (security or "").strip()
        entry = {
            "ssid": ssid,
            "signal": strength,
            "security": security or "Aberta",
            "secured": bool(security) and security.upper() not in ("", "--", "NONE"),
            "in_use": in_use.strip() == "*",
        }
        existing = networks.get(ssid)
        if existing is None or entry["signal"] > existing["signal"]:
            networks[ssid] = entry

    ordered = sorted(networks.values(), key=lambda n: (-n["signal"], n["ssid"].lower()))
    log.info("scan Wi-Fi: %s redes encontradas", len(ordered))
    return ordered


def active_wifi(interface: str = "wlan0", use_sudo: bool = True) -> Dict[str, Any]:
    """SSID/IP atualmente ativos na interface."""
    info: Dict[str, Any] = {"ssid": None, "ip": None, "connection": None, "state": "unknown"}
    if not nmcli_available():
        return info

    result = _nmcli(
        ["-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS", "device", "show", interface],
        timeout=10.0,
        use_sudo=use_sudo,
    )
    if not result.ok:
        return info

    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if key == "GENERAL.STATE":
            info["state"] = value
        elif key == "GENERAL.CONNECTION":
            info["connection"] = value if value and value != "--" else None
        elif key.startswith("IP4.ADDRESS"):
            info["ip"] = value.split("/")[0] if value and value != "--" else None

    ssid_result = _nmcli(
        ["-t", "-f", "ACTIVE,SSID", "device", "wifi", "list", "ifname", interface, "--rescan", "no"],
        timeout=10.0,
        use_sudo=use_sudo,
    )
    if ssid_result.ok:
        for line in ssid_result.stdout.splitlines():
            fields = parse_terse_line(line)
            if len(fields) >= 2 and fields[0].strip().lower() == "yes" and fields[1].strip():
                info["ssid"] = fields[1].strip()
                break
    return info


def is_connected(
    interface: str = "wlan0", ap_connection_name: str = "zee-setup-ap", use_sudo: bool = True
) -> bool:
    """Conectado a uma rede real (o próprio Access Point não conta)."""
    info = active_wifi(interface, use_sudo=use_sudo)
    if info.get("connection") == ap_connection_name:
        return False
    return bool(info.get("ip")) and str(info.get("state", "")).startswith("100")


def saved_connection_for(ssid: str, use_sudo: bool = True) -> Optional[str]:
    """Nome do perfil salvo cujo SSID corresponde ao informado."""
    result = _nmcli(["-t", "-f", "NAME,TYPE", "connection", "show"], timeout=10.0, use_sudo=use_sudo)
    if not result.ok:
        return None
    for line in result.stdout.splitlines():
        fields = parse_terse_line(line)
        if len(fields) >= 2 and "wireless" in fields[1]:
            if fields[0] == ssid:
                return fields[0]
    return None


def has_saved_wifi(ap_connection_name: str = "zee-setup-ap", use_sudo: bool = True) -> bool:
    """Existe algum perfil Wi-Fi salvo além do Access Point de configuração?"""
    result = _nmcli(["-t", "-f", "NAME,TYPE", "connection", "show"], timeout=10.0, use_sudo=use_sudo)
    if not result.ok:
        return False
    for line in result.stdout.splitlines():
        fields = parse_terse_line(line)
        if len(fields) >= 2 and "wireless" in fields[1] and fields[0] != ap_connection_name:
            return True
    return False


def check_internet(url: str, timeout: float = 5.0) -> bool:
    """Confirma acesso externo (usado após conectar)."""
    if not url:
        return True
    request = urllib.request.Request(url, headers={"User-Agent": "ZeeAssistant/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return 200 <= response.status < 400
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.info("sem conectividade externa: %s", exc)
        return False


# --------------------------------------------------------------------- conexão
def enable_radio(use_sudo: bool = True) -> None:
    run(with_privileges(["rfkill", "unblock", "wifi"], use_sudo), timeout=10.0)
    _nmcli(["radio", "wifi", "on"], privileged=True, timeout=10.0, use_sudo=use_sudo)


def connect(
    ssid: str,
    password: str = "",
    interface: str = "wlan0",
    timeout: float = 45.0,
    use_sudo: bool = True,
) -> Tuple[bool, str]:
    """Conecta a uma rede.  Retorna ``(ok, mensagem_para_o_usuário)``."""
    ssid = validate_ssid(ssid)
    password = validate_password(password)

    if not nmcli_available():
        return False, "NetworkManager (nmcli) não está disponível no sistema."

    enable_radio(use_sudo)
    log.info("tentando conectar ao SSID %r (senha: %s)", ssid, "sim" if password else "não")

    args = ["device", "wifi", "connect", ssid, "ifname", interface]
    if password:
        args += ["password", password]
    result = _nmcli(args, privileged=True, timeout=timeout, use_sudo=use_sudo, secret=password or None)

    if not result.ok and password and saved_connection_for(ssid, use_sudo):
        # Perfil antigo com senha errada costuma travar a reconexão.
        log.info("removendo perfil antigo de %r e tentando novamente", ssid)
        _nmcli(["connection", "delete", ssid], privileged=True, timeout=15.0, use_sudo=use_sudo)
        result = _nmcli(
            args, privileged=True, timeout=timeout, use_sudo=use_sudo, secret=password or None
        )

    if result.ok:
        info = active_wifi(interface, use_sudo=use_sudo)
        if info.get("ip"):
            log.info("conectado a %r (ip=%s)", ssid, info["ip"])
            return True, f"Conectado a {ssid}"
        log.warning("nmcli reportou sucesso mas sem IP em %s", interface)
        return False, "A rede aceitou a conexão, mas o Zee não recebeu um IP."

    stderr = (result.stderr or "").lower()
    if "secrets were required" in stderr or "invalid password" in stderr or "802-11-wireless-security" in stderr:
        message = "Não foi possível conectar. Verifique a senha e tente novamente."
    elif result.timed_out:
        message = "A conexão demorou demais. Verifique se a rede está ao alcance."
    elif "no network with ssid" in stderr:
        message = "Rede não encontrada. Aproxime o Zee do roteador e tente novamente."
    else:
        message = "Não foi possível conectar. Verifique a senha e tente novamente."
    log.error("falha ao conectar a %r: %s", ssid, result.stderr)
    return False, message


# --------------------------------------------------------------- access point
def start_access_point(
    ssid: str,
    password: str = "",
    interface: str = "wlan0",
    connection_name: str = "zee-setup-ap",
    address: str = "10.42.0.1",
    prefix: int = 24,
    use_sudo: bool = True,
) -> Tuple[bool, str]:
    """Sobe o Access Point de configuração com IP fixo e NAT compartilhado."""
    if not nmcli_available():
        return False, "nmcli indisponível"

    enable_radio(use_sudo)
    _nmcli(["connection", "delete", connection_name], privileged=True, timeout=15.0, use_sudo=use_sudo)

    add = _nmcli(
        [
            "connection", "add",
            "type", "wifi",
            "ifname", interface,
            "con-name", connection_name,
            "autoconnect", "no",
            "ssid", ssid,
        ],
        privileged=True,
        timeout=20.0,
        use_sudo=use_sudo,
    )
    if not add.ok:
        return False, f"não foi possível criar o perfil do AP: {add.stderr}"

    modify_args = [
        "connection", "modify", connection_name,
        "802-11-wireless.mode", "ap",
        "802-11-wireless.band", "bg",
        "ipv4.method", "shared",
        "ipv4.addresses", f"{address}/{int(prefix)}",
        "ipv6.method", "ignore",
    ]
    if password:
        modify_args += [
            "wifi-sec.key-mgmt", "wpa-psk",
            "wifi-sec.proto", "rsn",
            "wifi-sec.psk", password,
        ]
    modify = _nmcli(
        modify_args, privileged=True, timeout=20.0, use_sudo=use_sudo, secret=password or None
    )
    if not modify.ok:
        return False, f"não foi possível configurar o AP: {modify.stderr}"

    up = _nmcli(["connection", "up", connection_name], privileged=True, timeout=45.0, use_sudo=use_sudo)
    if not up.ok:
        log.error("falha ao subir o Access Point: %s", up.stderr)
        return False, f"não foi possível ativar o AP: {up.stderr}"

    log.info("Access Point ativo: SSID=%s ip=%s (senha: %s)", ssid, address, "sim" if password else "aberta")
    return True, ssid


def stop_access_point(
    connection_name: str = "zee-setup-ap", use_sudo: bool = True, delete: bool = True
) -> bool:
    """Derruba (e opcionalmente remove) o perfil do Access Point."""
    if not nmcli_available():
        return False
    down = _nmcli(["connection", "down", connection_name], privileged=True, timeout=20.0, use_sudo=use_sudo)
    if delete:
        _nmcli(["connection", "delete", connection_name], privileged=True, timeout=20.0, use_sudo=use_sudo)
    log.info("Access Point desativado (%s)", "ok" if down.ok else down.stderr or "já inativo")
    return True


def reconnect_saved(interface: str = "wlan0", use_sudo: bool = True) -> bool:
    """Pede ao NetworkManager para reconectar aos perfis salvos."""
    if not nmcli_available():
        return False
    result = _nmcli(["device", "connect", interface], privileged=True, timeout=45.0, use_sudo=use_sudo)
    if not result.ok:
        log.debug("device connect falhou: %s", result.stderr)
    return result.ok
