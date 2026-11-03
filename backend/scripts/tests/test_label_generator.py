# backend/scripts/tests/test_label_generator.py
import io
from datetime import date, datetime
from decimal import Decimal
from typing import List

import pytest
from pypdf import PdfReader
from reportlab.graphics.barcode import code128
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from app.models.pickups import (
    Address,
    DimensionUnit,
    FreightPaymentMode,
    PackageDetails,
    PaymentDetails,
    PickupRequest,
    PickupStatus,
    PickupStrategy,
    ProductCategory,
    ServiceOption,
    ServiceType,
    WeightUnit,
)
from app.models.tenants import Tenant
from app.services import label
from app.services.label import LabelGenerator


def get_base_mock_shipment() -> PickupRequest:
    pickup_addr = Address(
        id="d7f31d2d-29cd-49e4-8350-c87bb3676048",
        name="Warehouse A",
        phone="9999999999",
        address_line1="123 Industrial Area",
        city="Delhi",
        state="DL",
        pincode="110001",
        company_name="Logistics Origin Corp",
        gstin="07AAAAA1111A1Z1"
    )
    delivery_addr = Address(
        id="d7f31d2d-29cd-49e4-8350-c87bb3676049",
        name="Retail Store B",
        phone="8888888888",
        address_line1="456 Market Road",
        city="Mumbai",
        state="MH",
        pincode="400001",
        company_name="Retail Destination Ltd",
        gstin="27BBBBB2222B2Z2"
    )
    
    shipment = PickupRequest(
        id="d7f31d2d-29cd-49e4-8350-c87bb3676050",
        tenant_id="d7f31d2d-29cd-49e4-8350-c87bb3676051",
        created_by_user_id="d7f31d2d-29cd-49e4-8350-c87bb3676052",
        tracking_id="NAV-B2BTEST123",
        order_reference_id="REF-12345",
        shipment_type="FORWARD",
        service_type=ServiceType.SURFACE_ROAD,
        requested_pickup_date=str(date.today()),
        pickup_time_slot="06:00 - 10:00",
        product_category=ProductCategory.ELECTRONICS,
        status=PickupStatus.OPEN,
        created_at=datetime.now(),
        pickup_address=pickup_addr,
        delivery_address=delivery_addr,
        packages=[],
        documents=[]
    )
    return shipment


def test_is_b2b_detection():
    tenant = Tenant(
        id="d7f31d2d-29cd-49e4-8350-c87bb3676051",
        name="Test Tenant",
        slug="test-tenant",
        settings={}
    )
    
    # Base shipment is B2C by default (no PO, no invoices, no B2B flags)
    shipment = get_base_mock_shipment()
    assert LabelGenerator._is_b2b(shipment, tenant) is False
    
    # 1. PO Number makes it B2B
    shipment.po_number = "PO-999"
    assert LabelGenerator._is_b2b(shipment, tenant) is True
    shipment.po_number = None
    
    # 2. Invoice numbers alone do NOT make it B2B (B2C parcels carry GST invoices too);
    #    labels follow the shared `is_b2b_shipment` classifier.
    shipment.payment_details = PaymentDetails(
        freight_payment_mode=FreightPaymentMode.PREPAID,
        invoice_numbers=["INV-001", "INV-002"]
    )
    assert LabelGenerator._is_b2b(shipment, tenant) is False
    shipment.payment_details = None

    # 2b. A pickup strategy (set by every B2B booking wizard) makes it B2B
    shipment.pickup_strategy = PickupStrategy.DEFAULT
    assert LabelGenerator._is_b2b(shipment, tenant) is True
    shipment.pickup_strategy = None

    # 2c. COMMERCIAL product category makes it B2B
    shipment.product_category = ProductCategory.COMMERCIAL
    assert LabelGenerator._is_b2b(shipment, tenant) is True
    shipment.product_category = ProductCategory.ELECTRONICS
    
    # 3. Blind pickup flag makes it B2B
    shipment.is_blind_pickup = True
    assert LabelGenerator._is_b2b(shipment, tenant) is True
    shipment.is_blind_pickup = False
    
    # 4. Carrier's risk flag makes it B2B
    shipment.is_carriers_risk = True
    assert LabelGenerator._is_b2b(shipment, tenant) is True
    shipment.is_carriers_risk = False
    
    # 5. Tenant settings config makes it B2B
    tenant.settings = {"is_b2b": True}
    assert LabelGenerator._is_b2b(shipment, tenant) is True
    
    tenant.settings = {"mode": "b2b"}
    assert LabelGenerator._is_b2b(shipment, tenant) is True
    
    tenant.settings = {"mode": "b2c"}
    assert LabelGenerator._is_b2b(shipment, tenant) is False


