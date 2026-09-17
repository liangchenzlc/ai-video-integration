import {
  addAsset,
  type EpisodeWorkflow,
} from "../../../features/projects/episode-workflow";

export function AssetControls({
  value,
  readOnly,
  onChange,
}: {
  value: EpisodeWorkflow;
  readOnly: boolean;
  onChange: (next: EpisodeWorkflow) => void;
}) {
  return (
    <div
      className="episode-stage-controls"
      role="group"
      aria-label="添加素材候选"
    >
      {(["character", "scene", "prop"] as const).map((kind, index) => (
        <button
          key={kind}
          type="button"
          disabled={readOnly}
          onClick={() => {
            if (!readOnly) onChange(addAsset(value, kind));
          }}
        >
          添加{["角色", "场景", "道具"][index]}
        </button>
      ))}
    </div>
  );
}
