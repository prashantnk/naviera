# backend/app/services/label.py
import io

from reportlab.graphics.barcode import code128
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from app.models.pickups import PickupRequest
from app.models.tenants import Tenant


class LabelGenerator:
    """
    Generates a standard 4x6 inch logistics shipping label.
    """

    @staticmethod
    def generate_pdf(shipment: PickupRequest, tenant: Tenant) -> io.BytesIO:
        buffer = io.BytesIO()

        # Standard Shipping Label Size: 4 inches wide by 6 inches high
        label_width = 4 * inch
        label_height = 6 * inch

        # Initialize Canvas
        c = canvas.Canvas(buffer, pagesize=(label_width, label_height))

        # --- 1. Header (Brand & Service) ---
        c.setFont("Helvetica-Bold", 16)
        c.drawString(0.2 * inch, 5.6 * inch, tenant.name.upper())

        c.setFont("Helvetica-Bold", 12)
        c.drawRightString(3.8 * inch, 5.6 * inch, shipment.service_type.value)

        c.line(0.1 * inch, 5.4 * inch, 3.9 * inch, 5.4 * inch)

        # --- 2. Origin Address (FROM) ---
        c.setFont("Helvetica-Bold", 10)
        c.drawString(0.2 * inch, 5.1 * inch, "FROM:")

        c.setFont("Helvetica", 9)
        c.drawString(0.2 * inch, 4.9 * inch, shipment.pickup_address.name)
        c.drawString(0.2 * inch, 4.7 * inch, shipment.pickup_address.address_line1)
        c.drawString(
            0.2 * inch,
            4.5 * inch,
            f"{shipment.pickup_address.city}, {shipment.pickup_address.state} {shipment.pickup_address.pincode}",
        )
        c.drawString(0.2 * inch, 4.3 * inch, f"Ph: {shipment.pickup_address.phone}")

        c.line(0.1 * inch, 4.1 * inch, 3.9 * inch, 4.1 * inch)

        # --- 3. Destination Address (TO) ---
        c.setFont("Helvetica-Bold", 14)
        c.drawString(0.2 * inch, 3.7 * inch, "TO:")

        c.setFont("Helvetica-Bold", 12)
        c.drawString(0.2 * inch, 3.4 * inch, shipment.delivery_address.name)

        c.setFont("Helvetica", 11)
        c.drawString(0.2 * inch, 3.2 * inch, shipment.delivery_address.address_line1)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(
            0.2 * inch,
            3.0 * inch,
            f"{shipment.delivery_address.city}, {shipment.delivery_address.state} {shipment.delivery_address.pincode}",
        )
        c.setFont("Helvetica", 10)
        c.drawString(0.2 * inch, 2.7 * inch, f"Ph: {shipment.delivery_address.phone}")

        c.line(0.1 * inch, 2.5 * inch, 3.9 * inch, 2.5 * inch)

        # --- 4. Package Info ---
        total_weight = sum(p.weight for p in shipment.packages)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(0.2 * inch, 2.2 * inch, f"WEIGHT: {total_weight} KG")
        c.drawString(2.5 * inch, 2.2 * inch, f"BOXES: {len(shipment.packages)}")
        c.drawString(0.2 * inch, 2.0 * inch, f"REF: {shipment.order_reference_id}")

        c.line(0.1 * inch, 1.8 * inch, 3.9 * inch, 1.8 * inch)

        # --- 5. Barcode (Tracking ID) ---
        # Generate a Code 128 barcode (standard for logistics)
        tracking_str = shipment.tracking_id or "PENDING"
        barcode = code128.Code128(tracking_str, barHeight=0.6 * inch, barWidth=1.5)

        # Center the barcode horizontally
        bc_width = barcode.width
        x_pos = (label_width - bc_width) / 2
        barcode.drawOn(c, x_pos, 0.9 * inch)

        # Print the Tracking ID text below the barcode
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(label_width / 2.0, 0.6 * inch, tracking_str)

        # Finalize and save to buffer
        c.showPage()
        c.save()

        buffer.seek(0)
        return buffer