def test_generate_b2c_pdf():
    tenant = Tenant(
        id="d7f31d2d-29cd-49e4-8350-c87bb3676051",
        name="Express Logistics",
        slug="express",
        settings={}
    )
    
    shipment = get_base_mock_shipment()
    shipment.packages = [
        PackageDetails(
            length=10.0,
            breadth=10.0,
            height=10.0,
            weight=1.5,
            box_count=1,
            dimension_unit=DimensionUnit.CM,
            weight_unit=WeightUnit.KG,
            description="Box 1"
        )
    ]
    
    # Generate B2C PDF label
    pdf_buffer = LabelGenerator.generate_pdf(shipment, tenant)
    assert isinstance(pdf_buffer, io.BytesIO)
    pdf_bytes = pdf_buffer.getvalue()
    assert len(pdf_bytes) > 0
    # PDF files start with %PDF header bytes
    assert pdf_bytes.startswith(b"%PDF")


def test_generate_b2b_pdf():
    tenant = Tenant(
        id="d7f31d2d-29cd-49e4-8350-c87bb3676051",
        name="Naviera Heavy Freight",
        slug="naviera",
        settings={"is_b2b": True}
    )
    
    shipment = get_base_mock_shipment()
    shipment.po_number = "PO-B2B-12345"
    shipment.po_date = date.today()
    shipment.appointment_id = "APT-998877"
    
    shipment.packages = [
        PackageDetails(
            length=40.0,
            breadth=30.0,
            height=20.0,
            weight=12.5,
            box_count=2,
            dimension_unit=DimensionUnit.CM,
            weight_unit=WeightUnit.KG,
            description="Industrial Components"
        )
    ]
    
    shipment.payment_details = PaymentDetails(
        freight_payment_mode=FreightPaymentMode.TO_PAY,
        is_cod=False,
        cod_amount=0.0,
        shipment_total_value=50000.0,
        hsn_code="8471",
        invoice_numbers=["INV-2026-001"],
        invoice_date=date.today(),
        base_freight=1200.0,
        tax_amount=216.0,
        total_logistics_cost=1416.0,
        chargeable_weight=25.0,
        pricing_breakdown={
            "total_actual_weight": 25.0,
            "total_volumetric_weight": 16.00,
            "docket_charge": 50.0,
            "fov_charge": 100.0,
            "fuel_surcharge": 50.0
        }
    )
    
    # Generate B2B PDF label
    pdf_buffer = LabelGenerator.generate_pdf(shipment, tenant)
    assert isinstance(pdf_buffer, io.BytesIO)
    pdf_bytes = pdf_buffer.getvalue()
    assert len(pdf_bytes) > 0
    assert pdf_bytes.startswith(b"%PDF")


# --- E-05 / E-06: barcode fit, payment block, boxes, weight, address wrap ---

MAX_LENGTH_CHILD_AWB = "LOGISMART-TEST-X9A2B3C4-B999"
LONG_STREET = (
    "Plot 14, Shri Ganesh Industrial Estate, Behind Old Octroi Naka, Near Railway Crossing "
    "Number 7, Opposite Shree Balaji Weighbridge, Bhiwandi Kalyan Road, Village Pimplas "
)


