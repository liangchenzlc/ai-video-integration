import { Writable } from "node:stream";
import { afterEach, expect, it, vi } from "vitest";
import {
  FRAME_LIMIT,
  ProtocolError,
} from "../../electron/main/runtime/control-codec";
import { PipeWriter } from "../../electron/main/runtime/pipe-writer";

afterEach(() => vi.useRealTimers());

it("preserves order through actual Writable backpressure", async () => {
  const output: Buffer[] = [];
  const stream = new Writable({
    highWaterMark: 1,
    write(chunk, _encoding, callback) {
      output.push(Buffer.from(chunk));
      setImmediate(callback);
    },
  });
  const failure = vi.fn();
  const writer = new PipeWriter(stream, failure);
  try {
    writer.enqueue(Buffer.from("first\n"));
    writer.enqueue(Buffer.from("second\n"));
    await vi.waitFor(() =>
      expect(Buffer.concat(output).toString()).toBe("first\nsecond\n"),
    );
    expect(failure).not.toHaveBeenCalled();
  } finally {
    writer.close();
  }
});

it("counts in-flight data against the 64 KiB queue bound", () => {
  const stream = new Writable({ write() {} });
  const failure = vi.fn();
  const writer = new PipeWriter(stream, failure);
  const frame = Buffer.alloc(FRAME_LIMIT, 120);
  frame[FRAME_LIMIT - 1] = 10;
  for (let i = 0; i < 4; i++) writer.enqueue(frame);
  expect(() => writer.enqueue(Buffer.from("extra\n"))).toThrow(ProtocolError);
  expect(stream.destroyed).toBe(true);
  expect(failure).toHaveBeenCalledExactlyOnceWith(expect.any(ProtocolError));
});

it("fails a stuck pipe once at two seconds", () => {
  vi.useFakeTimers();
  const stream = new Writable({ write() {} });
  const failure = vi.fn();
  const writer = new PipeWriter(stream, failure);
  writer.enqueue(Buffer.from("SECRET_SENTINEL\n"));
  vi.advanceTimersByTime(1999);
  expect(failure).not.toHaveBeenCalled();
  vi.advanceTimersByTime(1);
  expect(failure).toHaveBeenCalledExactlyOnceWith(
    expect.objectContaining({ message: "控制协议无效。" }),
  );
  vi.advanceTimersByTime(2000);
  expect(failure).toHaveBeenCalledTimes(1);
  expect(stream.destroyed).toBe(true);
});

it("sanitizes stream errors", async () => {
  const stream = new Writable({
    write(_chunk, _encoding, callback) {
      callback(new Error("SECRET_SENTINEL"));
    },
  });
  const failure = vi.fn();
  const writer = new PipeWriter(stream, failure);
  writer.enqueue(Buffer.from("frame\n"));
  await vi.waitFor(() => expect(failure).toHaveBeenCalledTimes(1));
  expect(String(failure.mock.calls[0][0])).not.toContain("SECRET_SENTINEL");
});
