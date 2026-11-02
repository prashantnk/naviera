"""
Seeds Logismart Prime zones and their pincodes (DESIGN.md v4 §C.2 `prime_zones`,
`prime_zone_pincodes`), plus the `logismart-test` fixture.

DRY RUN BY DEFAULT: everything runs inside one transaction that is rolled back unless
`--execute` is given. Live `logismart` needs the user's go-ahead before `--execute`.

Usage (from `naviera/backend`):
    poetry run python -m scripts.seed_prime_zones --tenant-slug logismart --pincodes-csv pins.csv
    poetry run python -m scripts.seed_prime_zones --tenant-slug logismart-test --test-fixture --execute

Pincode CSV columns: `pin,city,district,state,is_oda` (e.g. Delhivery's pincode list).
A pincode joins a zone when its city matches one of the zone's aliases; otherwise when
its district does; otherwise when its state is one of the zone's whole states (Delhi).
Ambiguous or unmatched pincodes are reported, never guessed. A pincode already mapped to
a different zone is reported and left where it is.

The alias table `PRIME_ZONE_SPECS` also maps the rate sheet's city spellings (including
its misspellings and routing text, DESIGN §C.1) to zones; `import_prime_lanes.py` uses it.

TODO(D5 follow-up): `--source delhivery` should pull the full pincode list from Delhivery's
pincode API (`GET /c/api/pin-codes/json/`) with `DELHIVERY_B2C_TOKEN`; not built yet.

Spring Boot mapping: a hand-run `CommandLineRunner` in one `@Transactional` method that
rolls back unless `--execute`.
"""

import argparse
import asyncio
import csv
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from app.core.config import settings
from app.core.db import AsyncSessionLocal, async_engine
from app.models.prime import PrimeDeliveryType, PrimeLaneMode, PrimeZone, PrimeZonePincode
from app.repositories.prime_rates import PrimeRatesRepository
from app.services.prime_admin import LaneInput, apply_lane_plan, plan_lane_import
from scripts.tenant_data_core import (
    ALLOWED_TEST_SLUGS,
    apply_transaction_timeouts,
    assert_test_tenant_marked,
    assert_test_tenant_slug,
    get_tenant_by_slug,
)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
BANNER_WIDTH = 78
SAMPLE_SIZE = 15
PINCODE_PATTERN = re.compile(r"^[1-9][0-9]{5}$")
TRUE_TOKENS = frozenset({"true", "1", "yes", "y"})
PINCODE_CSV_COLUMNS = ("pin", "city", "district", "state", "is_oda")
SOURCE_CSV = "csv"
SOURCE_DELHIVERY = "delhivery"


def normalize_place(text: str) -> str:
    """Upper-case letters only: "Chandigarh- IXC" → "CHANDIGARHIXC", "Yamuna Nagar" → "YAMUNANAGAR"."""
    return re.sub(r"[^A-Z]", "", (text or "").upper())


@dataclass(frozen=True)
class ZoneSpec:
    """
    One Prime zone: display name, its state, the spellings that name it, whole states it covers.

    `aliases` are matched (normalised) against pincode city/district names and the sheet's
    FROM/TO CITY cells; `state_spellings` are the sheet's accepted spellings of `state`.
    """

    name: str
    state: str
    aliases: Tuple[str, ...]
    state_spellings: Tuple[str, ...] = ()
    whole_states: Tuple[str, ...] = ()

    @property
    def alias_keys(self) -> FrozenSet[str]:
        """Normalised aliases (the zone name included)."""
        return frozenset(normalize_place(alias) for alias in self.aliases + (self.name,))

    @property
    def state_keys(self) -> FrozenSet[str]:
        """Normalised accepted state spellings (the canonical one included)."""
        return frozenset(normalize_place(item) for item in self.state_spellings + (self.state,))


