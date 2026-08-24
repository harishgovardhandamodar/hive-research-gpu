import { marked } from "marked";

marked.setOptions({ breaks: true, gfm: true });

export interface LoadedArtifact {
  path: string;
  kind: "markdown" | "image" | "raw" | "pdf";
  html?: string;
  rawUrl?: string;
}

/** Resolve a relative figure path against the note's folder. */
export function joinBase(baseDir: string, rel: string): string {
  const parts = baseDir ? baseDir.split("/") : [];
  for (const seg of rel.split("/")) {
    if (!seg || seg === ".") continue;
    if (seg === "..") parts.pop();
    else parts.push(seg);
  }
  return parts.join("/");
}

/** Point relative <img> sources at the authenticated raw-file proxy. */
function inlineImages(html: string, artifactPath: string): string {
  const baseDir = artifactPath.includes("/") ? artifactPath.slice(0, artifactPath.lastIndexOf("/")) : "";
  const doc = new DOMParser().parseFromString(html, "text/html");
  doc.querySelectorAll("img").forEach((img) => {
    const src = img.getAttribute("src") ?? "";
    if (/^(https?:|data:)/i.test(src)) return;
    const resolved = joinBase(baseDir, src.replace(/^\.?\//, ""));
    img.setAttribute("src", `/api/artifacts/raw?path=${encodeURIComponent(resolved)}`);
  });
  return doc.body.innerHTML;
}

function renderMarkdown(md: string): string {
  try {
    return marked.parse(md) as string;
  } catch {
    return `<pre>${md.replace(/</g, "&lt;")}</pre>`;
  }
}

export function extOf(path: string): string {
  const base = path.slice(path.lastIndexOf("/") + 1);
  const dot = base.lastIndexOf(".");
  return dot === -1 ? "" : base.slice(dot).toLowerCase();
}

export async function loadArtifact(
  path: string,
  view: string,
  fetchContent: (path: string) => Promise<{ content: string }>,
): Promise<LoadedArtifact> {
  if (view === "image") {
    return { path, kind: "image", rawUrl: `/api/artifacts/raw?path=${encodeURIComponent(path)}` };
  }
  if (view === "pdf") {
    return { path, kind: "pdf", rawUrl: `/api/artifacts/raw?path=${encodeURIComponent(path)}` };
  }
  if (view === "text") {
    const data = await fetchContent(path);
    return { path, kind: "markdown", html: inlineImages(renderMarkdown(data.content), path) };
  }
  return { path, kind: "raw", rawUrl: `/api/artifacts/raw?path=${encodeURIComponent(path)}` };
}
