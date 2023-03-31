from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Callable, Coroutine, DefaultDict, Dict, cast

from starlite._multipart import parse_multipart_form
from starlite._parsers import (
    parse_headers,
    parse_query_string,
    parse_url_encoded_form_data,
)
from starlite.datastructures.upload_file import UploadFile
from starlite.enums import ParamType, RequestEncodingType
from starlite.exceptions import ValidationException
from starlite.params import BodyKwarg
from starlite.types import Empty

__all__ = (
    "body_extractor",
    "cookies_extractor",
    "create_connection_value_extractor",
    "create_data_extractor",
    "create_multipart_extractor",
    "create_query_default_dict",
    "create_url_encoded_data_extractor",
    "headers_extractor",
    "json_extractor",
    "msgpack_extractor",
    "parse_connection_headers",
    "parse_connection_query_params",
    "query_extractor",
    "request_extractor",
    "scope_extractor",
    "socket_extractor",
    "state_extractor",
)


if TYPE_CHECKING:
    from starlite._kwargs import KwargsModel
    from starlite._kwargs.parameter_definition import ParameterDefinition
    from starlite._signature.field import SignatureField
    from starlite.connection import ASGIConnection, Request


def create_connection_value_extractor(
    kwargs_model: KwargsModel,
    connection_key: str,
    expected_params: set[ParameterDefinition],
    parser: Callable[[ASGIConnection, KwargsModel], dict[str, Any]] | None = None,
) -> Callable[[dict[str, Any], ASGIConnection], None]:
    """Create a kwargs extractor function.

    Args:
        kwargs_model: The KwargsModel instance.
        connection_key: The attribute key to use.
        expected_params: The set of expected params.
        parser: An optional parser function.

    Returns:
        An extractor function.
    """

    alias_and_key_tuple = tuple(
        (p.field_alias.lower() if p.param_type == ParamType.HEADER else p.field_alias, p.field_name)
        for p in expected_params
    )
    alias_defaults = {
        p.field_alias.lower() if p.param_type == ParamType.HEADER else p.field_alias: p.default_value
        for p in expected_params
        if not (p.is_required or p.default_value is Ellipsis)
    }

    def extractor(values: dict[str, Any], connection: ASGIConnection) -> None:
        data = parser(connection, kwargs_model) if parser else getattr(connection, connection_key, {})

        try:
            connection_mapping: dict[str, Any] = {
                key: data[alias] if alias in data else alias_defaults[alias] for alias, key in alias_and_key_tuple
            }
            values.update(connection_mapping)
        except KeyError as e:
            raise ValidationException(f"Missing required parameter {e.args[0]} for url {connection.url}") from e

    return extractor


@lru_cache(1024)
def create_query_default_dict(
    parsed_query: tuple[tuple[str, str], ...], sequence_query_parameter_names: tuple[str, ...]
) -> DefaultDict[str, list[str] | str]:
    """Transform a list of tuples into a default dict. Ensures non-list values are not wrapped in a list.

    Args:
        parsed_query: The parsed query list of tuples.
        sequence_query_parameter_names: A set of query parameters that should be wrapped in list.

    Returns:
        A default dict
    """
    output: DefaultDict[str, list[str] | str] = defaultdict(list)

    for k, v in parsed_query:
        if k in sequence_query_parameter_names:
            output[k].append(v)  # type: ignore
        else:
            output[k] = v

    return output


def parse_connection_query_params(connection: ASGIConnection, kwargs_model: KwargsModel) -> dict[str, Any]:
    """Parse query params and cache the result in scope.

    Args:
        connection: The ASGI connection instance.
        kwargs_model: The KwargsModel instance.

    Returns:
        A dictionary of parsed values.
    """
    parsed_query = connection.scope["_parsed_query"] = (  # type: ignore
        connection._parsed_query
        if connection._parsed_query is not Empty
        else parse_query_string(connection.scope.get("query_string", b""))
    )
    return create_query_default_dict(
        parsed_query=parsed_query, sequence_query_parameter_names=kwargs_model.sequence_query_parameter_names
    )