DELHI_NCR = "Delhi NCR"
HARYANA = ("Haryana", ("HARYANA",))
UP = ("Uttar Pradesh", ("UTTARPRADESH", "UP"))
PUNJAB = ("Punjab", ("PUNJAB",))
MAHARASHTRA = ("Maharashtra", ("MAHARASHTRA", "MAHARSHTRA"))
GUJARAT = ("Gujarat", ("GUJARAT", "GUJRAT"))
MP = ("Madhya Pradesh", ("MADHYAPRADESH", "MP"))
RAJASTHAN = ("Rajasthan", ("RAJASTHAN",))
UTTARAKHAND = ("Uttarakhand", ("UTTARAKHAND", "UTTRAKHAND"))


def _zone(name: str, state: Tuple[str, Tuple[str, ...]], *aliases: str) -> ZoneSpec:
    """A destination zone spec."""
    return ZoneSpec(name=name, state=state[0], aliases=aliases, state_spellings=state[1])


PRIME_ZONE_SPECS: Tuple[ZoneSpec, ...] = (
    ZoneSpec(
        name=DELHI_NCR,
        state="Delhi",
        aliases=(
            "DELHI", "NEW DELHI", "RANGPURI", "MAHIPALPUR", "MAHIPALPUR & PAHARGANJ", "PAHARGANJ", "BAWANA",
            "TUGHLAKABAD", "AJMERI GATE", "NIZAMUDDIN WASHING LINE", "GURGAON", "GURUGRAM", "NOIDA",
            "GAUTAM BUDDHA NAGAR", "GHAZIABAD", "FARIDABAD",
        ),
        state_spellings=("NEW DELHI", "DELHI", "HARYANA"),
        whole_states=("DELHI",),
    ),
    _zone("Agra", UP, "AAGRA", "AGRA"),
    _zone("Ahmedabad", GUJARAT, "AHMEDABAD"),
    _zone("Prayagraj", UP, "ALLAHABAD", "PRAYAGRAJ"),
    _zone("Alwar", RAJASTHAN, "ALWAR"),
    _zone("Ambala", HARYANA, "AMBALA"),
    _zone("Amritsar", PUNJAB, "AMRITSAR- ATQ", "AMRITSAR"),
    _zone("Kolkata", ("West Bengal", ("WESTBENGAL",)), "BADABAZAAR", "BARABAZAR", "KOLKATA"),
    _zone("Bahadurgarh", HARYANA, "BAHADURGARGH", "BAHADURGARH"),
    _zone("Bengaluru", ("Karnataka", ("KARNATAKA",)), "BANGLORE", "BANGALORE", "BENGALURU", "BENGALURU URBAN"),
    _zone("Bathinda", PUNJAB, "BHATINDA", "BATHINDA"),
    _zone("Bhiwandi", MAHARASHTRA, "BHIWANDI"),
    _zone("Bhiwani", HARYANA, "BHIWANI"),
    _zone("Bhopal", MP, "BHOPAL"),
    _zone("Chandigarh", ("Chandigarh", ("CHANDIGARH",)), "CHANDIGARGH", "CHANDIGARH", "CHANDIGARH- IXC"),
    _zone("Chennai", ("Tamil Nadu", ("TAMILNADU",)), "CHENNAI"),
    _zone("Dehradun", UTTARAKHAND, "DEHRADOON", "DEHRADUN"),
    _zone("Dharuhera", HARYANA, "DHARUHERA"),
    _zone("Fatehabad", HARYANA, "FATEHABAD"),
    _zone("Gorakhpur", UP, "GORAKHPUR VIA LUCKNOW", "GORAKHPUR"),
    _zone("Haldwani", UTTARAKHAND, "HALDWAMI", "HALDWANI"),
    _zone("Hisar", HARYANA, "HISAR", "HISSAR"),
    _zone("Hyderabad", ("Telangana", ("TELANGANA",)), "HYDERABAD"),
    _zone("Indore", MP, "INDORE"),
    _zone("Jabalpur", MP, "JABALPUR"),
    _zone("Jaipur", RAJASTHAN, "JAIPUR"),
    _zone("Jalandhar", PUNJAB, "JALANDHAR- JLD", "JALANDHAR"),
    _zone("Jammu", ("Jammu and Kashmir", ("JAMMU & KASHMIR", "JAMMUKASHMIR")), "JAMMU VIA LUDHIANA", "JAMMU"),
    _zone("Jhajjar", HARYANA, "JHAJHAR", "JHAJJAR"),
    _zone("Jind", HARYANA, "JIND"),
    _zone("Kaithal", HARYANA, "KAITHAL"),
    _zone("Kanpur", UP, "KANPUR", "KANPUR NAGAR"),
    _zone("Karnal", HARYANA, "KARNAL"),
    _zone("Kundli", HARYANA, "KUNDALI", "KUNDLI"),
    _zone("Kurukshetra", HARYANA, "KURUKSHETRA"),
    _zone("Lucknow", UP, "LUCKNOW"),
    _zone("Ludhiana", PUNJAB, "LUDHIANA"),
    _zone("Mathura", UP, "MATHURA- MTR", "MATHURA"),
    _zone("Mohali", PUNJAB, "MOHALI", "SAS NAGAR", "SAHIBZADA AJIT SINGH NAGAR"),
    _zone("Mumbai", MAHARASHTRA, "MUMBAI", "MUMBAI SUBURBAN"),
    _zone("Moradabad", UP, "MURADABAD- MBD", "MORADABAD"),
    _zone("Nagpur", MAHARASHTRA, "NAGPUR"),
    _zone("Narnaul", HARYANA, "NARNOL", "NARNAUL"),
    _zone("Panipat", HARYANA, "PANIPAT"),
    _zone("Patna", ("Bihar", ("BIHAR",)), "PATNA"),
    _zone("Pune", MAHARASHTRA, "PUNE"),
    _zone("Raipur", ("Chhattisgarh", ("CHATTISGARH", "CHHATTISGARH")), "RAIPUR"),
    _zone("Ranchi", ("Jharkhand", ("JHARKHAND",)), "RANCHI"),
    _zone("Rewari", HARYANA, "REWARI"),
    _zone("Rohtak", HARYANA, "ROHTAK"),
    _zone("Sirsa", HARYANA, "SIRSA"),
    _zone("Sonipat", HARYANA, "SONIPAT", "SONEPAT"),
    _zone("Surat", GUJARAT, "SURAT"),
    _zone("Vapi", GUJARAT, "VAPI"),
    _zone("Varanasi", UP, "VARANASHI", "VARANASI"),
    _zone("Yamunanagar", HARYANA, "YAMUNA NAGAR", "YAMUNANAGAR"),
)
"""Sheet1's 59 destination spellings + 6 Delhi NCR booking points mapped to 57 zones."""

