"""
Centralized Role-Based Access Control (RBAC) for the Unified `UserRole` Model:

1. Category A — `TENANT_STAFF` (LogiSmart Internal Carrier / Platform Team):
   - `User.role in STAFF_USER_ROLES` (`owner`, `admin`, `operations_user`, `support_user`, `read_only_user`):
     - `owner` / `admin`: Full tenant administration, settings, rate cards,
       user management, B2B access approvals, wallet recharge approvals,
       COD remittances, GST invoices, and operations.
     - `operations_user`: Carrier Ops & Field Executive (`/ops` Control Tower,
       pickup request dispatch, 6-digit OTP POD, weight audit, raising/resolving NDRs).
     - `support_user`: Carrier Support Desk (view all tenant shipments, reply/resolve
       support tickets, assist with exceptions and weight claims).
     - `read_only_user`: Carrier Analyst (read-only access across tenant; blocked
       from all write operations).

2. Category B — `CUSTOMER` (External B2C / B2B Shippers on the Tenant):
   - `User.role == UserRole.customer`
   - Zero sub-role segregation at the customer level: every customer has full
     self-service access to their own account within the `service_scope`
     (`B2C`, `B2B`, or `BOTH`) enabled by the tenant (`logismart`).
"""
from typing import Optional

from fastapi import HTTPException, status

from app.models.tenants import User, UserRole

STAFF_USER_ROLES = (
    UserRole.owner,
    UserRole.admin,
    UserRole.operations_user,
    UserRole.support_user,
    UserRole.read_only_user,
)
ADMIN_USER_ROLES = (UserRole.owner, UserRole.admin)
TENANT_FINANCE_VIEWER_ROLES = (UserRole.owner, UserRole.admin, UserRole.read_only_user)
"""Roles that can view the tenant-wide wallet ledger (every user's transactions)."""


def can_view_tenant_finance(user: Optional[User]) -> bool:
    """
    True if the user may read the tenant-wide wallet ledger across all users
    (`owner` / `admin` approve payments; `read_only_user` audits).
    """
    return user is not None and user.role in TENANT_FINANCE_VIEWER_ROLES


def is_tenant_staff(user: Optional[User]) -> bool:
    """True if the user is a Tenant Staff member (`owner`, `admin`, `operations_user`, `support_user`, `read_only_user`)."""
    return user is not None and user.role in STAFF_USER_ROLES


def is_tenant_admin(user: Optional[User]) -> bool:
    """
    True if the user is a Tenant Staff `owner` or `admin` (can manage users,
    approve B2B requests, approve wallet recharges, and update tenant settings).
    """
    return user is not None and user.role in ADMIN_USER_ROLES


def assert_not_read_only(
    user: Optional[User], action: str = "perform write operations"
) -> None:
    """
    Raises 403 Forbidden if a Tenant Staff user has the `read_only_user` role.
    Customers (`User.role == customer`) have no sub-role segregation and are
    never read-only on their own resources.
    """
    if user is not None and user.role == UserRole.read_only_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Read-Only staff users cannot {action}.",
        )


def assert_can_manage_shipments_or_pickups(
    user: Optional[User], action: str = "create or cancel shipments and pickup requests"
) -> None:
    """
    Raises 403 Forbidden if a Tenant Staff user is `read_only_user` or `support_user`.
    Customers can always create/cancel their own shipments & pickup requests
    within their enabled `service_scope` (`B2C`, `B2B`, or `BOTH`).
    """
    assert_not_read_only(user, action)
    if user is not None and user.role == UserRole.support_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Support-User staff role cannot {action}. "
                "Support staff can manage Exceptions, Weight Disputes, and Support Tickets."
            ),
        )


def assert_can_manage_finance_or_wallet(
    user: Optional[User], action: str = "initiate wallet recharges or COD settlements"
) -> None:
    """
    Raises 403 Forbidden if a Tenant Staff user is `read_only_user`, `support_user`,
    or `operations_user`. Customers can always recharge their own wallet and settle
    their own COD shipments.
    """
    assert_not_read_only(user, action)
    if (
        user is not None
        and is_tenant_staff(user)
        and user.role not in ADMIN_USER_ROLES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Only Tenant Owner or Admin staff roles can {action}.",
        )


def assert_can_accept_shipment_charges(
    user: Optional[User],
    *,
    is_shipment_owner: bool,
    action: str = "accept wallet charges for this shipment",
) -> None:
    """
    Decision D30: an action that debits a shipper's wallet (acknowledging
    exception charges, accepting a measured weight) may be taken only by the
    shipment's own creator or, on the shipper's behalf, by a Tenant `owner` /
    `admin` (the caller logs who acted). Operations, support and read-only
    staff can never consent to a charge for a shipper.

    Args:
        user: The acting user.
        is_shipment_owner: True when `user` created the shipment (wallet owner).
        action: Human-readable action for the error message.

    Raises:
        HTTPException(403): any other actor.
    """
    assert_not_read_only(user, action)
    if user is not None and (is_shipment_owner or is_tenant_admin(user)):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            f"Only the shipment's owner or a Tenant Owner/Admin can {action}."
        ),
    )
