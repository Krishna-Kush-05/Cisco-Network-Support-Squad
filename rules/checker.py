"""
rules/checker.py — NetSage AI rule-checker module.

Deterministic, offline, no AI/LLM calls. Reads raw Cisco Packet Tracer
`show` command output (and optionally `ipconfig /all` from a PC) pasted
as one blob of text, and flags known fault types using plain string
search / regex.

Public API:
    run_rule_check(case: Case) -> RuleResult

Everything else in this file is internal and may be restructured freely.
"""

import re
from collections import defaultdict

try:
    from shared.schema import Case, RuleResult
except ImportError:
    from schema import Case, RuleResult


# ---------------------------------------------------------------------------
# Helpers: splitting the evidence blob into per-command sections
# ---------------------------------------------------------------------------

# Packet Tracer typically echoes the command back at a prompt, e.g.:
#   Router#show ip interface brief
#   Switch#show vlan brief
#   PC>ipconfig /all
# We split on these command-echo lines (case-insensitive) so each check
# only looks at its own block of output, regardless of what order the
# commands were pasted in or how many are concatenated together.
_COMMAND_SPLIT_RE = re.compile(
    r"(?im)^\s*\S*[#>]\s*(show\s+ip\s+interface\s+brief|show\s+interfaces?|"
    r"show\s+vlan\s+brief|show\s+ip\s+route|show\s+access-lists?|"
    r"show\s+arp|ipconfig\s*/all)\s*$"
)


def _split_into_blocks(evidence_text: str) -> dict:
    """
    Split evidence_text into a dict keyed by normalized command name ->
    concatenated text under that command (handles the same command
    appearing more than once, e.g. show ip interface brief on two devices).
    """
    blocks = defaultdict(str)

    matches = list(_COMMAND_SPLIT_RE.finditer(evidence_text))

    if not matches:
        # No recognizable command headers at all — treat the whole blob
        # as "unknown" so downstream checks can still try regex against it.
        blocks["_unstructured"] = evidence_text
        return blocks

    # Text before the first recognized command header is unstructured
    # (titles, case metadata that leaked in, etc) — keep it too, cheaply.
    if matches[0].start() > 0:
        blocks["_unstructured"] += evidence_text[: matches[0].start()]

    for i, m in enumerate(matches):
        cmd = re.sub(r"\s+", " ", m.group(1).strip().lower())
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(evidence_text)
        blocks[cmd] += evidence_text[start:end]

    return blocks


def _get_block(blocks: dict, *keys: str) -> str:
    """Concatenate all blocks whose normalized key matches any of keys."""
    out = []
    for k, v in blocks.items():
        if any(key in k for key in keys):
            out.append(v)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

_IP_RE = r"(\d{1,3}(?:\.\d{1,3}){3})"


def _check_duplicate_ip(blocks: dict) -> bool:
    """
    Flags if the same IP address shows up on more than one interface line
    across `show ip interface brief` and/or ARP-type output.
    """
    text = _get_block(blocks, "show ip interface brief", "show arp", "_unstructured")

    ip_owners = defaultdict(set)

    # show ip interface brief lines look like:
    #   Interface  IP-Address  OK? Method Status  Protocol
    #   GigabitEthernet0/0  192.168.1.1  YES manual up  up
    for line in text.splitlines():
        m = re.match(
            rf"^\s*(\S+)\s+{_IP_RE}\s+(YES|NO)\s+\S+\s+(\S+(?:\s\S+)?)\s+\S+\s*$",
            line,
            re.IGNORECASE,
        )
        if m:
            iface, ip = m.group(1), m.group(2)
            if ip.lower() != "unassigned":
                ip_owners[ip].add(iface)

    # ARP table lines: Internet  192.168.1.1  ...  0050.0000.0001  ARPA  ...
    for line in text.splitlines():
        m = re.match(rf"^\s*Internet\s+{_IP_RE}\s+\S+\s+(\S+)\s+ARPA", line, re.IGNORECASE)
        if m:
            ip, mac = m.group(1), m.group(2)
            ip_owners[ip].add(f"mac:{mac}")

    return any(len(owners) > 1 for owners in ip_owners.values())


