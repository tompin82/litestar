from __future__ import annotations

from enum import Enum
from inspect import Signature
from typing import TYPE_CHECKING, AnyStr, Mapping, cast

from typing_extensions import TypedDict

from starlite._layers.utils import narrow_response_cookies, narrow_response_headers
from starlite._signature.utils import get_signature_model
from starlite.datastructures.cookie import Cookie
from starlite.datastructures.response_header import ResponseHeader
from starlite.enums import HttpMethod, MediaType
from starlite.exceptions import (
    HTTPException,
    ImproperlyConfiguredException,
)
from starlite.handlers.base import BaseRouteHandler
from starlite.handlers.http_handlers._utils import (
    create_data_handler,
    create_generic_asgi_response_handler,
    create_response_container_handler,
    create_response_handler,
    get_default_status_code,
    normalize_http_method,
)
from starlite.response import FileResponse, Response
from starlite.response_containers import File, Redirect, ResponseContainer
from starlite.status_codes import HTTP_204_NO_CONTENT, HTTP_304_NOT_MODIFIED
from starlite.types import (
    AfterRequestHookHandler,
    AfterResponseHookHandler,
    AnyCallable,
    ASGIApp,
    BeforeRequestHookHandler,
    CacheKeyBuilder,
    Empty,
    EmptyType,
    ExceptionHandlersMap,
    Guard,
    Method,
    Middleware,
    ResponseCookies,
    ResponseHeaders,
    ResponseType,
    TypeEncodersMap,
)
from starlite.utils import AsyncCallable, Ref, is_async_callable, is_class_and_subclass

if TYPE_CHECKING:
    from typing import Any, Awaitable, Callable, Sequence

    from starlite.app import Starlite
    from starlite.background_tasks import BackgroundTask, BackgroundTasks
    from starlite.config.response_cache import CACHE_FOREVER
    from starlite.connection import Request
    from starlite.datastructures import CacheControlHeader, ETag
    from starlite.datastructures.headers import Header
    from starlite.di import Provide
    from starlite.openapi.datastructures import ResponseSpec
    from starlite.openapi.spec import SecurityRequirement
    from starlite.plugins import SerializationPluginProtocol
    from starlite.types import MaybePartial  # noqa: F401


__all__ = ("HTTPRouteHandler", "route")


class ResponseHandlerMap(TypedDict):
    default_handler: Callable[[Any], Awaitable[ASGIApp]] | EmptyType
    response_type_handler: Callable[[Any], Awaitable[ASGIApp]] | EmptyType