def _tenant() -> Tenant:
    return Tenant(
        id="d7f31d2d-29cd-49e4-8350-c87bb3676051",
        name="Logismart",
        slug="logismart",
        settings={},
    )


def _package(weight: float, box_count: int, unit: WeightUnit = WeightUnit.KG) -> PackageDetails:
    return PackageDetails(
        length=10.0,
        breadth=10.0,
        height=10.0,
        weight=weight,
        box_count=box_count,
        dimension_unit=DimensionUnit.CM,
        weight_unit=unit,
    )


def _cod_payment(cod_amount: float) -> PaymentDetails:
    return PaymentDetails(
        freight_payment_mode=FreightPaymentMode.PREPAID, is_cod=True, cod_amount=cod_amount
    )


def _b2c_cod_shipment() -> PickupRequest:
    """A B2C COD shipment: 3 boxes, line 2 + landmark on the consignee, no order reference."""
    shipment = get_base_mock_shipment()
    shipment.tracking_id = "LOGISMART-X9A2B3C4"
    shipment.order_reference_id = None
    shipment.delivery_address.address_line2 = "Flat 4B, Sai Krupa Apartments"
    shipment.delivery_address.landmark = "near Hanuman Mandir"
    shipment.packages = [_package(1.5, 2), _package(500.0, 1, WeightUnit.G)]
    shipment.payment_details = _cod_payment(123456.5)
    return shipment


def _pdf_pages_text(pdf: io.BytesIO) -> List[str]:
    return [page.extract_text() for page in PdfReader(pdf).pages]


def test_fitted_barcode_fits_label_for_max_length_awb():
    for awb in (MAX_LENGTH_CHILD_AWB, "LOGISMART-X9A2B3C4", "A" * 40):
        barcode = label.fitted_code128(awb, label.LABEL_BARCODE_USABLE_WIDTH, 40)
        assert barcode.width <= label.LABEL_BARCODE_USABLE_WIDTH + 1e-6
        assert barcode.lquiet == pytest.approx(barcode.barWidth * label.BARCODE_QUIET_ZONE_MODULES)


def test_fitted_barcode_caps_short_values_at_max_bar_width():
    barcode = label.fitted_code128("AB1", label.LABEL_BARCODE_USABLE_WIDTH, 40)
    assert barcode.barWidth == label.BARCODE_MAX_BAR_WIDTH


def test_old_fixed_bar_width_would_have_clipped():
    """Regression guard for E-05: the old barWidth=1.5 barcode was wider than the label."""
    assert code128.Code128("LOGISMART-X9A2B3C4", barWidth=1.5).width > label.LABEL_WIDTH


@pytest.mark.parametrize(
    "amount, expected",
    [
        ("0", "0.00"),
        ("999.5", "999.50"),
        ("1000", "1,000.00"),
        ("100000", "1,00,000.00"),
        ("123456.5", "1,23,456.50"),
        ("12345678.9", "1,23,45,678.90"),
    ],
)
def test_format_inr_uses_indian_grouping(amount, expected):
    assert label.format_inr(Decimal(amount)) == expected


def test_payment_block_cod_uses_door_collectible(monkeypatch):
    assert (
        label.payment_block_text(_cod_payment(123456.5), "\u20b9")
        == "COD \u2013 Collect \u20b91,23,456.50"
    )
    # The amount comes only from cod_payout.door_collectible, never from cod_amount directly.
    monkeypatch.setattr(label, "door_collectible", lambda payment: Decimal("42.00"))
    assert label.payment_block_text(_cod_payment(123456.5), "Rs. ") == "COD \u2013 Collect Rs. 42.00"


def test_payment_block_prepaid_when_nothing_to_collect():
    assert label.payment_block_text(None, "\u20b9") == label.PREPAID_LABEL
    prepaid = PaymentDetails(freight_payment_mode=FreightPaymentMode.PREPAID, is_cod=False, cod_amount=500.0)
    assert label.payment_block_text(prepaid, "\u20b9") == label.PREPAID_LABEL
    assert label.payment_block_text(_cod_payment(0.0), "\u20b9") == label.PREPAID_LABEL