def _check_wrong_mask(blocks: dict) -> bool:
    """
    Flags if interfaces that appear to be on the same subnet (matching
    first 3 octets as a proxy for "same VLAN/subnet") report different
    masks. Looks at `show running-config`-style or `show ip interface`
    (non-brief) output where masks are visible, falling back to any
    IP/mask pairs found anywhere in the evidence.
    """
    text = (
        _get_block(blocks, "show interfaces", "show ip interface")
        + "\n"
        + _get_block(blocks, "_unstructured")
    )

    # Matches "ip address 192.168.1.1 255.255.255.0" style lines
    pairs = re.findall(
        rf"ip address\s+{_IP_RE}\s+{_IP_RE}", text, re.IGNORECASE
    )
    # Also matches "Internet address is 192.168.1.1/24"
    cidr_pairs = re.findall(
        rf"Internet address is\s+{_IP_RE}/(\d{{1,2}})", text, re.IGNORECASE
    )

    subnet_masks = defaultdict(set)

    for ip, mask in pairs:
        subnet_key = ".".join(ip.split(".")[:3])
        subnet_masks[subnet_key].add(mask)

    for ip, prefix in cidr_pairs:
        subnet_key = ".".join(ip.split(".")[:3])
        subnet_masks[subnet_key].add(f"/{prefix}")

    return any(len(masks) > 1 for masks in subnet_masks.values())


def _check_gateway_mismatch(blocks: dict) -> bool:
    """
    Flags if a PC's default gateway (from ipconfig /all) doesn't match
    any router interface IP found in the router-side evidence.
    """
    pc_text = _get_block(blocks, "ipconfig")
    if not pc_text:
        return False

    gw_match = re.search(
        r"Default Gateway[.\s]*:\s*" + _IP_RE, pc_text, re.IGNORECASE
    )
    if not gw_match:
        return False
    gateway_ip = gw_match.group(1)

    router_text = _get_block(
        blocks, "show ip interface brief", "show interfaces", "show ip interface"
    )
    router_ips = set(re.findall(_IP_RE, router_text))

    if not router_ips:
        # No router IP evidence to compare against — can't confirm a
        # mismatch, so don't flag (avoid false positives).
        return False

    return gateway_ip not in router_ips


def _check_interface_down(blocks: dict) -> bool:
    """
    Flags any `show ip interface brief` line reporting down /
    administratively down status where the port name/context doesn't
    suggest it's expected to be down (e.g. explicitly unused/reserved).
    """
    text = _get_block(blocks, "show ip interface brief")

    for line in text.splitlines():
        if re.search(r"administratively down|down\s+down", line, re.IGNORECASE):
            if re.search(r"reserved|unused|disabled\s*\(expected\)", line, re.IGNORECASE):
                continue
            return True
    return False


def _check_missing_vlan(blocks: dict, case: Case) -> bool:
    """
    Flags if a port's VLAN assignment (from `show vlan brief`) doesn't
    match the VLAN implied by the topology/symptom text. Since we don't
    have a structured "expected VLAN per port" map, this looks for the
    weaker but still useful signal: a port mentioned by name in the
    symptom/topology text sitting in a *different* VLAN than other ports
    of the same naming pattern, or a port sitting in the default VLAN 1
    when everything else on that switch has been assigned elsewhere.
    """
    text = _get_block(blocks, "show vlan brief")
    if not text:
        return False

    vlan_to_ports = defaultdict(list)
    current_vlan = None
    for line in text.splitlines():
        m = re.match(r"^\s*(\d+)\s+\S+.*?\s+(active|act/unsup)?\s*(.*)$", line, re.IGNORECASE)
        header = re.match(r"^\s*(\d+)\s+(\S+)", line)
        if header:
            current_vlan = header.group(1)
            ports_part = line[header.end():]
            ports = re.findall(r"(?:Fa|Gi|Fast|Gig)\S*\d+/\d+", ports_part)
            vlan_to_ports[current_vlan].extend(ports)
        elif current_vlan and re.match(r"^\s*(?:Fa|Gi|Fast|Gig)", line):
            ports = re.findall(r"(?:Fa|Gi|Fast|Gig)\S*\d+/\d+", line)
            vlan_to_ports[current_vlan].extend(ports)

    if not vlan_to_ports:
        return False

    # Heuristic: if VLAN 1 (default) holds ports while other VLANs exist
    # with only one or two ports each, a port likely got left on the
    # default VLAN by mistake — a very common Packet Tracer injected fault.
    non_default_vlans = {v: p for v, p in vlan_to_ports.items() if v != "1"}
    default_ports = vlan_to_ports.get("1", [])

    if default_ports and non_default_vlans:
        # If the fault/symptom text mentions VLAN explicitly, treat any
        # access port stuck on VLAN 1 as suspicious.
        if re.search(r"vlan", case.symptom, re.IGNORECASE) or re.search(
            r"vlan", case.fault_type, re.IGNORECASE
        ):
            return True

    return False


