"""Shared eBUSd TCP endpoint discovery, probing, and fallback connection helpers."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .const import (
    DEFAULT_EBUSD_TCP_PORT,
    MANUFACTURER_SAUNIER_DUVAL,
    MANUFACTURER_VAILLANT,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

EBUSD_ADDON_HOST_CANDIDATES: tuple[str, ...] = (
    "b4d7ad18-ebusd",
    "local-ebusd",
    "ebusd",
    "ebusd.local",
)
DEFAULT_TCP_PROBE_TIMEOUT: float = 0.8
LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost"})
_EBUSD_INFO_MARKERS: tuple[str, ...] = (
    "version:",
    "signal:",
    "symbol rate:",
    "masters:",
    "address ",
)


def _is_supervisor_present(hass: HomeAssistant | None) -> bool:
    """Return True only when Home Assistant Supervisor (hassio) is genuinely loaded."""
    if hass is None:
        return False

    try:
        system_info = importlib.import_module("homeassistant.helpers.system_info")
        is_hassio_fn = getattr(system_info, "is_hassio", None)
        if callable(is_hassio_fn) and is_hassio_fn(hass) is True:
            return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Optional is_hassio check unavailable: %s", err)

    config = getattr(hass, "config", None)
    components = getattr(config, "components", None)
    return isinstance(components, (set, list, tuple, frozenset)) and (
        "hassio" in components
    )


def _extract_addon_endpoints(
    slug: str,
    info: Any,
    default_port: int,
) -> list[tuple[str, int]]:
    """Extract (host, port) candidates from a Supervisor add-on metadata payload."""
    if isinstance(info, dict):
        name = str(info.get("name", ""))
        hostname = str(info.get("hostname") or "").strip()
        ip_address = str(info.get("ip_address") or "").strip()
        network = info.get("network")
    else:
        name = str(getattr(info, "name", ""))
        hostname = str(getattr(info, "hostname", "") or "").strip()
        ip_address = str(getattr(info, "ip_address", "") or "").strip()
        network = getattr(info, "network", None)

    if "ebusd" not in slug.lower() and "ebusd" not in name.lower():
        return []

    ports: list[int] = [int(default_port)]
    if isinstance(network, dict):
        for key, mapped_port in network.items():
            container_port_str = str(key).split("/", 1)[0].strip()
            with contextlib.suppress(ValueError, TypeError):
                container_port = int(container_port_str)
                if 1 <= container_port <= 65535 and container_port not in ports:
                    ports.insert(0, container_port)
            if mapped_port is not None:
                with contextlib.suppress(ValueError, TypeError):
                    mapped_int = int(mapped_port)
                    if 1 <= mapped_int <= 65535 and mapped_int not in ports:
                        ports.append(mapped_int)

    hosts: list[str] = []
    for candidate in (hostname, slug.replace("_", "-"), ip_address):
        clean = candidate.strip()
        if clean and clean not in hosts:
            hosts.append(clean)

    endpoints: list[tuple[str, int]] = []
    for host in hosts:
        for port in ports:
            endpoints.append((host, port))
    return endpoints


async def _async_discover_hassio_endpoints(
    hass: HomeAssistant | None,
    default_port: int,
) -> list[tuple[str, int]]:
    """Optionally query Home Assistant Supervisor for installed eBUSd add-ons."""
    if not _is_supervisor_present(hass) or hass is None:
        return []

    discovered_started: list[tuple[str, int]] = []
    discovered_other: list[tuple[str, int]] = []

    try:
        hassio = importlib.import_module("homeassistant.components.hassio")

        addons_info: Any = None
        get_addons_info = getattr(hassio, "get_addons_info", None)
        if callable(get_addons_info):
            addons_info = get_addons_info(hass)
        elif hasattr(hassio, "coordinator"):
            coord_get = getattr(hassio.coordinator, "get_addons_info", None)
            if callable(coord_get):
                addons_info = coord_get(hass)

        if isinstance(addons_info, dict) and addons_info:
            for slug, info in addons_info.items():
                eps = _extract_addon_endpoints(str(slug), info, default_port)
                if not eps:
                    continue
                state = (
                    info.get("state")
                    if isinstance(info, dict)
                    else getattr(info, "state", None)
                )
                target = discovered_started if state == "started" else discovered_other
                target.extend(eps)
            return [*discovered_started, *discovered_other]

        get_client: Any = getattr(hassio, "get_supervisor_client", None)
        if callable(get_client):
            client: Any = get_client(hass)
            addons_api: Any = getattr(client, "addons", None)
            list_fn: Any = getattr(addons_api, "list", None) if addons_api else None
            if callable(list_fn):
                list_res: Any = list_fn()
                addons_list: Any = (
                    await list_res if inspect.isawaitable(list_res) else list_res
                )
                if isinstance(addons_list, (list, tuple)):
                    for addon in addons_list:
                        slug = str(
                            addon.get("slug", "")
                            if isinstance(addon, dict)
                            else getattr(addon, "slug", "")
                        )
                        if not slug:
                            continue
                        info_obj: Any = addon
                        addon_info_fn: Any = getattr(addons_api, "addon_info", None)
                        if (
                            "ebusd" in slug.lower()
                            or "ebusd"
                            in str(
                                addon.get("name", "")
                                if isinstance(addon, dict)
                                else getattr(addon, "name", "")
                            ).lower()
                        ) and callable(addon_info_fn):
                            with contextlib.suppress(Exception):
                                info_res: Any = addon_info_fn(slug)
                                info_obj = (
                                    await info_res
                                    if inspect.isawaitable(info_res)
                                    else info_res
                                )
                        eps = _extract_addon_endpoints(slug, info_obj, default_port)
                        if not eps:
                            continue
                        state = (
                            addon.get("state")
                            if isinstance(addon, dict)
                            else getattr(addon, "state", None)
                        )
                        target = (
                            discovered_started
                            if state == "started"
                            else discovered_other
                        )
                        target.extend(eps)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Optional hassio eBUSd add-on discovery skipped: %s", err)

    return [*discovered_started, *discovered_other]


async def async_check_hassio_seed_mqtt_cfg(hass: HomeAssistant | None) -> bool | None:
    """Optionally inspect Supervisor eBUSd add-on options for seed_mqtt_cfg.

    Returns True if an active eBUSd add-on explicitly has seed_mqtt_cfg=True,
    False if explicitly False, or None if unavailable (non-Supervisor / API drift).
    """
    if not _is_supervisor_present(hass) or hass is None:
        return None

    try:
        hassio = importlib.import_module("homeassistant.components.hassio")
        get_client: Any = getattr(hassio, "get_supervisor_client", None)
        if not callable(get_client):
            return None

        client: Any = get_client(hass)
        addons_api: Any = getattr(client, "addons", None)
        list_fn: Any = getattr(addons_api, "list", None) if addons_api else None
        addon_info_fn: Any = (
            getattr(addons_api, "addon_info", None) if addons_api else None
        )
        if not callable(list_fn) or not callable(addon_info_fn):
            return None

        list_res: Any = list_fn()
        addons_list: Any = await list_res if inspect.isawaitable(list_res) else list_res
        if not isinstance(addons_list, (list, tuple)):
            return None

        for addon in addons_list:
            slug = str(
                addon.get("slug", "")
                if isinstance(addon, dict)
                else getattr(addon, "slug", "")
            )
            name = str(
                addon.get("name", "")
                if isinstance(addon, dict)
                else getattr(addon, "name", "")
            )
            state = (
                addon.get("state")
                if isinstance(addon, dict)
                else getattr(addon, "state", None)
            )
            if state != "started" or (
                "ebusd" not in slug.lower() and "ebusd" not in name.lower()
            ):
                continue
            info_res: Any = addon_info_fn(slug)
            info: Any = await info_res if inspect.isawaitable(info_res) else info_res
            options = (
                info.get("options")
                if isinstance(info, dict)
                else getattr(info, "options", None)
            )
            if isinstance(options, dict) and "seed_mqtt_cfg" in options:
                return bool(options["seed_mqtt_cfg"])
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Optional hassio seed_mqtt_cfg inspection skipped: %s", err)

    return None


def _get_config_entry_endpoints(
    hass: HomeAssistant | None,
    default_port: int,
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Read host hints from existing core 'ebusd' and 'mqtt' config entries."""
    ebusd_entries: list[tuple[str, int]] = []
    mqtt_entries: list[tuple[str, int]] = []
    if hass is None:
        return ebusd_entries, mqtt_entries

    cfg_entries = getattr(hass, "config_entries", None)
    async_entries = getattr(cfg_entries, "async_entries", None)
    if not callable(async_entries):
        return ebusd_entries, mqtt_entries

    try:
        core_ebusd = async_entries("ebusd")
        if isinstance(core_ebusd, (list, tuple)):
            for entry in core_ebusd:
                data = getattr(entry, "data", None)
                if not isinstance(data, dict):
                    continue
                host = str(data.get("host") or "").strip()
                if not host:
                    continue
                try:
                    entry_port = int(data.get("port") or default_port)
                except (ValueError, TypeError):
                    entry_port = default_port
                ebusd_entries.append((host, entry_port))
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Failed reading ebusd config entry hints: %s", err)

    try:
        mqtt_cfgs = async_entries("mqtt")
        if isinstance(mqtt_cfgs, (list, tuple)):
            for entry in mqtt_cfgs:
                data = getattr(entry, "data", None)
                if not isinstance(data, dict):
                    continue
                broker = str(data.get("broker") or "").strip()
                if broker and broker not in LOOPBACK_HOSTS:
                    mqtt_entries.append((broker, default_port))
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Failed reading mqtt broker host hints: %s", err)

    return ebusd_entries, mqtt_entries


