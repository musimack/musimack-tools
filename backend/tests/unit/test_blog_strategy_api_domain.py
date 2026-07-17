from musimack_tools.api.blog_strategy import create_blog_strategy_router
from musimack_tools.api.dependencies import permission_for_request
from musimack_tools.domain.api import InternalApiConfiguration
from musimack_tools.domain.authentication import Permission, UserRole, permissions_for_role


def test_blog_strategy_permissions_are_private_and_narrow() -> None:
    prefix = "/api/internal/v1/blog-strategy/projects/p1"
    assert permission_for_request("GET", prefix) is Permission.BLOG_STRATEGY_VIEW
    assert permission_for_request("POST", f"{prefix}/import") is Permission.BLOG_STRATEGY_IMPORT
    assert permission_for_request("PATCH", f"{prefix}/pages/x") is Permission.BLOG_STRATEGY_REVIEW
    assert (
        permission_for_request("POST", f"{prefix}/pages/x/approve")
        is Permission.BLOG_STRATEGY_APPROVE
    )
    assert permission_for_request("POST", f"{prefix}/export") is Permission.BLOG_STRATEGY_EXPORT
    assert Permission.BLOG_STRATEGY_VIEW in permissions_for_role(UserRole.VIEWER)
    assert Permission.BLOG_STRATEGY_APPROVE not in permissions_for_role(UserRole.OPERATOR)
    assert Permission.BLOG_STRATEGY_APPROVE in permissions_for_role(UserRole.ADMINISTRATOR)


def test_blog_strategy_router_exposes_no_public_routes() -> None:
    router = create_blog_strategy_router(
        object(), InternalApiConfiguration(mount_internal_routes=True)
    )
    paths = {getattr(route, "path", "") for route in router.routes}
    assert paths
    assert all(path.startswith("/api/internal/v1/blog-strategy/") for path in paths)
    assert all(not path.startswith("/api/blog-strategy") for path in paths)
