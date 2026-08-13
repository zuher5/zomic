import { useState } from "react";
import { Link } from "react-router-dom";
import { getJSON, imgSrc } from "../api.js";

export default function Search() {
  const [query, setQuery] = useState("");
  const [state, setState] = useState({ loading: false, error: null, data: [] });

  async function run(q) {
    setState({ loading: true, error: null, data: [] });
    try {
      const res = await getJSON(`/search?q=${encodeURIComponent(q)}&page=1&limit=20`);
      setState({ loading: false, error: null, data: res.data });
    } catch (err) {
      setState({ loading: false, error: err.message, data: [] });
    }
  }

  return (
    <main style={{ padding: "1.5rem", maxWidth: 900, margin: "0 auto" }}>
      <h1 style={{ fontSize: 22 }}>Search</h1>
      <form onSubmit={(e) => { e.preventDefault(); if (query.trim()) run(query.trim()); }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Comic title..."
          style={{ padding: "0.6rem", width: 300, borderRadius: 6, border: "1px solid #374151", background: "#111827", color: "#e5e7eb" }}
        />
        <button type="submit" style={{ marginLeft: 8, padding: "0.6rem 1rem", borderRadius: 6, border: 0, background: "#2563eb", color: "#fff" }}>Search</button>
      </form>

      {state.loading && <p style={{ color: "#9ca3af" }}>Loading...</p>}
      {state.error && <p style={{ color: "#f87171" }}>Error: {state.error}</p>}
      {!state.loading && !state.error && state.data.length === 0 && (
        <p style={{ color: "#9ca3af" }}>No results. Try a different title.</p>
      )}

      <ul style={{ listStyle: "none", padding: 0, marginTop: "1rem" }}>
        {state.data.map((c) => (
          <li key={c.id} style={{ borderBottom: "1px solid #1f2937", display: "flex", gap: "1rem", alignItems: "center", padding: "0.5rem 0" }}>
            <img src={imgSrc(c.cover_url)} alt={c.title} width={56} height={80} style={{ objectFit: "cover", borderRadius: 4 }} />
            <Link to={`/comics/${c.id}`} style={{ color: "#e5e7eb" }}>{c.title}</Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
