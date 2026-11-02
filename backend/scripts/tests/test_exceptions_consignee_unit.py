"""
Unit tests for the NDR "Update consignee" snapshot (journey:staff fix).

The consignee name typed in the Delivery Exceptions dialog used to be pasted into the
remark only; it is now saved on the new delivery-address snapshot like phone / address.
No database: `_build_consignee_snapshot` is a pure function of the shipment and request.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.pickups import Address, NdrAction, ShipmentType
from app.schemas.v1.exceptions import NdrActionRequest
from app.services.exceptions import ExceptionsService

PINCODE = "122002"


def _address(name: str = "Asha Verma") -> Address:
    """Current consignee address of the shipment."""
    return Address(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name=name,
        phone="9810011177",
        address_line1="Flat 7, DLF Phase 2",
        city="Gurugram",
        state="Haryana",
        pincode=PINCODE,
        country="IN",
    )


def _service() -> ExceptionsService:
    """Service instance without collaborators (only the pure snapshot helper is used)."""
    return ExceptionsService.__new__(ExceptionsService)


def _shipment(address: Address) -> SimpleNamespace:
    """Forward shipment stand-in carrying the consignee address."""
    return SimpleNamespace(
        tenant_id=address.tenant_id,
        shipment_type=ShipmentType.FORWARD,
        delivery_address=address,
        pickup_address=None,
    )


def test_consignee_name_is_saved_on_the_snapshot() -> None:
    current = _address()
    request = NdrActionRequest(
        action=NdrAction.UPDATE_CONSIGNEE,
        consignee_name="  Rahul Verma ",
        consignee_pincode=PINCODE,
    )
    snapshot, changes = _service()._build_consignee_snapshot(_shipment(current), request)
    assert snapshot.name == "Rahul Verma"
    assert snapshot.phone == current.phone
    assert changes == {"name": {"old": "Asha Verma", "new": "Rahul Verma"}}


def test_name_only_request_counts_as_a_consignee_edit() -> None:
    request = NdrActionRequest(action=NdrAction.REATTEMPT, consignee_name="Rahul Verma")
    assert ExceptionsService._has_consignee_edit(request) is True
    assert ExceptionsService._has_consignee_edit(NdrActionRequest(action=NdrAction.REATTEMPT)) is False


def test_blank_name_keeps_the_current_name() -> None:
    current = _address()
    request = NdrActionRequest(
        action=NdrAction.UPDATE_CONSIGNEE,
        consignee_phone="9123456780",
        consignee_pincode=PINCODE,
    )
    snapshot, changes = _service()._build_consignee_snapshot(_shipment(current), request)
    assert snapshot.name == "Asha Verma"
    assert "name" not in changes
    assert changes["phone"]["new"] == "9123456780"


def test_pincode_change_is_still_refused() -> None:
    request = NdrActionRequest(
        action=NdrAction.UPDATE_CONSIGNEE, consignee_name="Rahul Verma", consignee_pincode="110001"
    )
    with pytest.raises(HTTPException) as exc:
        _service()._build_consignee_snapshot(_shipment(_address()), request)
    assert exc.value.status_code == 400