ROUTING_TEXT_MARKERS = (" VIA ", "- ")
"""Sheet city cells that carry routing text ("JAMMU VIA LUDHIANA", "AMRITSAR- ATQ")."""

TEST_FIXTURE_ZONES: Mapping[str, Mapping[str, bool]] = {
    DELHI_NCR: {"122001": False},
    "Mumbai": {"400001": False, "400009": True},
}
"""`logismart-test` zones: pincode → is_oda (400009 is ODA so golden tests cover the ODA charge)."""

TEST_FIXTURE_TRANSPORTER = "SAMEER TRANSPORT"
TEST_FIXTURE_LANE_RATES: Mapping[str, Decimal] = {
    "rate_per_kg": Decimal("10.00"),
    "min_lr_charge": Decimal("500.00"),
    "docket_charge": Decimal("100.00"),
    "min_chargeable_kg": Decimal("50.00"),
    "volumetric_divisor": Decimal("4500.00"),
    "max_dimension_cm": Decimal("240.00"),
    "oda_per_kg": Decimal("2.00"),
    "oda_min": Decimal("800.00"),
    "odd_weight_per_kg": Decimal("2.00"),
    "odd_weight_min": Decimal("800.00"),
    "pickup_per_kg": Decimal("1.00"),
    "pickup_min": Decimal("600.00"),
    "door_delivery_per_kg": Decimal("1.00"),
    "door_delivery_min": Decimal("600.00"),
}
"""Sheet1 Sameer Transport terms for Rangpuri → Mumbai (rate ₹10/kg, TAT 30 h, GODOWN)."""
TEST_FIXTURE_TAT_HOURS = 30
TEST_FIXTURE_MARKUP = Decimal("20.00")


