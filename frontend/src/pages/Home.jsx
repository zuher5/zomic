import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getJSON, imgSrc } from "../api.js";

function ComicCard({ comic }) {
  return (
    <Link to={`/comics/${comic.id}`} style={{ textDecoration: "none", color: "inherit", width: 160 }}>
      <img src={imgSrc(comic.cover_url)} alt={comic.title} width={160} height={220} style={{ objectFit: "cover", borderRadius: 8, background: "#1f2937" }} />
      <p style={{ fontSize: 13, margin: "6px 0 0" }}>{comic.title}</p>
    </Link>
  );
}

export default function Home() {
  const [params] = useSearchParams();
  const page = Number(params.get("page")) || 1;
  const [state, setState] = useState({ loading: true, error: null, data: [], meta: null });

  useEffect(() => {
    let active = true;
    setState({ loading: true, error: null, data: [], meta: null });
    getJSON(`/comics?page=${page}&limit=24`)
      .then((body) => active && setState({ loading: false, error: null, data: body.data, meta: body.meta }))
      .catch((err) => active && setState({ loading: false, error: err.message, data: [], meta: null }));
    return () => { active = false; };
  }, [page]);

  const { loading, error, data, meta } = state;
  const lastPage = Math.max(1, Math.ceil((meta?.total || 0) / (meta?.limit || 24)));

  return (
    <main style={{ padding: "1.5rem", maxWidth: 1100, margin: "0 auto" }}>
      <h1 style={{ fontSize: 22 }}>Latest Comics</h1>
      {loading && <p style={{ color: "#9ca3af" }}>Loading...</p>}
      {error && <p style={{ color: "#f87171" }}>Error: {error}</p>}
      {!loading && !error && (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem" }}>
            {data.map((c) => <ComicCard key={c.id} comic={c} />)}
          </div>
          <div style={{ display: "flex", gap: "1rem", marginTop: "2rem", justifyContent: "center" }}>
            {page > 1 && <Link to={`/?page=${page - 1}`}>Previous</Link>}
            <span>Page {page} / {lastPage}</span>
            {page < lastPage && <Link to={`/?page=${page + 1}`}>Next</Link>}
          </div>
        </>
      )}
    </main>
  );
}