async def async_get_ebusd_tcp_candidates(
    hass: HomeAssistant | None,
    configured_host: str | None = None,
    port: int = DEFAULT_EBUSD_TCP_PORT,
) -> list[tuple[str, int]]:
    """Return ordered, deduplicated (host, port) candidates for connecting to eBUSd.

    If a custom non-loopback host is configured, only that endpoint is tried.
    Otherwise, Supervisor add-ons and HA add-on/container hostnames are tried
    first, followed by loopback (127.0.0.1) and external MQTT broker hints.
    """
    port_int = int(port)
    host_clean = (configured_host or "").strip()

    if host_clean and host_clean not in LOOPBACK_HOSTS:
        return [(host_clean, port_int)]

    raw_candidates: list[tuple[str, int]] = []
    raw_candidates.extend(await _async_discover_hassio_endpoints(hass, port_int))

    ebusd_entries, mqtt_entries = _get_config_entry_endpoints(hass, port_int)
    raw_candidates.extend(ebusd_entries)

    for addon_host in EBUSD_ADDON_HOST_CANDIDATES:
        raw_candidates.append((addon_host, port_int))

    if host_clean == "localhost":
        raw_candidates.append(("localhost", port_int))
    raw_candidates.append(("127.0.0.1", port_int))

    raw_candidates.extend(mqtt_entries)

    deduped: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for item in raw_candidates:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


