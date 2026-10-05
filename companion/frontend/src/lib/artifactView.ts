import { marked } from "marked";

marked.setOptions({ breaks: true, gfm: true });

// Marked passes raw HTML through, so anything it renders is sanitized before it
// reaches dangerouslySetInnerHTML -- chat answers and notes both flow through
// here, and a model that emits <script> or an onerror= attribute must not get
// one executed in the app's origin.
const BLOCKED_TAGS = new Set([
  "SCRIPT", "IFRAME", "OBJECT", "EMBED", "FORM", "LINK", "STYLE", "META", "BASE",
]);

export function sanitizeHtml(html: string): string {
  const doc = new DOMParser().parseFromString(html, "text/html");
  doc.body.querySelectorAll("*").forEach((el) => {
    if (BLOCKED_TAGS.has(el.tagName)) {
      el.remove();
      return;
    }
    Array.from(el.attributes).forEach((attr) => {
      const name = attr.name.toLowerCase();
      if (name.startsWith("on")) {
        el.removeAttribute(attr.name);
      } else if ((name === "href" || name === "src") && /^\s*javascript:/i.test(attr.value)) {
        el.removeAttribute(attr.name);
      }
    });
  });
  return doc.body.innerHTML;
}

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

/** Markdown -> sanitized HTML. Used by the artifact viewer and the chat log. */
export function renderMarkdown(md: string): string {
  try {
    return sanitizeHtml(marked.parse(md || "") as string);
  } catch {
    return `<pre>${(md || "").replace(/</g, "&lt;")}</pre>`;
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
