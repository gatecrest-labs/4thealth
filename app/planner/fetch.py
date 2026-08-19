# app/planner/fetch.py
"""Bridge: builds DeviceSnapshot from data already fetched by 4thealth's FMGClient.

The planner engine expects typed catalog objects (AddressCatalog, ServiceCatalog)
rather than raw dict lookups. This module converts 4thealth's pre-fetched FMG
dicts into those typed structures without making additional network calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.planner.matching import AddressCatalog, ServiceCatalog


@dataclass
class DeviceSnapshot:
    device: str
    adom: str
    addr_catalog: AddressCatalog
    svc_catalog: ServiceCatalog
    policies_by_package: dict[str, list[dict]]
    interfaces: list[dict]
    routing_table: list[dict] = field(default_factory=list)
    degraded: bool = False
    failures: list[str] = field(default_factory=list)


def build_snapshot(
    adom: str,
    device: str,
    addr_objects: list[dict],
    addr_groups: list[dict],
    svc_objects: list[dict],
    svc_groups: list[dict],
    policies_by_package: dict[str, list[dict]],
    interfaces: list[dict],
    routing_table: list[dict] | tuple = (),
) -> DeviceSnapshot:
    """Wrap pre-fetched FMG data into a DeviceSnapshot for the planner engine.

    policies_by_package keys use the same "{adom}/{pkg_path}" convention as
    the existing rule_review_routes.py (the route already builds this dict).
    """
    return DeviceSnapshot(
        device=device,
        adom=adom,
        addr_catalog=AddressCatalog(addr_objects, addr_groups),
        svc_catalog=ServiceCatalog(svc_objects, svc_groups),
        policies_by_package=dict(policies_by_package),
        interfaces=list(interfaces),
        routing_table=list(routing_table),
    )
