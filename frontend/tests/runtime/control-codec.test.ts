import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  FrameDecoder,
  FrameEncoder,
  ProtocolError,
  type Direction,
  type Frame,
} from "../../electron/main/runtime/control-codec";

const root = new URL("../../../", import.meta.url);
const identity = ["22222222-2222-4222-8222-222222222222", 1] as const;
const examples = JSON.parse(
  readFileSync(
    fileURLToPath(
      new URL("docs/技术方案/契约/t01-control.examples.json", root),
    ),
    "utf8",
  ),
) as Record<Direction, Frame[]>;
const { vectors } = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("contracts/control-vectors.json", root)),
    "utf8",
  ),
) as {
  vectors: Array<{
    name: string;
    direction: Direction;
    wireHex: string;
    chunkSize: number;
    expected: Frame[] | null;
  }>;
};

describe("shared wire contracts", () => {
  for (const vector of vectors) {
    it(vector.name, () => {
      const decoder = new FrameDecoder(vector.direction, ...identity);
      const raw = Buffer.from(vector.wireHex, "hex");
      const decode = () => {
        const frames: Frame[] = [];
        for (let offset = 0; offset < raw.length; offset += vector.chunkSize) {
          frames.push(
            ...decoder.feed(raw.subarray(offset, offset + vector.chunkSize)),
          );
        }
        decoder.eof();
        return frames;
      };
      if (vector.expected === null) {
        expect(decode).toThrow(ProtocolError);
        expect(() => decoder.feed(Buffer.from("\n"))).toThrow(ProtocolError);
      } else {
        expect(decode()).toEqual(vector.expected);
      }
    });
  }
});

it("encodes each direction with independent contiguous sequence numbers", () => {
  for (const direction of [
    "mainToSupervisor",
    "supervisorToApi",
    "apiToSupervisor",
    "supervisorToMain",
  ] as const) {
    const encoder = new FrameEncoder(direction, ...identity);
    const decoder = new FrameDecoder(direction, ...identity);
    const received = examples[direction].flatMap((frame) =>
      decoder.feed(encoder.encode(frame.type, frame.payload)),
    );
    expect(received).toEqual(examples[direction]);
  }
});

it("errors never include peer input or schema validation details", () => {
  const encoder = new FrameEncoder("mainToSupervisor", ...identity);
  expect(() =>
    encoder.encode("init", { tokenB64Url: "SECRET_SENTINEL" }),
  ).toThrow(/^控制协议无效。$/);
});
