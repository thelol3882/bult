"""Apps API tests."""

import pytest
from fastapi.testclient import TestClient

VALID = {
    "name": "blog",
    "preset": "fastapi",
    "repo_url": "https://github.com/thelol3882/bult",
    "branch": "main",
    "subdir": "examples/fastapi-hello",
}


def create(client: TestClient, **overrides):
    """POST /apps with VALID plus overrides."""
    return client.post("/apps", json={**VALID, **overrides})


def test_create_app(client: TestClient):
    resp = create(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "blog"
    assert body["url"] == "http://blog.bult.localhost"
    assert "created_at" in body

    resp = client.get("/apps/blog")
    assert resp.status_code == 200
    assert resp.json()["name"] == "blog"


def test_create_duplicate_name(client: TestClient):
    assert create(client).status_code == 201
    resp = create(client)
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "app_name_taken"
    assert body["field"] == "name"


@pytest.mark.parametrize("name", ["-blog", "blog-", "Blog", "b" * 64, "", "api", "my_app"])
def test_create_invalid_name(client: TestClient, name: str):
    resp = create(client, name=name)
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "validation_error"
    assert "name" in body["fields"]


def test_create_rejects_non_https_repo(client: TestClient):
    resp = create(client, repo_url="http://github.com/thelol3882/bult")
    assert resp.status_code == 422


def test_list_is_sorted(client: TestClient):
    for name in ("zeta", "alpha", "mid"):
        assert create(client, name=name).status_code == 201
    names = [app["name"] for app in client.get("/apps").json()["results"]]
    assert names == ["alpha", "mid", "zeta"]


def test_list_pages(client: TestClient):
    for name in ("a", "b", "c"):
        create(client, name=name)
    page = client.get("/apps?page=2&page_size=2").json()
    assert page["count"] == 3
    assert [a["name"] for a in page["results"]] == ["c"]
    assert page["previous"] == 1 and page["next"] is None


def test_get_missing(client: TestClient):
    assert client.get("/apps/nope").status_code == 404


def test_patch_changes_only_sent_fields(client: TestClient):
    create(client)
    resp = client.patch("/apps/blog", json={"branch": "dev"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["branch"] == "dev"
    assert body["subdir"] == VALID["subdir"]


def test_patch_empty_subdir_is_kept(client: TestClient):
    create(client)
    resp = client.patch("/apps/blog", json={"subdir": ""})
    assert resp.status_code == 200
    assert resp.json()["subdir"] == ""


@pytest.mark.parametrize("body, field", [({"branch": None}, "branch"), ({"name": "x"}, "name")])
def test_patch_rejects_null_and_unknown_fields(client: TestClient, body: dict, field: str):
    create(client)
    resp = client.patch("/apps/blog", json=body)
    assert resp.status_code == 422
    assert field in resp.json()["fields"]


def test_patch_missing_app_is_404(client: TestClient):
    resp = client.patch("/apps/nope", json={"branch": "dev"})
    assert resp.status_code == 404


def test_list_page_past_the_end_points_back_to_last_page(client: TestClient):
    for name in ("a", "b", "c", "d", "e"):
        create(client, name=name)
    page = client.get("/apps?page=9&page_size=2").json()
    assert page["results"] == []
    assert page["previous"] == 3 and page["next"] is None


@pytest.mark.parametrize("page", [1, 3])
def test_empty_list_has_no_neighbours(client: TestClient, page: int):
    body = client.get(f"/apps?page={page}").json()
    assert body["count"] == 0 and body["results"] == []
    assert body["previous"] is None and body["next"] is None
