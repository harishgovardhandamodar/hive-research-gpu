import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { usePolling } from "../hooks/usePolling";
import { ArgsView } from "./ui";
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

  usePolling(refresh, 4000);

  // instant refresh when a step pauses for approval (App dispatches this on
  // every plan event — the old "ws-event" listener here never fired because
  // nothing published that event)
  useEffect(() => {
    const handler = () => setTimeout(refresh, 300);
    window.addEventListener("plans-changed", handler);
    return () => window.removeEventListener("plans-changed", handler);
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
          <ArgsView args={a.args} />
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