async def async_open_ebusd_tcp_connection(
    hass: HomeAssistant | None,
    host: str,
    port: int,
    timeout: float = 3.0,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, str, int]:
    """Open TCP connection to eBUSd, trying add-on hostnames before loopback."""
    candidates = await async_get_ebusd_tcp_candidates(hass, host, port)
    last_err: BaseException | None = None

    for cand_host, cand_port in candidates:
        try:
            connect_coro = asyncio.open_connection(cand_host, cand_port)
            reader, writer = await asyncio.wait_for(connect_coro, timeout=timeout)
            _LOGGER.debug(
                "Connected to eBUSd TCP socket at '%s:%s'", cand_host, cand_port
            )
            return reader, writer, cand_host, cand_port
        except (TimeoutError, OSError) as err:
            last_err = err
            continue

    if last_err is not None:
        raise last_err
    raise OSError(f"No TCP candidates available for eBUSd ({host}:{port})")


async def async_probe_ebusd_tcp(
    hass: HomeAssistant | None,
    configured_host: str | None = None,
    port: int = DEFAULT_EBUSD_TCP_PORT,
    timeout: float = DEFAULT_TCP_PROBE_TIMEOUT,
) -> tuple[str, int] | None:
    """Probe candidates and verify the endpoint speaks the eBUSd TCP protocol."""
    candidates = await async_get_ebusd_tcp_candidates(hass, configured_host, port)

    for cand_host, cand_port in candidates:
        writer: asyncio.StreamWriter | None = None
        try:
            connect_coro = asyncio.open_connection(cand_host, cand_port)
            reader, writer = await asyncio.wait_for(connect_coro, timeout=timeout)
            writer.write(b"info\n")
            await asyncio.wait_for(writer.drain(), timeout=timeout)

            for _ in range(12):
                line_bytes = await asyncio.wait_for(reader.readline(), timeout=timeout)
                if not line_bytes:
                    break
                line = line_bytes.decode("ascii", errors="replace").strip().lower()
                if not line:
                    break
                if any(marker in line for marker in _EBUSD_INFO_MARKERS):
                    _LOGGER.info(
                        "Auto-discovered live eBUSd TCP daemon at %s:%s",
                        cand_host,
                        cand_port,
                    )
                    return cand_host, cand_port
        except (TimeoutError, OSError):
            continue
        finally:
            if writer is not None:
                writer.close()
                with contextlib.suppress(OSError):
                    await writer.wait_closed()

    return None


@dataclass(frozen=True, slots=True)
class EbusdBusHardware:
    """Hardware topology auto-detected from an eBUSd TCP `info` probe."""

    endpoint: tuple[str, int]
    has_migo_link: bool | None = None
    has_wireless_room_unit: bool | None = None
    has_vr70: bool | None = None
    manufacturer: str | None = None