def test_payment_font_and_currency_pairs_symbol_with_font():
    font, currency = label.payment_font_and_currency()
    if font == label.BOLD_FONT:
        assert currency == label.RUPEE_FALLBACK_PREFIX
    else:
        assert (font, currency) == (label.RUPEE_FONT_NAME, label.RUPEE_SYMBOL)


def test_total_boxes_counts_every_carton():
    shipment = _b2c_cod_shipment()
    assert label.total_boxes(shipment) == 3
    shipment.packages = []
    assert label.total_boxes(shipment) == 1
    shipment.is_blind_pickup = True
    shipment.estimated_box_count = 5
    assert label.total_boxes(shipment) == 5


def test_label_weight_prefers_chargeable_else_sums_boxes():
    shipment = _b2c_cod_shipment()
    # 1.5 kg x 2 boxes + 500 g x 1 box
    assert label.label_weight_kg(shipment) == pytest.approx(3.5)
    shipment.payment_details.chargeable_weight = 4.0
    assert label.label_weight_kg(shipment) == pytest.approx(4.0)


def test_info_lines_omit_empty_reference():
    shipment = _b2c_cod_shipment()
    assert not any(line.startswith("REF") for line in label.b2c_info_lines(shipment))
    shipment.order_reference_id = "   "
    assert not any(line.startswith("REF") for line in label.b2c_info_lines(shipment))
    shipment.order_reference_id = "ORD-77"
    assert label.b2c_info_lines(shipment)[-1] == "REF: ORD-77"


def test_address_rows_include_line2_and_landmark():
    shipment = _b2c_cod_shipment()
    rows = [row[0] for row in label.address_rows(shipment.delivery_address, label.TO_ADDRESS_STYLE)]
    assert rows[1] == "456 Market Road, Flat 4B, Sai Krupa Apartments"
    assert rows[2] == "Landmark: near Hanuman Mandir"
    shipment.delivery_address.address_line2 = " "
    shipment.delivery_address.landmark = None
    rows = [row[0] for row in label.address_rows(shipment.delivery_address, label.TO_ADDRESS_STYLE)]
    assert rows[1] == "456 Market Road"
    assert not any(row.startswith("Landmark") for row in rows)


def test_wrap_text_keeps_lines_inside_width_and_budget():
    lines = label.wrap_text(LONG_STREET * 3, label.BASE_FONT, 10, label.LABEL_TEXT_WIDTH, 3)
    assert len(lines) == 3
    assert lines[-1].endswith(label.ELLIPSIS)
    for line in lines:
        assert pdfmetrics.stringWidth(line, label.BASE_FONT, 10) <= label.LABEL_TEXT_WIDTH
    single_word = label.wrap_text("X" * 200, label.BOLD_FONT, 12, label.LABEL_TEXT_WIDTH, 1)
    assert pdfmetrics.stringWidth(single_word[0], label.BOLD_FONT, 12) <= label.LABEL_TEXT_WIDTH


def test_b2c_addresses_never_reach_payment_block_for_worst_case_input():
    shipment = _b2c_cod_shipment()
    for addr in (shipment.pickup_address, shipment.delivery_address):
        addr.name = "Very Long Consignee Name Private Limited Unit Two " * 2
        addr.address_line1 = LONG_STREET
        addr.address_line2 = LONG_STREET
        addr.landmark = "Opposite the big banyan tree beside the old temple " * 2
        addr.city = "Thiruvananthapuram Municipal Corporation Area"
        addr.state = "Kerala"
        addr.alternate_phone = "7777777777"
    c = canvas.Canvas(io.BytesIO(), pagesize=(label.LABEL_WIDTH, label.LABEL_4X6_HEIGHT))
    bottom = LabelGenerator._draw_b2c_addresses(c, shipment)
    assert bottom >= label.B2C_ADDRESS_FLOOR_Y


