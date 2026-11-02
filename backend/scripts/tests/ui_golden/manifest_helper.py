import uuid
from typing import List
from sqlmodel.ext.asyncio.session import AsyncSession
from app.models.pickups import PickupRequest
from app.schemas.v1.manifests import ManifestCreate
from app.services.manifests import ManifestService
from sqlmodel import select
from datetime import date

async def auto_manifest_shipments(session: AsyncSession, tenant_id: uuid.UUID, shipment_ids: List[uuid.UUID]) -> str:
    service = ManifestService(session)
    
    shipment = (await session.exec(select(PickupRequest).where(PickupRequest.id == shipment_ids[0]))).first()
    
    payload = ManifestCreate(
        pickup_address_id=shipment.pickup_address_id,
        scheduled_date=date.today(),
        time_slot="10:00 - 14:00",
        is_blind_pickup=False,
        total_boxes=len(shipment_ids),
        shipment_ids=shipment_ids
    )
    
    manifest_dict = await service.create_manifest(payload, tenant_id, None)
    await session.commit()
    return manifest_dict["pickup_request_number"]
