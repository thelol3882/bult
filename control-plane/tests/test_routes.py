"""RouteWriter tests: files only, no nginx, no network (tmp_path)."""

import asyncio
import json

import pytest

from app.ingress.routes import (
    LbAlgorithm,
    PathRoute,
    Route,
    RouteApplyError,
    RouteWriter,
    Upstream,
    render,
    with_paths,
)
from tests.fakes import one_route


def test_render_server_block():
    files = render([one_route("blog", "192.168.252.6", 20002)], "bult.localhost")

    assert list(files) == ["blog.conf"]
    conf = files["blog.conf"]
    assert "server_name blog.bult.localhost;" in conf
    assert "server 192.168.252.6:20002 max_fails=3 fail_timeout=10s;" in conf
    assert "proxy_pass http://app_blog;" in conf
    assert "proxy_connect_timeout 3s;" in conf


def test_apply_writes_version_atomically(tmp_path):
    writer = RouteWriter(tmp_path, "bult.localhost")
    desired = tmp_path / "desired"

    gen1 = writer.apply([one_route("blog", "192.168.252.6", 20002)])
    gen2 = writer.apply([])

    assert (gen1, gen2) == (1, 2)
    assert (desired / "1" / "blog.conf").exists()
    assert (desired / "2").is_dir()
    assert list((desired / "2").iterdir()) == []
    assert (desired / "LATEST").read_text().strip() == "2"
    assert list(desired.glob(".tmp-*")) == []
    assert not (desired / "LATEST.tmp").exists()


def test_numbering_continues_from_disk(tmp_path):
    (tmp_path / "status.json").write_text(json.dumps({"generation": 7, "ok": True}))

    writer = RouteWriter(tmp_path, "bult.localhost")

    assert writer.apply([]) == 8


def test_wait_applied_rejected_and_timeout(tmp_path):
    writer = RouteWriter(tmp_path, "bult.localhost")
    status_file = tmp_path / "status.json"

    status_file.write_text(
        json.dumps(
            {"generation": 3, "ok": False, "error": "unexpected '}' in blog.conf"}
        )
    )
    with pytest.raises(RouteApplyError, match="unexpected '}' in blog.conf"):
        asyncio.run(writer.wait_applied(3, timeout=1.0))

    status_file.write_text(json.dumps({"generation": 3, "ok": True}))
    with pytest.raises(TimeoutError):
        asyncio.run(writer.wait_applied(4, timeout=0.3))


def test_render_stopped_app_is_a_server_block_without_an_upstream():
    files = render(
        [one_route("blog", "192.168.252.6", 20002)], "bult.localhost", stopped=["shop"]
    )

    assert sorted(files) == ["blog.conf", "shop.conf"]
    shop = files["shop.conf"]
    assert "server_name shop.bult.localhost;" in shop
    assert "include /etc/nginx/bult/snippets/stopped.conf;" in shop
    assert "proxy_pass" not in shop and "upstream" not in shop


def test_a_route_wins_over_the_stopped_flag_for_the_same_name():
    files = render([one_route("blog", "192.168.252.6", 20002)], "bult.localhost", ["blog"])

    assert "proxy_pass http://app_blog;" in files["blog.conf"]


def test_apply_writes_stopped_apps(tmp_path):
    writer = RouteWriter(tmp_path, "bult.localhost")

    gen = writer.apply([], stopped=["shop"])

    assert (tmp_path / "desired" / str(gen) / "shop.conf").exists()


def test_render_balances_over_every_replica_of_the_app():
    route = Route(
        "blog",
        (Upstream("192.168.252.6", 20002), Upstream("192.168.252.7", 20005)),
    )

    conf = render([route], "bult.localhost")["blog.conf"]

    assert "server 192.168.252.6:20002 " in conf
    assert "server 192.168.252.7:20005 " in conf
    assert conf.count("proxy_pass") == 1  # one upstream block, nginx round-robins


def _upstream_block(conf: str) -> str:
    return conf[conf.index("upstream "): conf.index("server {")]


def test_upstream_has_zone_failure_marks_and_keepalive():
    conf = render([one_route("blog", "192.168.252.6", 20002)], "bult.localhost")["blog.conf"]

    upstream = _upstream_block(conf)
    assert "zone app_blog 64k;" in upstream
    assert "max_fails=3 fail_timeout=10s;" in upstream
    assert "keepalive 16;" in upstream
    # `keepalive` after the balancing method, `zone` before it
    assert upstream.index("zone") < upstream.index("server ") < upstream.index("keepalive")


