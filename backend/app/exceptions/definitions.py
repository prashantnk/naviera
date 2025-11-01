"""
This file contains custom, application-specific exceptions.
These exceptions are raised by the Service Layer and handled
by a global exception handler in the API Layer (main.py).
"""


class NavieraException(Exception):
    """
    Base exception for the Naviera application.
    All custom business exceptions should inherit from this.
    """

    pass


class TenantNotFoundException(NavieraException):
    """
    Raised when a specific tenant cannot be found in the database.
    """

    pass


class UserNotFoundException(NavieraException):
    """
    Raised when a specific user cannot be found in the database.
    """

    pass
