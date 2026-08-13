import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getJSON, imgSrc } from "../api.js";

export default function Reader() {
  const { comicId, chapterId } = useParams();
  const [state, setState] = useState({ loading: true, error: null, title: "", chapters: [], pages: [] });

  useEffect(() => {
    let active = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    Promise.all([
      getJSON(`/comics/${comicId}`),
      getJSON(`/comics/${comicId}/chapters`),
      getJSON(`/chapters/${chapterId}/pages`),
    ])
      .then(([comicRes, chRes, pgRes]) =>
        active && setState({ loading: false, error: null, title: comicRes.data.title, chapters: chRes.data, pages: pgRes.data })
      )
      .catch((err) => active && setState({ loading: false, error: err.message, title: "", chapters: [], pages: [] }));
    return () => { active = false; };
  }, [comicId, chapterId]);

  const { loading, error, title, chapters, pages } = state;
  const sorted = [...chapters].sort((a, b) => a.index - b.index);
  const current = sorted.findIndex((c) => String(c.id) === String(chapterId));
  const prev = current > 0 ? sorted[current - 1] : null;
  const next = current >= 0 && current < sorted.length - 1 ? sorted[current + 1] : null;

  if (loading) return <main style={{ padding: "1.5rem" }}><p style={{ color: "#9ca3af" }}>Loading...</p></main>;
  if (error) return <main style={{ padding: "1.5rem" }}><p style={{ color: "#f87171" }}>Error: {error}</p></main>;

  return (
    <main style={{ maxWidth: 800, margin: "0 auto", padding: "1rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem", marginBottom: "1rem" }}>
        <Link to={`/comics/${comicId}`} style={{ color: "#60a5fa" }}>← {title}</Link>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          {prev && <Link to={`/reader/${comicId}/${prev.id}`} style={{ color: "#e5e7eb" }}>← Prev</Link>}
          <span style={{ color: "#9ca3af" }}>Chapter {sorted[current]?.index}</span>
          {next && <Link to={`/reader/${comicId}/${next.id}`} style={{ color: "#e5e7eb" }}>Next →</Link>}
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
        {pages.map((p) => (
          <img
            key={p.id}
            src={imgSrc(p.url)}
            alt={`Page ${p.position}`}
            loading="lazy"
            width="100%"
            style={{ display: "block", borderRadius: 6, background: "#111827" }}
          />
        ))}
      </div>
    </main>
  );
}