def _alias_index() -> Dict[str, List[ZoneSpec]]:
    """Normalised alias → zone specs (more than one = ambiguous)."""
    index: Dict[str, List[ZoneSpec]] = defaultdict(list)
    for spec in PRIME_ZONE_SPECS:
        for key in spec.alias_keys:
            index[key].append(spec)
    return index


ALIAS_INDEX: Mapping[str, List[ZoneSpec]] = _alias_index()


def zone_for_place(raw: str) -> Optional[ZoneSpec]:
    """
    The zone a place name (sheet city cell, pincode city or district) belongs to.

    Args:
        raw: The place text as written.

    Returns:
        The single matching zone, or None (unknown or ambiguous).
    """
    matches = ALIAS_INDEX.get(normalize_place(raw), [])
    return matches[0] if len(matches) == 1 else None


def has_routing_text(raw: str) -> bool:
    """True when a sheet city cell carries routing text."""
    padded = f" {(raw or '').upper()} "
    return any(marker in padded for marker in ROUTING_TEXT_MARKERS)


@dataclass(frozen=True)
class PincodeRecord:
    """One row of the pincode CSV."""

    line: int
    pin: str
    city: str
    district: str
    state: str
    is_oda: bool


@dataclass
class ZoneSeedReport:
    """What the zone seed matched and what needs review."""

    matched: Dict[str, Dict[str, bool]] = field(default_factory=lambda: defaultdict(dict))
    unmatched: List[PincodeRecord] = field(default_factory=list)
    invalid: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)


def read_pincode_csv(path: Path) -> Tuple[List[PincodeRecord], List[str]]:
    """
    Reads the pincode CSV.

    Returns:
        Valid records and plain-English problems (bad pin, missing columns).
    """
    problems: List[str] = []
    records: List[PincodeRecord] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in PINCODE_CSV_COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            return [], [f"Pincode CSV is missing columns: {', '.join(missing)}."]
        for line, row in enumerate(reader, start=2):
            pin = (row.get("pin") or "").strip()
            if not PINCODE_PATTERN.match(pin):
                problems.append(f"line {line}: pin '{pin}' is not a 6-digit pincode.")
                continue
            records.append(
                PincodeRecord(
                    line=line,
                    pin=pin,
                    city=(row.get("city") or "").strip(),
                    district=(row.get("district") or "").strip(),
                    state=(row.get("state") or "").strip(),
                    is_oda=(row.get("is_oda") or "").strip().lower() in TRUE_TOKENS,
                )
            )
    return records, problems


def _zone_for_pincode(record: PincodeRecord) -> Optional[ZoneSpec]:
    """City match, else district match, else whole-state match; None when nothing (or several) match."""
    for place in (record.city, record.district):
        zone = zone_for_place(place)
        if zone is not None:
            return zone
    state_key = normalize_place(record.state)
    covering = [spec for spec in PRIME_ZONE_SPECS if state_key in {normalize_place(s) for s in spec.whole_states}]
    return covering[0] if len(covering) == 1 else None


def match_pincodes(records: Sequence[PincodeRecord]) -> ZoneSeedReport:
    """
    Assigns pincodes to zones (pure).

    Args:
        records: Pincode rows.

    Returns:
        Zone → {pin: is_oda}, plus unmatched rows and in-file duplicates.
    """
    report = ZoneSeedReport()
    seen: Dict[str, str] = {}
    for record in records:
        zone = _zone_for_pincode(record)
        if zone is None:
            report.unmatched.append(record)
            continue
        if record.pin in seen and seen[record.pin] != zone.name:
            report.conflicts.append(f"pin {record.pin} matches {seen[record.pin]} and {zone.name} (line {record.line}).")
            continue
        seen[record.pin] = zone.name
        report.matched[zone.name][record.pin] = record.is_oda
    return report


