import { serviceLabels, type AiConfig } from "./config-model";

export function ConfigTable({
  items,
  onEdit,
  onDelete,
}: {
  items: AiConfig[];
  onEdit: (item: AiConfig) => void;
  onDelete: (id: string) => void;
}) {
  if (!items.length)
    return (
      <div className="studio-empty">
        <h2>还没有 AI 配置</h2>
        <p>可以先添加服务类型和模型信息，供界面预览。</p>
      </div>
    );
  return (
    <div className="config-table-wrap">
      <table className="config-table">
        <thead>
          <tr>
            <th>名称</th>
            <th>提供商</th>
            <th>Base URL</th>
            <th>默认模型</th>
            <th>类型</th>
            <th>默认</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td className="config-name">{item.name}</td>
              <td>{item.provider}</td>
              <td className="config-url" title={item.baseUrl}>
                {item.baseUrl || "—"}
              </td>
              <td>{item.defaultModel || "—"}</td>
              <td>
                <span className="service-tag">
                  {serviceLabels[item.serviceType]}
                </span>
              </td>
              <td>{item.isDefault ? "是" : "—"}</td>
              <td>
                <div className="config-actions">
                  <button onClick={() => onEdit(item)}>编辑</button>
                  <button onClick={() => onDelete(item.id)}>删除</button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