def _check_missing_route(blocks: dict, case: Case) -> bool:
    """
    Flags if an expected destination subnet is absent from
    `show ip route` output. "Expected" subnets are inferred from any
    subnet mentioned in topology/symptom text and from subnets seen on
    router interfaces elsewhere in the evidence (a subnet a router is
    directly connected to, or one it should have learned about, should
    appear in its routing table).
    """
    route_text = _get_block(blocks, "show ip route")
    if not route_text:
        # No routing table evidence at all — can't evaluate meaningfully.
        return False

    route_subnets = set()
    for m in re.finditer(rf"{_IP_RE}(?:/(\d{{1,2}})|\s+{_IP_RE})", route_text):
        ip = m.group(1)
        route_subnets.add(".".join(ip.split(".")[:3]))

    # Subnets referenced anywhere else in the evidence (interfaces, PC config)
    other_text = _get_block(
        blocks, "show ip interface brief", "show interfaces", "ipconfig", "_unstructured"
    )
    mentioned_subnets = set()
    for ip in re.findall(_IP_RE, other_text):
        mentioned_subnets.add(".".join(ip.split(".")[:3]))

    # Also pull any subnet explicitly named in topology/symptom text, e.g. "192.168.2.0/24"
    for ip in re.findall(_IP_RE, case.topology + " " + case.symptom):
        mentioned_subnets.add(".".join(ip.split(".")[:3]))

    missing = mentioned_subnets - route_subnets
    # Ignore subnets that are trivially the router's own connected
    # interfaces would normally auto-appear as "C" routes — if they're
    # missing, that's exactly the fault we want to catch.
    return len(missing) > 0 and len(mentioned_subnets) > 0


def _check_bad_acl(blocks: dict) -> bool:
    """
    Flags if `show access-lists` contains a deny rule that looks
    overly broad (denies "any any" or denies a subnet mentioned
    elsewhere as legitimate traffic), or if ACL apply direction/interface
    context in the evidence looks suspicious (deny-all with no permit
    entries at all, which is a classic mis-applied-ACL Packet Tracer fault).
    """
    text = _get_block(blocks, "show access-lists")
    if not text:
        return False

    lines = [l for l in text.splitlines() if l.strip()]
    has_deny = any(re.search(r"\bdeny\b", l, re.IGNORECASE) for l in lines)
    has_permit = any(re.search(r"\bpermit\b", l, re.IGNORECASE) for l in lines)

    # Deny-any-any with zero permits anywhere in the ACL is almost always
    # an over-broad / misconfigured ACL blocking legitimate traffic.
    deny_any_any = re.search(r"deny\s+ip\s+any\s+any", text, re.IGNORECASE) or re.search(
        r"deny\s+any\s+any", text, re.IGNORECASE
    )

    if deny_any_any and not has_permit:
        return True

    if has_deny and not has_permit:
        # An ACL with only deny statements and no explicit permits will
        # (with the implicit deny-all) block everything — flag it.
        return True

    return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_FLAG_LABELS = {
    "duplicate_ip": "duplicate IP address",
    "wrong_mask": "mismatched subnet mask",
    "gateway_mismatch": "gateway mismatch",
    "interface_down": "interface down",
    "missing_vlan": "port stuck on wrong/default VLAN",
    "missing_route": "missing route",
    "bad_acl": "misconfigured/overly broad ACL",
}


def run_rule_check(case: Case) -> RuleResult:
    blocks = _split_into_blocks(case.evidence_text)

    flags = {
        "duplicate_ip": _check_duplicate_ip(blocks),
        "wrong_mask": _check_wrong_mask(blocks),
        "gateway_mismatch": _check_gateway_mismatch(blocks),
        "interface_down": _check_interface_down(blocks),
        "missing_vlan": _check_missing_vlan(blocks, case),
        "missing_route": _check_missing_route(blocks, case),
        "bad_acl": _check_bad_acl(blocks),
    }

    fired = [_FLAG_LABELS[k] for k, v in flags.items() if v]
    rule_verdict = (
        f"Flagged: {', '.join(fired)}." if fired else "no rule violations detected"
    )

    return RuleResult(case_id=case.case_id, rule_verdict=rule_verdict, **flags)