async def _upsert_zone(repo: PrimeRatesRepository, tenant_id: uuid.UUID, spec_name: str, aliases: Sequence[str]) -> PrimeZone:
    """Creates the zone or refreshes its aliases."""
    zone = await repo.get_zone_by_name(tenant_id, spec_name)
    if zone is None:
        zone = PrimeZone(tenant_id=tenant_id, name=spec_name, city_aliases=list(aliases))
    else:
        zone.city_aliases = list(aliases)
    repo.add(zone)
    await repo.flush()
    return zone


async def write_zone_pincodes(
    repo: PrimeRatesRepository,
    tenant_id: uuid.UUID,
    matched: Mapping[str, Mapping[str, bool]],
    aliases: Mapping[str, Sequence[str]],
) -> List[str]:
    """
    Upserts zones and pincodes; a pincode already in another zone is left there and reported.

    Args:
        repo: Repository on the script session.
        tenant_id: Tenant scope.
        matched: Zone name → {pin: is_oda}.
        aliases: Zone name → aliases stored on the zone.

    Returns:
        Conflict messages.
    """
    conflicts: List[str] = []
    for zone_name, pins in matched.items():
        zone = await _upsert_zone(repo, tenant_id, zone_name, aliases.get(zone_name, ()))
        existing = await repo.get_pincode_rows(tenant_id, pins.keys())
        for pin, is_oda in pins.items():
            row = existing.get(pin)
            if row is None:
                repo.add(PrimeZonePincode(tenant_id=tenant_id, zone_id=zone.id, pincode=pin, is_oda=is_oda))
            elif row.zone_id != zone.id:
                conflicts.append(f"pin {pin} is already in another zone; left unchanged (wanted {zone_name}).")
            elif row.is_oda != is_oda:
                row.is_oda = is_oda
                repo.add(row)
    await repo.flush()
    return conflicts


def _fixture_lane() -> LaneInput:
    """The single `logismart-test` lane: Delhi NCR → Mumbai."""
    return LaneInput(
        row=None,
        origin_zone=DELHI_NCR,
        dest_zone="Mumbai",
        mode=PrimeLaneMode.SURFACE,
        transporter_name=TEST_FIXTURE_TRANSPORTER,
        tat_hours=TEST_FIXTURE_TAT_HOURS,
        delivery_type=PrimeDeliveryType.GODOWN,
        rates=dict(TEST_FIXTURE_LANE_RATES),
        markup_percent=TEST_FIXTURE_MARKUP,
        is_active=True,
    )


async def apply_test_fixture(repo: PrimeRatesRepository, tenant_id: uuid.UUID) -> List[str]:
    """
    Writes the `logismart-test` Prime fixture (idempotent): 2 zones, 3 pincodes, 1 active lane.

    Returns:
        Lines describing what was done.
    """
    aliases = {spec.name: list(spec.aliases) for spec in PRIME_ZONE_SPECS}
    conflicts = await write_zone_pincodes(repo, tenant_id, TEST_FIXTURE_ZONES, aliases)
    zones = await repo.list_zones(tenant_id)
    zone_ids = {zone.name: zone.id for zone in zones}
    plan = plan_lane_import([_fixture_lane()], await repo.list_lanes(tenant_id), set(zone_ids))
    if plan.errors:
        return [f"ERROR {issue.message}" for issue in plan.errors]
    await apply_lane_plan(repo, tenant_id, plan, zone_ids, None)
    report = plan.report()
    return conflicts + [
        f"zones: {', '.join(TEST_FIXTURE_ZONES)}; pins: "
        + ", ".join(f"{pin}{' (ODA)' if oda else ''}" for pins in TEST_FIXTURE_ZONES.values() for pin, oda in pins.items()),
        f"lane {DELHI_NCR} → Mumbai: created={report.created} updated={report.updated} deactivated={report.deactivated}",
    ]


def _print_banner(title: str) -> None:
    """Section separator."""
    print("=" * BANNER_WIDTH)
    print(title)
    print("=" * BANNER_WIDTH)


