import { useEffect, useState } from "react";
import type { z } from "zod";
import type { activitySchema } from "../../electron/shared/tasks";
export const taskLabels: Record<string, string> = {
  pending: "待继续",
  running: "执行中",
  complete: "已完成",
  partial: "部分完成",
  result_unknown: "结果未知，可能已计费",
  pending_download: "等待下载",
  failed: "未完成",
  prepared: "尚未提交",
  submitting: "提交中",
  succeeded: "已完成",
  cancelled: "服务商已确认取消",
};
export function TaskActivity({
  ready,
  runtimeId,
  onOpen,
}: {
  ready: boolean;
  runtimeId: string | null;
  onOpen: () => void;
}) {
  const [items, setItems] = useState<z.infer<typeof activitySchema>>([]);
  useEffect(() => {
    let active = true;
    const load = async () => {
      if (!ready) return;
      const result = await window.desktop.tasks.activity({});
      if (active && result.ok) setItems(result.data);
    };
    void load();
    const timer = setInterval(() => void load(), 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [ready, runtimeId]);
  if (!items.length) return null;
  return (
    <aside className="task-activity" aria-label="跨项目活动任务">
      <strong>活动与待核对任务</strong>
      <ul>
        {items.map((item) => (
          <li key={`${item.projectId}:${item.taskId}`}>
            {item.projectName} · {taskLabels[item.state]}
            <small>任务 {item.taskId}</small>
          </li>
        ))}
      </ul>
      <button onClick={onOpen}>打开项目工具核对</button>
    </aside>
  );
}
