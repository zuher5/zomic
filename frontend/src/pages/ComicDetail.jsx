import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getJSON, imgSrc } from "../api.js";

export default function ComicDetail() {
  const { id } = useParams();
  const [state, setState] = useState({ loading: true, error: null, comic: null, chapters: [] });

  useEffect(() => {
    let active = true;
    Promise.all([getJSON(`/comics/${id}`), getJSON(`/comics/${id}/chapters`)])
      .then(([comicRes, chRes]) =>
        active && setState({ loading: false, error: null, comic: comicRes.data, chapters: chRes.data })
      )
      .catch((err) => active && setState({ loading: false, error: err.message, comic: null, chapters: [] }));
    return () => { active = false; };
  }, [id]);

  const { loading, error, comic, chapters } = state;

  if (loading) return <main style={{ padding: "1.5rem" }}><p style={{ color: "#9ca3af" }}>Loading...</p></main>;
  if (error) return <main style={{ padding: "1.5rem" }}><p style={{ color: "#f87171" }}>Error: {error}</p></main>;

  return (
    <main style={{ padding: "1.5rem", maxWidth: 900, margin: "0 auto" }}>
      <div style={{ display: "flex", gap: "1.5rem" }}>
        <img src={imgSrc(comic.cover_url)} alt={comic.title} width={220} height={300} style={{ objectFit: "cover", borderRadius: 8 }} />
        <div>
          <h1 style={{ fontSize: 24, margin: 0 }}>{comic.title}</h1>
          <p style={{ color: "#9ca3af" }}>Author: {comic.author || "-"} · {comic.status}</p>
          <p style={{ color: "#9ca3af" }}>Genres: {comic.genres.join(", ") || "-"}</p>
          <p style={{ whiteSpace: "pre-wrap" }}>{comic.synopsis}</p>
        </div>
      </div>
      <h2 style={{ fontSize: 18, marginTop: "2rem" }}>Chapters</h2>
      <ul style={{ listStyle: "none", padding: 0 }}>
        {[...chapters].sort((a, b) => a.index - b.index).map((ch) => (
          <li key={ch.id} style={{ borderBottom: "1px solid #1f2937" }}>
            <Link to={`/reader/${id}/${ch.id}`} style={{ color: "#e5e7eb", padding: "0.75rem 0", display: "block" }}>
              Chapter {ch.index}{ch.title ? ` - ${ch.title}` : ""}
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
