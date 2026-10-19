"""FastAPI preset demo: a todo API under /api, in memory, that tells which replica answered."""

import socket
from itertools import count

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, Field

app = FastAPI(title="fastapi-todos")
REPLICA = socket.gethostname()

# Per replica: with several replicas each one has its own list. Real state belongs in a database.
todos: dict[int, dict] = {}
ids = count(1)


class TodoIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@app.middleware("http")
async def add_replica_header(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["X-Replica"] = REPLICA
    return response


@app.get("/api/todos")
def list_todos() -> list[dict]:
    return list(todos.values())


@app.post("/api/todos", status_code=201)
def create_todo(payload: TodoIn) -> dict:
    todo = {"id": next(ids), "title": payload.title.strip()}
    todos[todo["id"]] = todo
    return todo


@app.delete("/api/todos/{todo_id}", status_code=204)
def delete_todo(todo_id: int) -> None:
    todos.pop(todo_id, None)


@app.get("/api/healthz")
def healthz() -> dict:
    return {"status": "ok", "replica": REPLICA}