class HTTPRouteHandler(BaseRouteHandler["HTTPRouteHandler"]):
    """HTTP Route Decorator.

    Use this decorator to decorate an HTTP handler with multiple methods.
    """

    __slots__ = (
        "_resolved_after_response",
        "_resolved_before_request",
        "_response_handler_mapping",
        "after_request",
        "after_response",
        "background",
        "before_request",
        "cache",
        "cache_control",
        "cache_key_builder",
        "content_encoding",
        "content_media_type",
        "deprecated",
        "description",
        "etag",
        "has_sync_callable",
        "http_methods",
        "include_in_schema",
        "media_type",
        "operation_id",
        "raises",
        "response_class",
        "response_cookies",
        "response_description",
        "response_headers",
        "responses",
        "security",
        "status_code",
        "summary",
        "sync_to_thread",
        "tags",
        "template_name",
    )

    has_sync_callable: bool

    def __init__(
        self,
        path: str | Sequence[str] | None = None,
        *,
        after_request: AfterRequestHookHandler | None = None,
        after_response: AfterResponseHookHandler | None = None,
        background: BackgroundTask | BackgroundTasks | None = None,
        before_request: BeforeRequestHookHandler | None = None,
        cache: bool | int | type[CACHE_FOREVER] = False,
        cache_control: CacheControlHeader | None = None,
        cache_key_builder: CacheKeyBuilder | None = None,
        dependencies: Mapping[str, Provide] | None = None,
        etag: ETag | None = None,
        exception_handlers: ExceptionHandlersMap | None = None,
        guards: Sequence[Guard] | None = None,
        http_method: HttpMethod | Method | Sequence[HttpMethod | Method],
        media_type: MediaType | str | None = None,
        middleware: Sequence[Middleware] | None = None,
        name: str | None = None,
        opt: Mapping[str, Any] | None = None,
        response_class: ResponseType | None = None,
        response_cookies: ResponseCookies | None = None,
        response_headers: ResponseHeaders | None = None,
        status_code: int | None = None,
        sync_to_thread: bool = False,
        # OpenAPI related attributes
        content_encoding: str | None = None,
        content_media_type: str | None = None,
        deprecated: bool = False,
        description: str | None = None,
        include_in_schema: bool = True,
        operation_id: str | None = None,
        raises: Sequence[type[HTTPException]] | None = None,
        response_description: str | None = None,
        responses: Mapping[int, ResponseSpec] | None = None,
        signature_namespace: Mapping[str, Any] | None = None,
        security: Sequence[SecurityRequirement] | None = None,
        summary: str | None = None,
        tags: Sequence[str] | None = None,
        type_encoders: TypeEncodersMap | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize ``HTTPRouteHandler``.

        Args:
            path: A path fragment for the route handler function or a sequence of path fragments.
                If not given defaults to ``/``
            after_request: A sync or async function executed before a :class:`Request <.connection.Request>` is passed
                to any route handler. If this function returns a value, the request will not reach the route handler,
                and instead this value will be used.
            after_response: A sync or async function called after the response has been awaited. It receives the
                :class:`Request <.connection.Request>` object and should not return any values.
            background: A :class:`BackgroundTask <.background_tasks.BackgroundTask>` instance or
                :class:`BackgroundTasks <.background_tasks.BackgroundTasks>` to execute after the response is finished.
                Defaults to ``None``.
            before_request: A sync or async function called immediately before calling the route handler. Receives
                the :class:`Request <.connection.Request>` instance and any non-``None`` return value is used for the
                response, bypassing the route handler.
            cache: Enables response caching if configured on the application level. Valid values are ``True`` or a
                number of seconds (e.g. ``120``) to cache the response.
            cache_control: A ``cache-control`` header of type
                :class:`CacheControlHeader <.datastructures.CacheControlHeader>` that will be added to the response.
            cache_key_builder: A :class:`cache-key builder function <.types.CacheKeyBuilder>`. Allows for customization
                of the cache key if caching is configured on the application level.
            dependencies: A string keyed mapping of dependency :class:`Provider <.di.Provide>` instances.
            etag: An ``etag`` header of type :class:`ETag <.datastructures.ETag>` that will be added to the response.
            exception_handlers: A mapping of status codes and/or exception types to handler functions.
            guards: A sequence of :class:`Guard <.types.Guard>` callables.
            http_method: An :class:`http method string <.types.Method>`, a member of the enum
                :class:`HttpMethod <.enums.HttpMethod>` or a list of these that correlates to the methods the route
                handler function should handle.
            media_type: A member of the :class:`MediaType <.enums.MediaType>` enum or a string with a valid IANA
                Media-Type.
            middleware: A sequence of :class:`Middleware <.types.Middleware>`.
            name: A string identifying the route handler.
            opt: A string keyed mapping of arbitrary values that can be accessed in :class:`Guards <.types.Guard>` or
                wherever you have access to :class:`Request <.connection.Request>` or
                :class:`ASGI Scope <.types.Scope>`.
            response_class: A custom subclass of :class:`Response <.response.Response>` to be used as route handler's
                default response.
            response_cookies: A sequence of :class:`Cookie <.datastructures.Cookie>` instances.
            response_headers: A string keyed mapping of :class:`ResponseHeader <.datastructures.ResponseHeader>`
                instances.
            responses: A mapping of additional status codes and a description of their expected content.
                This information will be included in the OpenAPI schema
            signature_namespace: A mapping of names to types for use in forward reference resolution during signature modelling.
            status_code: An http status code for the response. Defaults to ``200`` for mixed method or ``GET``, ``PUT`` and
                ``PATCH``, ``201`` for ``POST`` and ``204`` for ``DELETE``.
            sync_to_thread: A boolean dictating whether the handler function will be executed in a worker thread or the
                main event loop. This has an effect only for sync handler functions. See using sync handler functions.
            content_encoding: A string describing the encoding of the content, e.g. ``"base64"``.
            content_media_type: A string designating the media-type of the content, e.g. ``"image/png"``.
            deprecated:  A boolean dictating whether this route should be marked as deprecated in the OpenAPI schema.
            description: Text used for the route's schema description section.
            include_in_schema: A boolean flag dictating whether  the route handler should be documented in the OpenAPI schema.
            operation_id: An identifier used for the route's schema operationId. Defaults to the ``__name__`` of the wrapped function.
            raises:  A list of exception classes extending from starlite.HttpException that is used for the OpenAPI documentation.
                This list should describe all exceptions raised within the route handler's function/method. The Starlite
                ValidationException will be added automatically for the schema if any validation is involved.
            response_description: Text used for the route's response schema description section.
            security: A sequence of dictionaries that contain information about which security scheme can be used on the endpoint.
            summary: Text used for the route's schema summary section.
            tags: A sequence of string tags that will be appended to the OpenAPI schema.
            type_encoders: A mapping of types to callables that transform them into types supported for serialization.
            **kwargs: Any additional kwarg - will be set in the opt dictionary.
        """
        if not http_method:
            raise ImproperlyConfiguredException("An http_method kwarg is required")

        self.http_methods = normalize_http_method(http_methods=http_method)
        self.status_code = status_code or get_default_status_code(http_methods=self.http_methods)

        super().__init__(
            path,
            dependencies=dependencies,
            exception_handlers=exception_handlers,
            guards=guards,
            middleware=middleware,
            name=name,
            opt=opt,
            signature_namespace=signature_namespace,
            type_encoders=type_encoders,
            **kwargs,
        )

        self.after_request = AsyncCallable(after_request) if after_request else None  # type: ignore[arg-type]
        self.after_response = AsyncCallable(after_response) if after_response else None
        self.background = background
        self.before_request = AsyncCallable(before_request) if before_request else None
        self.cache = cache
        self.cache_control = cache_control
        self.cache_key_builder = cache_key_builder
        self.etag = etag
        self.media_type: MediaType | str = media_type or ""
        self.response_class = response_class

        self.response_cookies: Sequence[Cookie] | None = narrow_response_cookies(response_cookies)
        self.response_headers: Sequence[ResponseHeader] | None = narrow_response_headers(response_headers)

        self.sync_to_thread = sync_to_thread
        # OpenAPI related attributes
        self.content_encoding = content_encoding
        self.content_media_type = content_media_type
        self.deprecated = deprecated
        self.description = description
        self.include_in_schema = include_in_schema
        self.operation_id = operation_id
        self.raises = raises
        self.response_description = response_description
        self.summary = summary
        self.tags = tags
        self.security = security
        self.responses = responses
        # memoized attributes, defaulted to Empty
        self._resolved_after_response: AfterResponseHookHandler | None | EmptyType = Empty
        self._resolved_before_request: BeforeRequestHookHandler | None | EmptyType = Empty
        self._response_handler_mapping: ResponseHandlerMap = {"default_handler": Empty, "response_type_handler": Empty}

    def __call__(self, fn: AnyCallable) -> HTTPRouteHandler:
        """Replace a function with itself."""
        self.fn = Ref["MaybePartial[AnyCallable]"](fn)
        self.signature = Signature.from_callable(fn)
        self._validate_handler_function()

        if not self.media_type:
            if self.signature.return_annotation in {str, bytes, AnyStr, Redirect, File} or any(
                is_class_and_subclass(self.signature.return_annotation, t_type) for t_type in (str, bytes)  # type: ignore
            ):
                self.media_type = MediaType.TEXT
            else:
                self.media_type = MediaType.JSON

        return self

    def resolve_response_class(self) -> type[Response]:
        """Return the closest custom Response class in the owner graph or the default Response class.

        This method is memoized so the computation occurs only once.

        Returns:
            The default :class:`Response <.response.Response>` class for the route handler.
        """
        for layer in list(reversed(self.ownership_layers)):
            if layer.response_class is not None:
                return layer.response_class
        return Response

    def resolve_response_headers(self) -> frozenset[ResponseHeader]:
        """Return all header parameters in the scope of the handler function.

        Returns:
            A dictionary mapping keys to :class:`ResponseHeader <.datastructures.ResponseHeader>` instances.
        """
        resolved_response_headers: dict[str, ResponseHeader] = {}

        for layer in self.ownership_layers:
            if layer_response_headers := layer.response_headers:
                if isinstance(layer_response_headers, Mapping):
                    # this can't happen unless you manually set response_headers on an instance, which would result in a
                    # type-checking error on everything but the controller. We cover this case nevertheless
                    resolved_response_headers.update(
                        {name: ResponseHeader(name=name, value=value) for name, value in layer_response_headers.items()}
                    )
                else:
                    resolved_response_headers.update({h.name: h for h in layer_response_headers})
            for extra_header in ("cache_control", "etag"):
                header_model: Header | None = getattr(layer, extra_header, None)
                if header_model:
                    resolved_response_headers[header_model.HEADER_NAME] = ResponseHeader(
                        name=header_model.HEADER_NAME,
                        value=header_model.to_header(),
                        documentation_only=header_model.documentation_only,
                    )

        return frozenset(resolved_response_headers.values())

    def resolve_response_cookies(self) -> frozenset[Cookie]:
        """Return a list of Cookie instances. Filters the list to ensure each cookie key is unique.

        Returns:
            A list of :class:`Cookie <.datastructures.Cookie>` instances.
        """
        response_cookies: set[Cookie] = set()
        for layer in reversed(self.ownership_layers):
            if layer_response_cookies := layer.response_cookies:
                if isinstance(layer_response_cookies, Mapping):
                    # this can't happen unless you manually set response_cookies on an instance, which would result in a
                    # type-checking error on everything but the controller. We cover this case nevertheless
                    response_cookies.update(
                        {Cookie(key=key, value=value) for key, value in layer_response_cookies.items()}
                    )
                else:
                    response_cookies.update(cast("set[Cookie]", layer_response_cookies))
        return frozenset(response_cookies)

    def resolve_before_request(self) -> BeforeRequestHookHandler | None:
        """Resolve the before_handler handler by starting from the route handler and moving up.

        If a handler is found it is returned, otherwise None is set.
        This method is memoized so the computation occurs only once.

        Returns:
            An optional :class:`before request lifecycle hook handler <.types.BeforeRequestHookHandler>`
        """
        if self._resolved_before_request is Empty:
            before_request_handlers: list[AsyncCallable] = [
                layer.before_request for layer in self.ownership_layers if layer.before_request  # type: ignore[misc]
            ]
            self._resolved_before_request = cast(
                "BeforeRequestHookHandler | None",
                before_request_handlers[-1] if before_request_handlers else None,
            )
        return self._resolved_before_request

    def resolve_after_response(self) -> AfterResponseHookHandler | None:
        """Resolve the after_response handler by starting from the route handler and moving up.

        If a handler is found it is returned, otherwise None is set.
        This method is memoized so the computation occurs only once.

        Returns:
            An optional :class:`after response lifecycle hook handler <.types.AfterResponseHookHandler>`
        """
        if self._resolved_after_response is Empty:
            after_response_handlers: list[AsyncCallable] = [
                layer.after_response for layer in self.ownership_layers if layer.after_response  # type: ignore[misc]
            ]
            self._resolved_after_response = cast(
                "AfterResponseHookHandler | None",
                after_response_handlers[-1] if after_response_handlers else None,
            )

        return cast("AfterResponseHookHandler | None", self._resolved_after_response)

    def get_response_handler(self, is_response_type_data: bool = False) -> Callable[[Any], Awaitable[ASGIApp]]:
        """Resolve the response_handler function for the route handler.

        This method is memoized so the computation occurs only once.

        Args:
            is_response_type_data: Whether to return a handler for 'Response' instances.

        Returns:
            Async Callable to handle an HTTP Request
        """
        if self._response_handler_mapping["default_handler"] is Empty:
            after_request_handlers: list[AsyncCallable] = [
                layer.after_request for layer in self.ownership_layers if layer.after_request  # type: ignore[misc]
            ]
            after_request = cast(
                "AfterRequestHookHandler | None",
                after_request_handlers[-1] if after_request_handlers else None,
            )

            media_type = self.media_type.value if isinstance(self.media_type, Enum) else self.media_type
            response_class = self.resolve_response_class()
            headers = self.resolve_response_headers()
            cookies = self.resolve_response_cookies()
            type_encoders = self.resolve_type_encoders()

            return_annotation = get_signature_model(self)._return_annotation

            if before_request_handler := self.resolve_before_request():
                before_request_handler_signature = Signature.from_callable(before_request_handler)
                if (
                    before_request_handler_signature.return_annotation
                    and before_request_handler_signature.return_annotation is not Signature.empty
                ):
                    return_annotation = before_request_handler_signature.return_annotation

            self._response_handler_mapping["response_type_handler"] = create_response_handler(
                cookies=cookies, after_request=after_request
            )

            if is_class_and_subclass(return_annotation, Response):
                self._response_handler_mapping["default_handler"] = self._response_handler_mapping[
                    "response_type_handler"
                ]
            elif is_class_and_subclass(return_annotation, ResponseContainer):  # type: ignore
                self._response_handler_mapping["default_handler"] = create_response_container_handler(
                    after_request=after_request,
                    cookies=cookies,
                    headers=headers,
                    media_type=media_type,
                    status_code=self.status_code,
                )
            elif is_async_callable(return_annotation) or return_annotation is ASGIApp:
                self._response_handler_mapping["default_handler"] = create_generic_asgi_response_handler(
                    cookies=cookies, after_request=after_request
                )
            else:
                self._response_handler_mapping["default_handler"] = create_data_handler(
                    after_request=after_request,
                    background=self.background,
                    cookies=cookies,
                    headers=headers,
                    media_type=media_type,
                    response_class=response_class,
                    return_annotation=return_annotation,
                    status_code=self.status_code,
                    type_encoders=type_encoders,
                )

        return cast(
            "Callable[[Any], Awaitable[ASGIApp]]",
            self._response_handler_mapping["response_type_handler"]
            if is_response_type_data
            else self._response_handler_mapping["default_handler"],
        )

    async def to_response(
        self, app: "Starlite", data: Any, plugins: list["SerializationPluginProtocol"], request: "Request"
    ) -> "ASGIApp":
        """Return a :class:`Response <.response.Response>` from the handler by resolving and calling it.

        Args:
            app: The :class:`Starlite <.app.Starlite>` app instance
            data: Either an instance of a :class:`ResponseContainer <.response_containers.ResponseContainer>`,
                a Response instance or an arbitrary value.
            plugins: An optional mapping of plugins
            request: A :class:`Request <.connection.Request>` instance

        Returns:
            A Response instance
        """
        response_handler = self.get_response_handler(is_response_type_data=isinstance(data, Response))
        return await response_handler(app=app, data=data, plugins=plugins, request=request)  # type: ignore

    def _validate_handler_function(self) -> None:
        """Validate the route handler function once it is set by inspecting its return annotations."""
        super()._validate_handler_function()

        if self.signature.return_annotation is Signature.empty:
            raise ImproperlyConfiguredException(
                "A return value of a route handler function should be type annotated."
                "If your function doesn't return a value, annotate it as returning 'None'."
            )

        if (
            self.status_code < 200 or self.status_code in {HTTP_204_NO_CONTENT, HTTP_304_NOT_MODIFIED}
        ) and self.signature.return_annotation not in {None, "None"}:
            raise ImproperlyConfiguredException(
                "A status code 204, 304 or in the range below 200 does not support a response body."
                "If the function should return a value, change the route handler status code to an appropriate value.",
            )

        if (
            is_class_and_subclass(self.signature.return_annotation, File)
            or is_class_and_subclass(self.signature.return_annotation, FileResponse)
        ) and self.media_type in (
            MediaType.JSON,
            MediaType.HTML,
        ):
            self.media_type = MediaType.TEXT

        if "socket" in self.signature.parameters:
            raise ImproperlyConfiguredException("The 'socket' kwarg is not supported with http handlers")

        if "data" in self.signature.parameters and "GET" in self.http_methods:
            raise ImproperlyConfiguredException("'data' kwarg is unsupported for 'GET' request handlers")


route = HTTPRouteHandler
