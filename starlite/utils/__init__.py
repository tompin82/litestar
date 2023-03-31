from starlite.utils.deprecation import deprecated, warn_deprecation

from .helpers import Ref, get_enum_string_value, get_name
from .path import join_paths, normalize_path
from .predicates import (
    is_any,
    is_class_and_subclass,
    is_dataclass_class,
    is_mapping,
    is_optional_union,
    is_pydantic_model_class,
    is_pydantic_model_instance,
    is_typed_dict,
    is_union,
)
from .pydantic import (
    convert_dataclass_to_model,
    convert_typeddict_to_model,
    create_parsed_model_field,
)
from .scope import (
    delete_starlite_scope_state,
    get_serializer_from_scope,
    get_starlite_scope_state,
    set_starlite_scope_state,
)
from .sequence import compact, find_index, unique
from .sync import (
    AsyncCallable,
    AsyncIteratorWrapper,
    as_async_callable_list,
    async_partial,
    is_async_callable,
)
from .typing import annotation_is_iterable_of_type, get_origin_or_inner_type, make_non_optional_union

__all__ = (
    "AsyncCallable",
    "AsyncIteratorWrapper",
    "Ref",
    "annotation_is_iterable_of_type",
    "as_async_callable_list",
    "async_partial",
    "compact",
    "convert_dataclass_to_model",
    "convert_typeddict_to_model",
    "create_parsed_model_field",
    "delete_starlite_scope_state",
    "deprecated",
    "find_index",
    "get_enum_string_value",
    "get_name",
    "get_origin_or_inner_type",
    "get_serializer_from_scope",
    "get_starlite_scope_state",
    "is_any",
    "is_async_callable",
    "is_class_and_subclass",
    "is_dataclass_class",
    "is_mapping",
    "is_optional_union",
    "is_pydantic_model_class",
    "is_pydantic_model_instance",
    "is_typed_dict",
    "is_union",
    "join_paths",
    "make_non_optional_union",
    "normalize_path",
    "set_starlite_scope_state",
    "unique",
    "warn_deprecation",
)
