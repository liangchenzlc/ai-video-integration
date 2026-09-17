import { useState } from "react";
import type { AssetKind } from "../../features/assets/asset-model";

export type MainPage = "projects" | "assets" | "ai";
export function Sidebar({
  page,
  kind,
  onSelect,
}: {
  page: MainPage;
  kind: AssetKind;
  onSelect: (page: MainPage, kind?: AssetKind) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <aside className="studio-sidebar">
      <div className="studio-brand">
        <span className="studio-brand-mark" aria-hidden="true">
          ▣
        </span>
        <span>
          短剧工作台<small>本地创作空间</small>
        </span>
      </div>
      <nav aria-label="主导航">
        <button
          className={page === "projects" ? "studio-nav active" : "studio-nav"}
          onClick={() => {
            setExpanded(false);
            onSelect("projects");
          }}
          aria-current={page === "projects" ? "page" : undefined}
        >
          项目管理
        </button>
        <button
          type="button"
          className={
            page === "assets"
              ? "studio-nav studio-nav-assets active"
              : "studio-nav studio-nav-assets"
          }
          aria-controls="asset-subnav"
          aria-expanded={expanded}
          onClick={() => {
            if (!expanded) onSelect("assets", kind);
            setExpanded(!expanded);
          }}
        >
          素材库
          <span
            className={expanded ? "chevron expanded" : "chevron"}
            aria-hidden="true"
          />
        </button>
        <div id="asset-subnav" className="studio-subnav" hidden={!expanded}>
          {(
            [
              ["character", "角色"],
              ["scene", "场景"],
              ["prop", "道具"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              className={
                page === "assets" && kind === value
                  ? "studio-subnav-item active"
                  : "studio-subnav-item"
              }
              onClick={() => onSelect("assets", value)}
              aria-current={
                page === "assets" && kind === value ? "page" : undefined
              }
            >
              {label}
            </button>
          ))}
        </div>
        <button
          className={page === "ai" ? "studio-nav active" : "studio-nav"}
          onClick={() => {
            setExpanded(false);
            onSelect("ai");
          }}
          aria-current={page === "ai" ? "page" : undefined}
        >
          AI 配置
        </button>
      </nav>
      <p className="studio-sidebar-foot">项目文件留在本机</p>
    </aside>
  );
}
