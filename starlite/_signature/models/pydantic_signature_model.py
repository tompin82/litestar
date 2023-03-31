from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from pydantic import BaseConfig, BaseModel, ValidationError, create_model
from pydantic.fields import FieldInfo, ModelField, Undefined
from pydantic_factories import ModelFactory

from starlite._signature.field import SignatureField
from starlite._signature.models.base import SignatureModel
from starlite.constants import UNDEFINED_SENTINELS
from starlite.params import BodyKwarg, DependencyKwarg, ParameterKwarg
from starlite.types import Empty

if TYPE_CHECKING:
    from starlite._signature.parsing import ParsedSignatureParameter
    from starlite.connection import ASGIConnection
    from starlite.plugins import PluginMapping

__all__ = ("PydanticSignatureModel",)


class PydanticSignatureModel(SignatureModel, BaseModel):
    """Model that represents a function signature that uses a pydantic specific type or types."""

    class Config(BaseConfig):
        copy_on_model_validation = "none"
        arbitrary_types_allowed = True

    @classmethod
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
        try:
            signature = cls(**kwargs)
        except ValidationError as e:
            raise cls._create_exception(
                messages=[{"key": str(exc["loc"][-1]), "message": exc["msg"]} for exc in e.errors()],
                connection=connection,
            ) from e

        return signature.to_dict()

    def _resolve_field_value(self, key: str) -> Any:
        """Return value using key mapping, if available.

        Args:
            key: A field name.

        Returns:
            The plugin value, if available.
        """
        value = self.__getattribute__(key)
        mapping = self.field_plugin_mappings.get(key)
        return mapping.get_model_instance_for_value(value) if mapping else value

    def to_dict(self) -> dict[str, Any]:
        """Normalize access to the signature model's dictionary method, because different backends use different methods
        for this.

        Returns: A dictionary of string keyed values.
        """
        if self.field_plugin_mappings:
            return {key: self._resolve_field_value(key) for key in self.__fields__}
        return {key: self.__getattribute__(key) for key in self.__fields__}

    @classmethod
    def signature_field_from_model_field(cls, model_field: ModelField) -> SignatureField:
        """Create a SignatureField instance from a pydantic ModelField.

        Args:
            model_field: A pydantic ModelField instance.

        Returns:
            A SignatureField
        """
        children = (
            tuple(cls.signature_field_from_model_field(sub_field) for sub_field in model_field.sub_fields)
            if model_field.sub_fields
            else None
        )
        default_value = (
            model_field.field_info.default if model_field.field_info.default not in UNDEFINED_SENTINELS else Empty
        )

        kwarg_model: ParameterKwarg | DependencyKwarg | BodyKwarg | None = model_field.field_info.extra.pop(
            "kwargs_model", None
        )
        if kwarg_model:
            default_value = kwarg_model.default
        elif isinstance(default_value, (ParameterKwarg, DependencyKwarg, BodyKwarg)):
            kwarg_model = default_value
            default_value = default_value.default

        return SignatureField(
            children=children,
            default_value=default_value,
            extra=model_field.field_info.extra or {},
            field_type=model_field.annotation if model_field.annotation is not Empty else Any,
            kwarg_model=kwarg_model,
            name=model_field.name,
        )

    @classmethod
    def populate_signature_fields(cls) -> None:
        """Populate the class signature fields.

        Returns:
            None.
        """
        cls.fields = {k: cls.signature_field_from_model_field(v) for k, v in cls.__fields__.items()}

    @classmethod
    def create(
        cls,
        fn_name: str,
        fn_module: str | None,
        parsed_params: list[ParsedSignatureParameter],
        return_annotation: Any,
        field_plugin_mappings: dict[str, PluginMapping],
        dependency_names: set[str],
    ) -> type[PydanticSignatureModel]:
        """Create a pydantic based SignatureModel.

        Args:
            fn_name: Name of the callable.
            fn_module: Name of the function's module, if any.
            parsed_params: A list of parsed signature parameters.
            return_annotation: Annotation for the callable's return value.
            field_plugin_mappings: A mapping of field names to plugin mappings.
            dependency_names: A set of dependency names.

        Returns:
            The created PydanticSignatureModel.
        """
        field_definitions: dict[str, tuple[Any, Any]] = {}

        for parameter in parsed_params:
            if isinstance(parameter.default, (ParameterKwarg, BodyKwarg)):
                field_info = FieldInfo(
                    **asdict(parameter.default), kwargs_model=parameter.default, parsed_parameter=parameter
                )
            else:
                field_info = FieldInfo(default=..., parsed_parameter=parameter)
            if parameter.should_skip_validation:
                field_type = Any
                if isinstance(parameter.default, DependencyKwarg):
                    field_info.default = parameter.default.default if parameter.default.default is not Empty else None
            elif isinstance(parameter.default, (ParameterKwarg, BodyKwarg)):
                field_type = parameter.annotation
                field_info.default = parameter.default.default if parameter.default.default is not Empty else Undefined
            elif ModelFactory.is_constrained_field(parameter.default):
                field_type = parameter.default
            elif parameter.default_defined:
                field_type = parameter.annotation
                field_info.default = parameter.default
            elif not parameter.optional:
                field_type = parameter.annotation
            else:
                field_type = parameter.annotation
                field_info.default = None

            field_definitions[parameter.name] = (field_type, field_info)

        model: type[PydanticSignatureModel] = create_model(  # type: ignore
            f"{fn_name}_signature_model",
            __base__=PydanticSignatureModel,
            __module__=fn_module or "pydantic.main",
            **field_definitions,
        )
        model.return_annotation = return_annotation
        model.field_plugin_mappings = field_plugin_mappings
        model.dependency_name_set = dependency_names
        model.populate_signature_fields()
        return model
