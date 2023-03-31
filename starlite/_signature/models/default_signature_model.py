from __future__ import annotations

from _decimal import Decimal, InvalidOperation
from datetime import date, datetime, time, timedelta
from pathlib import Path, PurePath
from typing import Any, Callable, ClassVar, cast, Mapping, get_args
from uuid import UUID

from dateutil.parser import parse
from pytimeparse.timeparse import timeparse

from starlite import Request, WebSocket
from starlite._signature import SignatureModel
from starlite._signature.field import SignatureField
from starlite._signature.models.base import ErrorMessage
from starlite._signature.parsing import ParsedSignatureParameter
from starlite.connection import ASGIConnection
from starlite.datastructures import ImmutableState, State, UploadFile, MultiDict
from starlite.params import BodyKwarg, DependencyKwarg, ParameterKwarg
from starlite.plugins import PluginMapping

__all__ = ("DefaultSignatureModel",)

from starlite.utils import is_optional_union, is_union, get_origin_or_inner_type, is_dataclass_class, \
    is_pydantic_model_class
from starlite.utils.predicates import is_attrs_class, is_data_container_class, is_typed_dict


class _ExtractionException(Exception):
    def __init__(self, *args: Any, messages: list[ErrorMessage]) -> None:
        super().__init__(*args)
        self.messages = messages


def _create_data_container_extractor(cls: type) -> Callable[[Any], Any]:
    if is_typed_dict(cls):
        return _extract_builtin

    def _extractor(value: Any) -> Any:
        return cls(**value)

    return _extractor


def _extract_builtin(value: Any) -> Any:
    return value


def _extract_string(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _extract_bytes(value: Any) -> bytes:
    if isinstance(value, str):
        return value.encode()
    return bytes(value)


def _extract_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value

    try:
        return Decimal(value)
    except InvalidOperation as e:
        raise ValueError(f"unsupported decimal value {value}") from e


def _extract_path(value: Any) -> PurePath:
    return value if isinstance(value, PurePath) else PurePath(str(value))


def _extract_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _extract_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value

    try:
        return datetime.fromtimestamp(float(value))
    except (ValueError, TypeError):
        pass

    return parse(value)


def _extract_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, (float, int, Decimal)):
        return date.fromtimestamp(float(value))

    dt = _extract_datetime(value=value)
    return date(year=dt.year, month=dt.month, day=dt.day)


def _extract_time(value: Any) -> time:
    if isinstance(value, time):
        return value

    if isinstance(value, str):
        return time.fromisoformat(value)

    dt = _extract_datetime(value=value)
    return time(hour=dt.hour, minute=dt.minute, second=dt.second, microsecond=dt.microsecond, tzinfo=dt.tzinfo)


def _extract_timedelta(value: Any) -> timedelta:
    if isinstance(value, timedelta):
        return value
    if isinstance(value, (float, int, Decimal)):
        return timedelta(seconds=int(value))
    return timedelta(seconds=timeparse(value))


_type_extractor_mapping: dict[type, Callable[[Any], Any]] = {
    str: _extract_string,
    bytes: _extract_bytes,
    int: int,
    float: float,
    Decimal: _extract_decimal,
    PurePath: _extract_path,
    ASGIConnection: _extract_builtin,
    ImmutableState: _extract_builtin,
    MultiDict: _create_data_container_extractor(MultiDict),
    Request: _extract_builtin,
    State: _extract_builtin,
    UUID: _extract_uuid,
    UploadFile: _extract_builtin,
    WebSocket: _extract_builtin,
    date: _extract_date,
    datetime: _extract_datetime,
    time: _extract_time,
    timedelta: _extract_timedelta,
}


def _create_union_extractor(annotations: tuple[type, ...]):
    if type(None) in annotations:
        allow_none = True
    else:
        allow_none = False

    extractors: dict[type, Callable[[Any], Any]] = {}

    for annotation in annotations:
        key = get_origin_or_inner_type(annotation) or annotation

        if key in _type_extractor_mapping:
            extractors[key] = _type_extractor_mapping[key]




    def _extractor(value: Any) -> Any:
        if value is None:
            if allow_none:
                return value
            raise ValueError("unexpected None value")

        try:
            return extractors[type(value)](value)
        except KeyError:
            pass

        for extractor in extractors:
            try:
                return extractor(value)
            except ValueError:
                continue

        raise ValueError(
            f"unexpected value {value}, expected one of {', '.join(k.__name__ for k in extractors.keys())} but received {type(value).__name__}"
        )

    return _extractor

def create_extractors(annotation: Any) -> Callable[[Any], Any]:
    if is_optional_union(annotation) or is_union(annotation):
        extractor = _type_extractor_mapping[annotation] = _create_union_extractor(get_args(annotation))
        return extractor

    annotation = get_origin_or_inner_type(annotation) or annotation

    if annotation in _type_extractor_mapping:
        return _type_extractor_mapping[annotation]

    if is_data_container_class(annotation):
        extractor = _type_extractor_mapping[annotation] = _create_data_container_extractor(annotation)
        return extractor

class DefaultSignatureModel(SignatureModel):
    __slots__ = (
        "dependency_name_set",
        "field_plugin_mappings",
        "return_annotation",
        "fields",
        "_dict",
        "_extractors",
        "_required_fields",
    )

    _required_fields: ClassVar[set[str]]
    _extractors: ClassVar[dict[str, Callable[[Any], Any]]]

    def __init__(self, **kwargs: Any) -> None:
        self._dict: dict[str, Any] = {}
        error_messages: list[ErrorMessage] = []

        for key, extractor in self._extractors.items():
            try:
                self._dict[key] = extractor(kwargs[key])
            except (ValueError, KeyError) as e:
                error_messages.append({"key": key, "message": str(e)})

        if error_messages:
            raise _ExtractionException(messages=error_messages)

    @classmethod
    def parse_values_from_connection_kwargs(cls, connection: ASGIConnection, **kwargs: Any) -> dict[str, Any]:
        if missing_fields := cls._required_fields.difference(set(kwargs)):
            raise super()._create_exception(
                connection=connection,
                messages=[
                    {"key": field_name, "message": "missing required parameter"} for field_name in missing_fields
                ],
            )

        try:
            signature = cls(**kwargs)
        except _ExtractionException as e:
            raise super()._create_exception(connection=connection, messages=e.messages)

        return signature._dict

    def to_dict(self) -> dict[str, Any]:
        return self._dict

    @classmethod
    def create(
        cls,
        fn_name: str,
        fn_module: str | None,
        parsed_params: list[ParsedSignatureParameter],
        return_annotation: Any,
        field_plugin_mappings: dict[str, PluginMapping],
        dependency_names: set[str],
    ) -> type[SignatureModel]:
        model = cast("type[DefaultSignatureModel]", type(f"{fn_name}_signature_model", (cls,), {}))

        model._extractors = {}

        for parameter in parsed_params:





        model._return_annotation = return_annotation
        model._field_plugin_mappings = field_plugin_mappings
        model._dependency_name_set = dependency_names
        model._signature_fields = {
            param.name: SignatureField.create(
                field_type=param.annotation,
                name=param.name,
                default_value=param.default
                if not isinstance(param.default, (ParameterKwarg, BodyKwarg, DependencyKwarg))
                else param.default.default,
                kwarg_model=param.default
                if isinstance(param.default, (ParameterKwarg, BodyKwarg, DependencyKwarg))
                else None,
            )
            for param in parsed_params
        }

        return model