def test_b2c_pdf_prints_payment_boxes_address_and_no_none_ref():
    text = _pdf_pages_text(LabelGenerator.generate_pdf(_b2c_cod_shipment(), _tenant()))[0]
    assert "COD" in text and "1,23,456.50" in text
    assert "BOXES: 3" in text
    assert "WEIGHT: 3.50 KG" in text
    assert "Flat 4B" in text and "Hanuman Mandir" in text
    assert "REF" not in text and "None" not in text
    assert label.TERMS_URL_PATH in text
    assert "LOGISMART-X9A2B3C4" in text


def test_b2c_pdf_prepaid_label():
    shipment = _b2c_cod_shipment()
    shipment.payment_details = None
    text = _pdf_pages_text(LabelGenerator.generate_pdf(shipment, _tenant()))[0]
    assert label.PREPAID_LABEL in text
    assert "COD" not in text


def test_b2b_box_labels_one_per_box_with_long_awb():
    shipment = get_base_mock_shipment()
    shipment.po_number = "PO-1"
    shipment.tracking_id = "LOGISMART-TEST-X9A2B3C4"
    shipment.packages = [_package(12.5, 2), _package(3.0, 1)]
    pages = _pdf_pages_text(LabelGenerator.generate_pdf(shipment, _tenant()))
    assert len(pages) == len(label.LR_COPY_LABELS) + 3
    assert "LOGISMART-TEST-X9A2B3C4-B3" in pages[-1]


def test_blind_b2b_without_estimate_still_prints_one_box_label():
    shipment = get_base_mock_shipment()
    shipment.is_blind_pickup = True
    shipment.estimated_box_count = None
    pages = _pdf_pages_text(LabelGenerator.generate_pdf(shipment, _tenant()))
    assert len(pages) == len(label.LR_COPY_LABELS) + 1


def test_thermal_4x2_prints_one_label_per_box():
    pages = _pdf_pages_text(
        LabelGenerator.generate_pdf(_b2c_cod_shipment(), _tenant(), label.THERMAL_4X2_FORMAT)
    )
    assert len(pages) == 3
    assert "LOGISMART-X9A2B3C4-B3" in pages[-1]


def test_info_lines_add_the_carrier_awb_once_ops_entered_it():
    """coordinator #519 (4): ops match the parcel to the carrier's own label by its AWB."""
    shipment = _b2c_cod_shipment()
    assert not any("AWB:" in line for line in label.b2c_info_lines(shipment))
    shipment.carrier_awb = "  "
    assert not any("AWB:" in line for line in label.b2c_info_lines(shipment))
    shipment.carrier_awb = "1234567890123"
    shipment.service_option = ServiceOption.DELHIVERY_SURFACE
    assert label.b2c_info_lines(shipment)[-1] == "DELHIVERY AWB: 1234567890123"
    shipment.service_option = ServiceOption.PRIME_SURFACE
    shipment.carrier_awb = "LR-778899"
    assert label.b2c_info_lines(shipment)[-1] == "LOGISMART PRIME AWB: LR-778899"


def test_b2c_label_pdf_prints_the_carrier_awb():
    shipment = _b2c_cod_shipment()
    shipment.carrier_awb = "1234567890123"
    shipment.service_option = ServiceOption.DELHIVERY_SURFACE
    shipment.order_reference_id = "ORD-77"
    text = "".join(_pdf_pages_text(LabelGenerator.generate_pdf(shipment, _tenant())))
    assert "DELHIVERY AWB: 1234567890123" in text


# --- journey:b2b — B2B LR docket: 3 copies, quote rows, compliance row ---


