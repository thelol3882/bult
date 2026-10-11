"""RouteWriter tests: files only, no nginx, no network (tmp_path)."""

import asyncio
import json

import pytest

from app.services.nginx import Route, RouteApplyError, RouteWriter, render


def test_render_server_block():
    files = render([Route("blog", "192.168.252.6", 20002)])

    assert list(files) == ["blog.conf"]
    conf = files["blog.conf"]
    assert "server_name blog.bult.localhost;" in conf
    assert "server 192.168.252.6:20002;" in conf
    assert "proxy_pass http://app_blog;" in conf
    assert "proxy_connect_timeout 3s;" in conf


def test_apply_writes_version_atomically(tmp_path):
    writer = RouteWriter(tmp_path)
    desired = tmp_path / "desired"

    gen1 = writer.apply([Route("blog", "192.168.252.6", 20002)])
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

    writer = RouteWriter(tmp_path)

    assert writer.apply([]) == 8


def test_wait_applied_rejected_and_timeout(tmp_path):
    writer = RouteWriter(tmp_path)
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
