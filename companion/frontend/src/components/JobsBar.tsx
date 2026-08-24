import { useCallback, useEffect, useState } from "react";
import { req } from "../api";

interface FoxJob {
  id: string;
  status: string;
  stage: string;
  progress: number;
}

interface StatusSnapshot {
  hive_ok: boolean;
  plans_running: number;
  approvals_pending: number;
  suggestions_open: number;
  hive_jobs: { label: string; status: string }[];
  fox_jobs: FoxJob[];
  episodes: number;
  last_scan: string | null;
}

export function JobsBar() {
  const [snap, setSnap] = useState<StatusSnapshot | null>(null);

  const refresh = useCallback(async () => {
    try {
      setSnap(await req<StatusSnapshot>("/api/statusbar"));
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  const scanAgo = snap?.last_scan
    ? Math.max(1, Math.round((Date.now() - new Date(snap.last_scan).getTime()) / 60000))
    : null;

  return (
    <footer className="jobsbar">
      <div className="jb-group">
        <span className={snap?.hive_ok ? "dot ok" : "dot bad"}>hive</span>
        <span className="jb-item" title="goals currently executing">
          ▶ {snap?.plans_running ?? 0} plans
        </span>
        {(snap?.approvals_pending ?? 0) > 0 && (
          <span className="jb-item jb-warn" title="mutations waiting for your decision">
            ⏸ {snap?.approvals_pending} approval{snap && snap.approvals_pending > 1 ? "s" : ""}
          </span>
        )}
        <span className="jb-item" title="open proactive suggestions">
          ◆ {snap?.suggestions_open ?? 0} suggestions
        </span>
      </div>
      <div className="jb-group jb-center">
        {(snap?.fox_jobs ?? []).map((j) => (
          <span key={j.id} className="jb-job" title={`survey ${j.id} — ${j.stage} (${Math.round((j.progress ?? 0) * 100)}%)`}>
            📝 survey · {j.stage || j.status} · {Math.round((j.progress ?? 0) * 100)}%
          </span>
        ))}
        {(snap?.hive_jobs ?? []).map((j, i) => (
          <span key={i} className="jb-job" title={j.label}>
            ⚙ {String(j.label).slice(0, 40)}
          </span>
        ))}
        {snap && snap.fox_jobs.length === 0 && snap.hive_jobs.length === 0 && (
          <span className="jb-idle">no background jobs</span>
        )}
      </div>
      <div className="jb-group">
        <span className="stat" title="episodic memory records">{snap?.episodes ?? 0} episodes</span>
        <span className="stat" title="last proactive signal scan">
          scanned {scanAgo !== null ? `${scanAgo}m ago` : "—"}
        </span>
      </div>
    </footer>
  );
}
