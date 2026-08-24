import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Approval } from "../types";

export function ApprovalInbox({ onChanged }: { onChanged: () => void }) {
  const [items, setItems] = useState<Approval[]>([]);

  const refresh = useCallback(async () => {
    try {
      setItems(await api.pendingApprovals());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.type === "awaiting_approval") refresh();
    };
    window.addEventListener("ws-event", handler);
    return () => window.removeEventListener("ws-event", handler);
  }, [refresh]);

  const decide = async (id: string, approved: boolean) => {
    await api.decideApproval(id, approved);
    await refresh();
    onChanged();
  };

  return (
    <div className="panel">
      <h2>
        Approvals{" "}
        {items.length > 0 && <span className="badge">{items.length}</span>}
      </h2>
      {items.length === 0 && <p className="empty">Nothing waiting on you.</p>}
      {items.map((a) => (
        <div key={a.id} className="approval-card">
          <code>{a.tool}</code>
          {a.rationale && <p>{a.rationale}</p>}
          <pre className="args">{JSON.stringify(a.args)}</pre>
          <div className="composer-row">
            <button className="ok" onClick={() => void decide(a.id, true)}>
              approve
            </button>
            <button className="bad" onClick={() => void decide(a.id, false)}>
              reject
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
