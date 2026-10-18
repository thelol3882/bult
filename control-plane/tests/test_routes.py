"""RouteWriter tests: files only, no nginx, no network (tmp_path)."""

import asyncio
import json

import pytest

from app.ingress.routes import Route, RouteApplyError, RouteWriter, Upstream, render
from tests.fakes import one_route


def test_render_server_block():
    files = render([one_route("blog", "192.168.252.6", 20002)], "bult.localhost")

    assert list(files) == ["blog.conf"]
    conf = files["blog.conf"]
    assert "server_name blog.bult.localhost;" in conf
    assert "server 192.168.252.6:20002;" in conf
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

    assert "server 192.168.252.6:20002;" in conf
    assert "server 192.168.252.7:20005;" in conf
    assert conf.count("proxy_pass") == 1  # one upstream block, nginx round-robins