def parse_connection_headers(connection: ASGIConnection, _: KwargsModel) -> dict[str, Any]:
    """Parse header parameters and cache the result in scope.

    Args:
        connection: The ASGI connection instance.
        _: The KwargsModel instance.

    Returns:
        A dictionary of parsed values
    """
    parsed_headers = connection.scope["_headers"] = (  # type: ignore
        connection._headers if connection._headers is not Empty else parse_headers(tuple(connection.scope["headers"]))
    )
    return cast("Dict[str, Any]", parsed_headers)


def state_extractor(values: dict[str, Any], connection: ASGIConnection) -> None:
    """Extract the app state from the connection and insert it to the kwargs injected to the handler.

    Args:
        connection: The ASGI connection instance.
        values: The kwargs that are extracted from the connection and will be injected into the handler.

    Returns:
        None
    """
    values["state"] = connection.app.state._state


def headers_extractor(values: dict[str, Any], connection: ASGIConnection) -> None:
    """Extract the headers from the connection and insert them to the kwargs injected to the handler.

    Args:
        connection: The ASGI connection instance.
        values: The kwargs that are extracted from the connection and will be injected into the handler.

    Returns:
        None
    """
    values["headers"] = connection.headers


def cookies_extractor(values: dict[str, Any], connection: ASGIConnection) -> None:
    """Extract the cookies from the connection and insert them to the kwargs injected to the handler.

    Args:
        connection: The ASGI connection instance.
        values: The kwargs that are extracted from the connection and will be injected into the handler.

    Returns:
        None
    """
    values["cookies"] = connection.cookies


def query_extractor(values: dict[str, Any], connection: ASGIConnection) -> None:
    """Extract the query params from the connection and insert them to the kwargs injected to the handler.

    Args:
        connection: The ASGI connection instance.
        values: The kwargs that are extracted from the connection and will be injected into the handler.

    Returns:
        None
    """
    values["query"] = connection.query_params


def scope_extractor(values: dict[str, Any], connection: ASGIConnection) -> None:
    """Extract the scope from the connection and insert it into the kwargs injected to the handler.

    Args:
        connection: The ASGI connection instance.
        values: The kwargs that are extracted from the connection and will be injected into the handler.

    Returns:
        None
    """
    values["scope"] = connection.scope


def request_extractor(values: dict[str, Any], connection: ASGIConnection) -> None:
    """Set the connection instance as the 'request' value in the kwargs injected to the handler.

    Args:
        connection: The ASGI connection instance.
        values: The kwargs that are extracted from the connection and will be injected into the handler.

    Returns:
        None
    """
    values["request"] = connection


def socket_extractor(values: dict[str, Any], connection: ASGIConnection) -> None:
    """Set the connection instance as the 'socket' value in the kwargs injected to the handler.

    Args:
        connection: The ASGI connection instance.
        values: The kwargs that are extracted from the connection and will be injected into the handler.

    Returns:
        None
    """
    values["socket"] = connection


def body_extractor(
    values: dict[str, Any],
    connection: Request[Any, Any, Any],
) -> None:
    """Extract the body from the request instance.

    Notes:
        - this extractor sets a Coroutine as the value in the kwargs. These are resolved at a later stage.

    Args:
        connection: The ASGI connection instance.
        values: The kwargs that are extracted from the connection and will be injected into the handler.

    Returns:
        The Body value.
    """
    values["body"] = connection.body()


async def json_extractor(
    connection: "Request[Any, Any, Any]",
) -> Any:
    """Extract the data from request and insert it into the kwargs injected to the handler.

    Notes:
        - this extractor sets a Coroutine as the value in the kwargs. These are resolved at a later stage.

    Args:
        connection: The ASGI connection instance.

    Returns:
        The JSON value.
    """
    return await connection.json()


async def msgpack_extractor(connection: "Request[Any, Any, Any]") -> Any:
    """Extract the data from request and insert it into the kwargs injected to the handler.

    Notes:
        - this extractor sets a Coroutine as the value in the kwargs. These are resolved at a later stage.

    Args:
        connection: The ASGI connection instance.

    Returns:
        The MessagePack value.
    """
    return await connection.msgpack()


