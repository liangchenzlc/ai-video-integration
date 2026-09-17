import type { FormEvent } from "react";
import { Button, Input, Select } from "antd";

interface Props {
  busy: boolean;
  ready: boolean;
  pending: boolean;
  directory: string | null;
  name: string;
  aspect: "16:9" | "9:16";
  seconds: string;
  onName: (value: string) => void;
  onAspect: (value: "16:9" | "9:16") => void;
  onSeconds: (value: string) => void;
  onChoose: () => void;
  onQuery: () => void;
  onCancel: () => void;
  onSubmit: (event: FormEvent) => void;
}
export function ProjectCreateForm(props: Props) {
  const disabled = props.busy || !props.ready || props.pending;
  return (
    <form
      className="project-form project-create-form"
      onSubmit={props.onSubmit}
    >
      <fieldset disabled={disabled}>
        <label htmlFor="create-project-name">
          项目名称
          <Input
            id="create-project-name"
            autoFocus
            maxLength={120}
            required
            value={props.name}
            onChange={(e) => props.onName(e.target.value)}
            placeholder="例如：雨夜借光"
          />
        </label>
        <div className="form-row">
          <label htmlFor="create-project-aspect">
            画幅
            <Select
              id="create-project-aspect"
              disabled={disabled}
              value={props.aspect}
              onChange={props.onAspect}
              options={[
                { value: "16:9", label: "横屏 16:9" },
                { value: "9:16", label: "竖屏 9:16" },
              ]}
            />
          </label>
          <label htmlFor="create-project-seconds">
            目标时长（秒）
            <Input
              id="create-project-seconds"
              type="number"
              min="1"
              step="1"
              required
              value={props.seconds}
              onChange={(e) => props.onSeconds(e.target.value)}
            />
          </label>
        </div>
        <p>输出设置：1080p · 24 帧/秒</p>
        <div className="directory-choice">
          <Button onClick={props.onChoose}>选择空目录</Button>
          <span>{props.directory ?? "尚未选择目录"}</span>
        </div>
        <p className="muted">
          项目保存在你选择的本机目录，请避开网盘同步文件夹。
        </p>
      </fieldset>
      {props.pending && (
        <p role="status">
          正在核对这次新建的结果。重试沿用原操作，不会另建一个项目。
        </p>
      )}
      <div className="project-actions">
        <Button
          type="primary"
          htmlType="submit"
          disabled={
            props.busy || !props.ready || (!props.directory && !props.pending)
          }
        >
          {props.busy ? "请稍候…" : props.pending ? "重试原操作" : "创建项目"}
        </Button>
        {props.pending ? (
          <Button disabled={props.busy || !props.ready} onClick={props.onQuery}>
            查询原操作
          </Button>
        ) : (
          <Button disabled={props.busy} onClick={props.onCancel}>
            取消
          </Button>
        )}
      </div>
    </form>
  );
}
