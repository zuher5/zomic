import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import Home from "./pages/Home.jsx";
import ComicDetail from "./pages/ComicDetail.jsx";
import Reader from "./pages/Reader.jsx";
import Search from "./pages/Search.jsx";

export default function App() {
  return (
    <BrowserRouter>
      <nav style={{ display: "flex", gap: "1rem", padding: "1rem", borderBottom: "1px solid #1f2937" }}>
        <Link to="/" style={{ color: "#60a5fa", fontWeight: 700 }}>Zomic</Link>
        <Link to="/search" style={{ color: "#9ca3af" }}>Search</Link>
      </nav>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/search" element={<Search />} />
        <Route path="/comics/:id" element={<ComicDetail />} />
        <Route path="/reader/:comicId/:chapterId" element={<Reader />} />
      </Routes>
    </BrowserRouter>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