def create_multipart_extractor(
    signature_field: SignatureField, is_data_optional: bool
) -> Callable[[ASGIConnection[Any, Any, Any, Any]], Coroutine[Any, Any, Any]]:
    """Create a multipart form-data extractor.

    Args:
        signature_field: A SignatureField instance.
        is_data_optional: Boolean dictating whether the field is optional.

    Returns:
        An extractor function.
    """
    body_kwarg_multipart_form_part_limit: int | None = None
    if signature_field.kwarg_model and isinstance(signature_field.kwarg_model, BodyKwarg):
        body_kwarg_multipart_form_part_limit = signature_field.kwarg_model.multipart_form_part_limit

    async def extract_multipart(
        connection: "Request[Any, Any, Any]",
    ) -> Any:
        multipart_form_part_limit = (
            body_kwarg_multipart_form_part_limit
            if body_kwarg_multipart_form_part_limit is not None
            else connection.app.multipart_form_part_limit
        )
        connection.scope["_form"] = form_values = (  # type: ignore[typeddict-unknown-key]
            connection.scope["_form"]  # type: ignore[typeddict-item]
            if "_form" in connection.scope
            else parse_multipart_form(
                body=await connection.body(),
                boundary=connection.content_type[-1].get("boundary", "").encode(),
                multipart_form_part_limit=multipart_form_part_limit,
            )
        )

        if signature_field.is_non_string_sequence:
            return list(form_values.values())
        if signature_field.is_simple_type and signature_field.field_type is UploadFile and form_values:
            return [v for v in form_values.values() if isinstance(v, UploadFile)][0]

        return form_values if form_values or not is_data_optional else None

    return cast("Callable[[ASGIConnection[Any, Any, Any, Any]], Coroutine[Any, Any, Any]]", extract_multipart)


def create_url_encoded_data_extractor(
    is_data_optional: bool,
) -> Callable[[ASGIConnection[Any, Any, Any, Any]], Coroutine[Any, Any, Any]]:
    """Create extractor for url encoded form-data.

    Args:
        is_data_optional: Boolean dictating whether the field is optional.

    Returns:
        An extractor function.
    """

    async def extract_url_encoded_extractor(
        connection: "Request[Any, Any, Any]",
    ) -> Any:
        connection.scope["_form"] = form_values = (  # type: ignore[typeddict-unknown-key]
            connection.scope["_form"]  # type: ignore[typeddict-item]
            if "_form" in connection.scope
            else parse_url_encoded_form_data(await connection.body())
        )
        return form_values if form_values or not is_data_optional else None

    return cast(
        "Callable[[ASGIConnection[Any, Any, Any, Any]], Coroutine[Any, Any, Any]]", extract_url_encoded_extractor
    )


def create_data_extractor(kwargs_model: KwargsModel) -> Callable[[dict[str, Any], ASGIConnection], None]:
    """Create an extractor for a request's body.

    Args:
        kwargs_model: The KwargsModel instance.

    Returns:
        An extractor for the request's body.
    """

    if kwargs_model.expected_form_data:
        media_type, signature_field = kwargs_model.expected_form_data

        if media_type == RequestEncodingType.MULTI_PART:
            data_extractor = create_multipart_extractor(
                signature_field=signature_field,
                is_data_optional=kwargs_model.is_data_optional,
            )
        else:
            data_extractor = create_url_encoded_data_extractor(is_data_optional=kwargs_model.is_data_optional)
    elif kwargs_model.expected_msgpack_data:
        data_extractor = cast(
            "Callable[[ASGIConnection[Any, Any, Any, Any]], Coroutine[Any, Any, Any]]", msgpack_extractor
        )
    else:
        data_extractor = cast(
            "Callable[[ASGIConnection[Any, Any, Any, Any]], Coroutine[Any, Any, Any]]", json_extractor
        )

    def extractor(
        values: dict[str, Any],
        connection: ASGIConnection[Any, Any, Any, Any],
    ) -> None:
        values["data"] = data_extractor(connection)

    return extractor
