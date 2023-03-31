from typing import Dict, Optional, Union
from uuid import uuid4

import pytest
from pydantic import UUID4

from starlite import get
from starlite.params import Parameter, ParameterKwarg
from starlite.status_codes import HTTP_200_OK, HTTP_400_BAD_REQUEST
from starlite.testing import create_test_client


@pytest.mark.parametrize(
    "t_type,param_dict, param, should_raise",
    [
        (str, {"special-header": "123"}, Parameter(header="special-header", min_length=1, max_length=3), False),
        (str, {"special-header": "123"}, Parameter(header="special-header", min_length=1, max_length=2), True),
        (str, {}, Parameter(header="special-header", min_length=1, max_length=2), True),
        (Optional[str], {}, Parameter(header="special-header", min_length=1, max_length=2, required=False), False),
        (int, {"special-header": "123"}, Parameter(header="special-header", ge=100, le=201), False),
        (int, {"special-header": "123"}, Parameter(header="special-header", ge=100, le=120), True),
        (int, {}, Parameter(header="special-header", ge=100, le=120), True),
        (Optional[int], {}, Parameter(header="special-header", ge=100, le=120, required=False), False),
    ],
)
def test_header_params(
    t_type: Optional[Union[str, int]], param_dict: Dict[str, str], param: ParameterKwarg, should_raise: bool
) -> None:
    test_path = "/test"

    @get(path=test_path)
    def test_method(special_header: t_type = param) -> None:  # type: ignore
        if special_header:
            assert special_header in (param_dict.get("special-header"), int(param_dict.get("special-header")))  # type: ignore

    with create_test_client(test_method) as client:
        response = client.get(test_path, headers=param_dict)
        if should_raise:
            assert response.status_code == HTTP_400_BAD_REQUEST, response.json()
        else:
            assert response.status_code == HTTP_200_OK, response.json()


def test_header_param_example() -> None:
    test_token = "123abc"

    @get(path="/users/{user_id:uuid}/")
    async def my_method(
        user_id: UUID4,
        token: str = Parameter(header="X-API-KEY"),
    ) -> None:
        assert user_id
        assert token == test_token

    with create_test_client(my_method) as client:
        response = client.get(f"/users/{uuid4()}/", headers={"X-API-KEY": test_token})
        assert response.status_code == HTTP_200_OK
