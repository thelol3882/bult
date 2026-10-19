import { useEffect, useState } from "react";

// Relative paths only: the page and the API share one origin, the ingress routes /api.
async function api(path, options) {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return {
    replica: response.headers.get("X-Replica"),
    data: response.status === 204 ? null : await response.json(),
  };
}

export default function App() {
  const [todos, setTodos] = useState([]);
  const [title, setTitle] = useState("");
  const [replica, setReplica] = useState(null);
  const [error, setError] = useState(null);

  async function call(path, options) {
    try {
      const result = await api(path, options);
      setReplica(result.replica);
      setError(null);
      return result.data;
    } catch (e) {
      setError(e.message);
      return undefined;
    }
  }

  async function load() {
    const data = await call("/todos");
    if (data) setTodos(data);
  }

  useEffect(() => {
    load();
  }, []);

  async function add(event) {
    event.preventDefault();
    if (!title.trim()) return;
    const created = await call("/todos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    if (created) {
      setTitle("");
      await load();
    }
  }

  async function remove(id) {
    await call(`/todos/${id}`, { method: "DELETE" });
    await load();
  }

  return (
    <main className="card">
      <h1>
        <span className="dot" /> Todos
      </h1>
      <p className="sub">
        Page: <code>react-todos</code>. API: <code>/api</code>, routed to another app by bult.
      </p>

      <form onSubmit={add}>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="What needs doing?"
          maxLength={200}
          aria-label="New todo"
        />
        <button type="submit">Add</button>
      </form>

      {error && <p className="error">API error: {error}</p>}

      <ul>
        {todos.map((todo) => (
          <li key={todo.id}>
            <span>{todo.title}</span>
            <button className="ghost" onClick={() => remove(todo.id)} aria-label="Delete">
              ×
            </button>
          </li>
        ))}
        {todos.length === 0 && !error && <li className="empty">Nothing yet.</li>}
      </ul>

      <p className="replica">
        Answered by replica <code>{replica ?? "-"}</code>
        <button className="ghost" onClick={load}>
          refresh
        </button>
      </p>
    </main>
  );
}
