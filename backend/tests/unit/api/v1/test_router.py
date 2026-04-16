"""
Tests for API router registration.
"""

from app.api.v1.router import api_v1_router


class TestRouterRegistration:
    def test_negotiations_route_registered(self):
        """验证 /negotiations 路由已注册"""
        routes = api_v1_router.routes
        path_found = any(
            getattr(route, "path", "").startswith("/negotiations")
            for route in routes
        )
        assert path_found, "/negotiations route should be registered in api_v1_router"

    def test_health_route_registered(self):
        routes = api_v1_router.routes
        tags_found = any(
            "health" in getattr(route, "tags", []) for route in routes
        )
        assert tags_found, "health route should be registered"
