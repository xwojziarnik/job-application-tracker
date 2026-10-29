"""The real application (``create_app``) renders framework errors in the shared format.

``test_exceptions.py`` checks the handlers on a minimal app; these tests check that
``create_app`` registers them, so the API's own 404 and 405 are not in FastAPI's default
``{"detail": ...}`` shape.
"""

from httpx import AsyncClient


async def test_unknown_route_returns_not_found_in_shared_format(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not Found"}}


async def test_unsupported_method_returns_method_not_allowed_with_allow_header(
    client: AsyncClient,
) -> None:
    response = await client.delete("/api/v1/health")

    assert response.status_code == 405
    assert response.json() == {
        "error": {"code": "method_not_allowed", "message": "Method Not Allowed"}
    }
    assert response.headers["allow"] == "GET"
