import { useCallback, useEffect, useState } from "react";
import { marked } from "marked";
import { api } from "../api";
import type { ArtifactGroup } from "../types";

interface Loaded {
  path: string;
  content: string;
}

marked.setOptions({ breaks: true, gfm: true });

function renderMarkdown(md: string): string {
  try {
    return marked.parse(md) as string;
  } catch {
    return `<pre>${md.replace(/</g, "&lt;")}</pre>`;
  }
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
export function inlineImages(html: string, artifactPath: string): string {
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

export function ArtifactsPanel() {
  const [groups, setGroups] = useState<ArtifactGroup[]>([]);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await api.artifacts();
      setGroups(data.groups);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15000);
    return () => clearInterval(t);
  }, [refresh]);

  const open = async (path: string) => {
    setBusy(true);
    try {
      const data = await api.artifactContent(path);
      const html = inlineImages(renderMarkdown(data.content), path);
      setLoaded({ path, content: html });
    } catch (err) {
      setLoaded({ path, content: `<pre>Could not load artifact: ${err instanceof Error ? err.message : String(err)}</pre>` });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h2>Artifacts</h2>
      {groups.map((g) =>
        g.total === 0 ? null : (
          <div key={g.id} className="artifact-group">
            <p className="artifact-label">
              {g.label} <span className="badge">{g.total}</span>
            </p>
            <ul className="artifact-list">
              {g.files.slice(0, 8).map((f) => (
                <li key={f.path}>
                  <button className="artifact-file" onClick={() => void open(f.path)} title={f.path}>
                    {f.name}
                  </button>
                </li>
              ))}
              {g.files.length > 8 && (
                <li className="artifact-more">+{g.files.length - 8} more</li>
              )}
            </ul>
          </div>
        ),
      )}
      {groups.every((g) => g.total === 0) && (
        <p className="empty">
          No artifacts yet. Approved surveys and digests land here as files in your vault.
        </p>
      )}
      {busy && <p className="typing">loading artifact…</p>}
      {loaded && (
        <div className="artifact-modal" onClick={() => setLoaded(null)}>
          <div className="artifact-box" onClick={(e) => e.stopPropagation()}>
            <div className="artifact-head">
              <code>{loaded.path}</code>
              <button onClick={() => setLoaded(null)}>close</button>
            </div>
            <div
              className="artifact-body md-body"
              dangerouslySetInnerHTML={{ __html: loaded.content }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