def _b2b_lr_shipment() -> PickupRequest:
    """A Prime B2B LR booked through the redesigned pricing (sell_lines present)."""
    shipment = get_base_mock_shipment()
    shipment.tracking_id = "LOGISMART-TEST-GVFEGEFW"
    shipment.po_number = "PO-J3-1,PO-J3-2"
    shipment.packages = [_package(18.0, 3)]
    shipment.payment_details = PaymentDetails(
        freight_payment_mode=FreightPaymentMode.PREPAID,
        is_cod=False,
        cod_amount=0.0,
        shipment_total_value=70800.0,
        invoice_numbers=["INV-J3-001", "INV-J3-002"],
        eway_bill_numbers=["331234567890"],
        base_freight=1608.0,
        tax_amount=289.44,
        total_logistics_cost=1897.44,
        chargeable_weight=64.0,
        pricing_breakdown={
            "docket_charge": 0.0,
            "sell_lines": [
                {"code": "FREIGHT", "label": "Freight (Logismart Prime)", "amount": 768.0},
                {"code": "DOCKET", "label": "Docket charge", "amount": 120.0},
                {"code": "PICKUP", "label": "Pickup charge", "amount": 720.0},
                {"code": "GST", "label": "GST (18%)", "amount": 289.44},
            ],
        },
    )
    return shipment


def test_b2b_lr_prints_three_marked_copies_then_box_labels():
    pages = _pdf_pages_text(LabelGenerator.generate_pdf(_b2b_lr_shipment(), _tenant()))
    assert len(pages) == 3 + 3
    for page, copy_label in zip(pages, label.LR_COPY_LABELS):
        assert copy_label in page
        assert "LORRY RECEIPT / FREIGHT DOCKET" in page
    assert "BOX LABEL" in pages[3] and "LOGISMART-TEST-GVFEGEFW-B3" in pages[-1]


def test_b2b_lr_ledger_uses_quote_rows_not_legacy_zero_docket():
    rows = label.docket_charge_lines(_b2b_lr_shipment().payment_details)
    assert rows == [
        ("Freight (Logismart Prime)", 768.0),
        ("Docket charge", 120.0),
        ("Pickup charge", 720.0),
    ]
    page = _pdf_pages_text(LabelGenerator.generate_pdf(_b2b_lr_shipment(), _tenant()))[0]
    assert "Pickup charge:" in page and "720.00" in page
    assert "Docket Fee:" not in page


def test_b2b_lr_ledger_legacy_rows_and_overflow_folding():
    payment = PaymentDetails(
        freight_payment_mode=FreightPaymentMode.PREPAID,
        base_freight=500.0,
        pricing_breakdown={"docket_charge": 50.0, "fuel_surcharge": 10.0, "cod_fee": 30.0},
    )
    assert label.docket_charge_lines(payment) == [
        ("Base Freight", 500.0),
        ("Docket Fee", 50.0),
        ("FOV Surcharge (Carrier's Risk)", 0.0),
        ("Fuel Surcharge", 10.0),
        ("COD Collection Fee", 30.0),
    ]
    many = [{"code": f"L{i}", "label": f"Line {i}", "amount": 10.0} for i in range(8)]
    payment.pricing_breakdown = {"sell_lines": many}
    rows = label.docket_charge_lines(payment)
    assert len(rows) == label.DOCKET_MAX_CHARGE_LINES
    assert rows[-1] == (label.OTHER_CHARGES_LABEL, 30.0)
    assert label.docket_charge_lines(None) == []


def test_b2b_lr_compliance_row_lists_invoices_eway_bills_and_value():
    shipment = _b2b_lr_shipment()
    text = label.docket_compliance_text(shipment)
    assert "INVOICE NO: INV-J3-001, INV-J3-002" in text
    assert "E-WAY BILL NO: 331234567890" in text
    assert "GOODS VALUE: Rs. 70,800.00" in text
    assert "AWB:" not in text
    shipment.carrier_awb = "LR-778899"
    shipment.service_option = ServiceOption.PRIME_SURFACE
    assert label.docket_compliance_text(shipment).endswith("LOGISMART PRIME AWB: LR-778899")
    shipment.payment_details = None
    assert "INVOICE NO: N/A" in label.docket_compliance_text(shipment)
    page = _pdf_pages_text(LabelGenerator.generate_pdf(_b2b_lr_shipment(), _tenant()))[0]
    assert "INV-J3-001" in page and "331234567890" in page
