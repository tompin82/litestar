from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, TypedDict

from starlite.enums import ScopeType
from starlite.exceptions import InternalServerException, ValidationException

if TYPE_CHECKING:
    from starlite._signature.field import SignatureField
    from starlite._signature.parsing import ParsedSignatureParameter
    from starlite.connection import ASGIConnection
    from starlite.plugins import PluginMapping

__all__ = ("SignatureModel",)


class ErrorMessage(TypedDict):
    key: str
    message: str


class SignatureModel(ABC):
    """Base model for Signature modelling."""

    dependency_name_set: ClassVar[set[str]]
    field_plugin_mappings: ClassVar[dict[str, PluginMapping]]
    return_annotation: ClassVar[Any]
    fields: ClassVar[dict[str, SignatureField]]

    @classmethod
    def _create_exception(cls, connection: ASGIConnection, messages: list[ErrorMessage]) -> Exception:
        """Create an exception class - either a ValidationException or an InternalServerException, depending on whether
            the failure is in client provided values or injected dependencies.

        Args:
            connection: An ASGI connection instance.
            messages: A list of error messages.

        Returns:
            An Exception
        """
        method = connection.method if hasattr(connection, "method") else ScopeType.WEBSOCKET  # pyright: ignore
        if client_errors := [
            err_message for err_message in messages if err_message["key"] not in cls.dependency_name_set
        ]:
            return ValidationException(detail=f"Validation failed for {method} {connection.url}", extra=client_errors)
        return InternalServerException(
            detail=f"A dependency failed validation for {method} {connection.url}", extra=messages
        )

    @classmethod
    @abstractmethod
    def parse_values_from_connection_kwargs(cls, connection: ASGIConnection, **kwargs: Any) -> dict[str, Any]:
        """Extract values from the connection instance and return a dict of parsed values.

        Args:
            connection: The ASGI connection instance.
            **kwargs: A dictionary of kwargs.

        Raises:
            ValidationException: If validation failed.
            InternalServerException: If another exception has been raised.

        Returns:
            A dictionary of parsed values
        """
        raise NotImplementedError

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Normalize access to the signature model's dictionary method, because different backends use different methods
        for this.

        Returns: A dictionary of string keyed values.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def populate_signature_fields(cls) -> None:
        """Populate the class signature fields.

        Returns:
            None.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def create(
        cls,
        fn_name: str,
        fn_module: str | None,
        parsed_params: list[ParsedSignatureParameter],
        return_annotation: Any,
        field_plugin_mappings: dict[str, PluginMapping],
        dependency_names: set[str],
    ) -> type[SignatureModel]:
        """Create a SignatureModel.

        Args:
            fn_name: Name of the callable.
            fn_module: Name of the function's module, if any.
            parsed_params: A list of parsed signature parameters.
            return_annotation: Annotation for the callable's return value.
            field_plugin_mappings: A mapping of field names to plugin mappings.
            dependency_names: A set of dependency names.

        Returns:
            The created SignatureModel.
        """
        raise NotImplementedError