@pytest.mark.parametrize("algorithm", ["least_conn", "ip_hash"])
def test_balancing_algorithm_is_a_directive_before_the_servers(algorithm: LbAlgorithm):
    route = one_route("blog", "192.168.252.6", 20002)

    upstream = _upstream_block(render([route], "bult.localhost", algorithm=algorithm)["blog.conf"])

    assert f"    {algorithm};\n" in upstream
    assert upstream.index(algorithm) < upstream.index("server ") < upstream.index("keepalive")


def test_round_robin_adds_no_directive():
    upstream = _upstream_block(
        render([one_route("blog", "192.168.252.6", 20002)], "bult.localhost")["blog.conf"]
    )

    assert "least_conn" not in upstream and "ip_hash" not in upstream


def test_writer_renders_with_its_algorithm(tmp_path):
    writer = RouteWriter(tmp_path, "bult.localhost", "least_conn")

    gen = writer.apply([one_route("blog", "192.168.252.6", 20002)])

    assert "least_conn;" in (tmp_path / "desired" / str(gen) / "blog.conf").read_text()


def test_proxied_location_retries_only_unsent_requests_and_keeps_inherited_headers():
    conf = render([one_route("blog", "192.168.252.6", 20002)], "bult.localhost")["blog.conf"]

    assert "proxy_next_upstream error timeout;" in conf
    assert "proxy_next_upstream_tries 2;" in conf
    assert "non_idempotent;" not in conf
    # one proxy_set_header in a location hides all of nginx.conf's (Host, X-Forwarded-*)
    assert "proxy_set_header" not in conf


def _shop_routes(*paths: PathRoute, api_running: bool = True) -> list[Route]:
    shop = Route("shop", (Upstream("10.0.0.5", 30001),), paths)
    api = [Route("shop-api", (Upstream("10.0.0.6", 30002),))] if api_running else []
    return [shop, *api]


def test_path_route_proxies_to_the_target_upstream_without_stripping_the_prefix():
    conf = render(_shop_routes(PathRoute("/api", "shop-api")), "bult.localhost")["shop.conf"]

    assert "location /api/ {\n        proxy_pass http://app_shop-api;\n" in conf  # no URI: not stripped
    assert "proxy_pass http://app_shop-api/" not in conf
    assert "location / {\n        proxy_pass http://app_shop;\n" in conf
    # the target's own file has its upstream
    assert "upstream app_shop-api {" in render(
        _shop_routes(PathRoute("/api", "shop-api")), "bult.localhost"
    )["shop-api.conf"]


def test_longer_paths_come_first_and_the_root_location_last():
    conf = render(
        _shop_routes(PathRoute("/api", "shop-api"), PathRoute("/api/v2", "shop-api")),
        "bult.localhost",
    )["shop.conf"]

    assert conf.index("location /api/v2/") < conf.index("location /api/ ") < conf.index("location / ")


def test_stopped_target_answers_503_json_not_the_frontend():
    conf = render(
        _shop_routes(PathRoute("/api", "shop-api"), api_running=False), "bult.localhost"
    )["shop.conf"]

    assert "location = /api {" in conf and "location /api/ {" in conf
    assert "proxy_pass http://app_shop-api" not in conf
    assert conf.count("return 503 '{\"detail\": \"backend is not running\", \"code\": \"backend_unavailable\"}';") == 2
    assert "default_type application/json;" in conf
    assert "types {}" in conf  # else the extension (/api/x.png) would pick the Content-Type
    assert "proxy_pass http://app_shop;" in conf  # the frontend itself is still served


def test_app_without_paths_has_only_the_root_location():
    conf = render(_shop_routes(), "bult.localhost")["shop.conf"]

    assert conf.count("location ") == 1


def test_with_paths_attaches_only_to_known_routes():
    routes = [one_route("shop", "10.0.0.5", 30001)]

    result = with_paths(routes, {"shop": [PathRoute("/api", "x")], "ghost": [PathRoute("/a", "x")]})

    assert result[0].paths == (PathRoute("/api", "x"),)
    assert len(result) == 1