def _print_seed_report(report: ZoneSeedReport, problems: Sequence[str]) -> None:
    """Zone counts, empty zones, unmatched sample, problems."""
    print("Pincodes per zone (review before --execute):")
    for spec in PRIME_ZONE_SPECS:
        pins = report.matched.get(spec.name, {})
        oda = sum(1 for flag in pins.values() if flag)
        flag = "   <-- NO PINCODES, check aliases" if not pins else ""
        print(f"  {spec.name:<14} {len(pins):>6} pins ({oda} ODA){flag}")
    print(f"Unmatched pincodes: {len(report.unmatched)}")
    by_state = Counter(record.state for record in report.unmatched)
    for state, count in by_state.most_common(SAMPLE_SIZE):
        print(f"  {state or '(blank state)'}: {count}")
    for message in list(problems)[:SAMPLE_SIZE] + report.conflicts[:SAMPLE_SIZE]:
        print(f"  ISSUE {message}")


def _parse_args() -> argparse.Namespace:
    """CLI flags (dry run unless `--execute`)."""
    parser = argparse.ArgumentParser(description="Seed Prime zones + pincodes (dry run by default).")
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--source", choices=(SOURCE_CSV, SOURCE_DELHIVERY), default=SOURCE_CSV)
    parser.add_argument("--pincodes-csv", type=Path, help="CSV with pin,city,district,state,is_oda")
    parser.add_argument("--test-fixture", action="store_true", help=f"Write the fixture ({sorted(ALLOWED_TEST_SLUGS)} only)")
    parser.add_argument("--execute", action="store_true", help="Commit (default: roll back)")
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> Optional[str]:
    """A usage problem, or None."""
    if args.source == SOURCE_DELHIVERY:
        if not getattr(settings, "delhivery_b2c_token", None):
            return "--source delhivery needs DELHIVERY_B2C_TOKEN in backend/.env."
        return "--source delhivery is not built yet (TODO D5 follow-up); export the list to CSV instead."
    if args.test_fixture:
        if args.tenant_slug not in ALLOWED_TEST_SLUGS:
            return f"--test-fixture is only for {sorted(ALLOWED_TEST_SLUGS)}."
        return None
    if args.pincodes_csv is None:
        return "Give --pincodes-csv (or --test-fixture for the test tenant)."
    return None


async def _run_once(args: argparse.Namespace) -> int:
    """One transaction: seed, print, commit or roll back."""
    mode = "EXECUTE (COMMIT)" if args.execute else "DRY RUN (ROLLBACK, NO DB CHANGES)"
    _print_banner(f"PRIME ZONES {args.tenant_slug} : {mode}")
    async with AsyncSessionLocal() as session:
        await apply_transaction_timeouts(session)
        tenant = await get_tenant_by_slug(session, args.tenant_slug)
        if tenant is None:
            print(f"Tenant '{args.tenant_slug}' not found.")
            return EXIT_FAILED
        repo = PrimeRatesRepository(session)
        if args.test_fixture:
            assert_test_tenant_slug(args.tenant_slug)
            assert_test_tenant_marked(tenant)
            for line in await apply_test_fixture(repo, tenant.id):
                print(f"  {line}")
        else:
            records, problems = read_pincode_csv(args.pincodes_csv)
            report = match_pincodes(records)
            aliases = {spec.name: list(spec.aliases) for spec in PRIME_ZONE_SPECS}
            report.conflicts.extend(await write_zone_pincodes(repo, tenant.id, report.matched, aliases))
            _print_seed_report(report, problems)
        if args.execute:
            await session.commit()
            print("COMMITTED.")
        else:
            await session.rollback()
            print("ROLLED BACK (dry run).")
    return EXIT_OK


async def _run(args: argparse.Namespace) -> int:
    """Runs once, then disposes the engine."""
    try:
        return await _run_once(args)
    finally:
        await async_engine.dispose()


def main() -> None:
    """CLI entry point."""
    args = _parse_args()
    problem = _validate_args(args)
    if problem:
        print(problem)
        raise SystemExit(EXIT_USAGE)
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
