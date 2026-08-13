export async function getJSON(path) {
  const res = await fetch(`/api${path}`);
  if (!res.ok) throw new Error(`request failed: ${res.status}`);
  return res.json();
}

export function imgSrc(url) {
  return `/api/images?url=${encodeURIComponent(url)}`;
}