def parse_ebusd_info_hardware(
    lines: list[str],
    endpoint: tuple[str, int],
) -> EbusdBusHardware:
    """Parse eBUSd `info` lines into detected bus accessories and manufacturer.

    Only sets boolean accessory flags when eBUS signal is acquired and at least
    one non-ebusd slave device has been scanned, avoiding false negatives on a
    cold/unscanned bus.
    """
    signal_acquired: bool | None = None
    master_addrs: set[str] = set()
    scanned_devices: dict[str, tuple[str, str]] = {}

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("signal:"):
            signal_acquired = "acquired" in low
            continue
        if not low.startswith("address ") or ":" not in line:
            continue
        addr_part, _, rest = line.partition(":")
        addr = addr_part[len("address ") :].strip().lower()
        rest_low = rest.lower()
        if "ebusd" in rest_low:
            continue
        if "master" in rest_low:
            master_addrs.add(addr)
        if 'scanned "' in rest:
            scanned_str = rest.partition('scanned "')[2].partition('"')[0]
            fields = dict(
                item.split("=", 1) for item in scanned_str.split(";") if "=" in item
            )
            dev_id = fields.get("ID", "").strip().upper()
            loaded_csv = (
                rest.partition(', loaded "')[2].partition('"')[0].strip().lower()
                if ', loaded "' in rest
                else ""
            )
            scanned_devices[addr] = (dev_id, loaded_csv)

    if signal_acquired is False or not scanned_devices:
        return EbusdBusHardware(endpoint=endpoint)

    f6_id, f6_csv = scanned_devices.get("f6", ("", ""))
    addr04_id, addr04_csv = scanned_devices.get("04", ("", ""))

    has_migo_link = "f1" in master_addrs or f6_id.startswith(("NETX", "VR9"))
    has_wireless_room_unit = ("NETX3" in addr04_id or "04.netx3" in addr04_csv) or (
        "NETX3" in f6_id or "f6.netx3" in f6_csv
    )
    has_vr70 = any(
        "VR_70" in dev_id or "vr_70" in loaded_csv
        for addr, (dev_id, loaded_csv) in scanned_devices.items()
        if addr in ("52", "53")
    )

    manufacturer: str | None = None
    ctrl_id = scanned_devices.get("15", ("", ""))[0]
    if ctrl_id == "BASS3":
        manufacturer = MANUFACTURER_SAUNIER_DUVAL
    elif ctrl_id in ("BASV3", "CTLV2", "CTLV3"):
        manufacturer = MANUFACTURER_VAILLANT

    return EbusdBusHardware(
        endpoint=endpoint,
        has_migo_link=has_migo_link,
        has_wireless_room_unit=has_wireless_room_unit,
        has_vr70=has_vr70,
        manufacturer=manufacturer,
    )


async def async_probe_ebusd_bus_hardware(
    hass: HomeAssistant | None,
    configured_host: str | None = None,
    port: int = DEFAULT_EBUSD_TCP_PORT,
    timeout: float = DEFAULT_TCP_PROBE_TIMEOUT,
) -> EbusdBusHardware | None:
    """Probe eBUSd TCP candidates and parse `info` to pre-detect bus hardware."""
    candidates = await async_get_ebusd_tcp_candidates(hass, configured_host, port)

    for cand_host, cand_port in candidates:
        writer: asyncio.StreamWriter | None = None
        try:
            connect_coro = asyncio.open_connection(cand_host, cand_port)
            reader, writer = await asyncio.wait_for(connect_coro, timeout=timeout)
            writer.write(b"info\n")
            await asyncio.wait_for(writer.drain(), timeout=timeout)

            lines: list[str] = []
            is_ebusd = False
            for _ in range(80):
                try:
                    line_bytes = await asyncio.wait_for(
                        reader.readline(), timeout=timeout
                    )
                except TimeoutError:
                    break
                if not line_bytes:
                    break
                decoded = line_bytes.decode("ascii", errors="replace").strip()
                if not decoded:
                    if lines:
                        break
                    continue
                lines.append(decoded)
                if any(marker in decoded.lower() for marker in _EBUSD_INFO_MARKERS):
                    is_ebusd = True

            if is_ebusd:
                detected = parse_ebusd_info_hardware(lines, (cand_host, cand_port))
                _LOGGER.info(
                    "Auto-detected eBUSd hardware at %s:%s (manufacturer=%s, gateway=%s, wireless=%s, vr70=%s)",
                    cand_host,
                    cand_port,
                    detected.manufacturer,
                    detected.has_migo_link,
                    detected.has_wireless_room_unit,
                    detected.has_vr70,
                )
                return detected
        except (TimeoutError, OSError):
            continue
        finally:
            if writer is not None:
                writer.close()
                with contextlib.suppress(OSError):
                    await writer.wait_closed()

    return None
