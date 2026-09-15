import type { Writable } from "node:stream";
import {
  FRAME_LIMIT,
  WRITE_LIMIT,
  WRITE_TIMEOUT_MS,
  ProtocolError,
} from "./control-codec";

export class PipeWriter {
  #queue: Buffer[] = [];
  #bytes = 0;
  #busy = false;
  #callbackDone = false;
  #needsDrain = false;
  #currentBytes = 0;
  #closed = false;
  #timer: ReturnType<typeof setTimeout> | undefined;

  constructor(
    private readonly stream: Writable,
    private readonly onFailure: (error: ProtocolError) => void,
  ) {
    stream.on("error", this.#fail);
    stream.on("close", this.#onClose);
    stream.on("drain", this.#onDrain);
  }
  #onDrain = (): void => {
    this.#needsDrain = false;
    this.#complete();
  };
  #onClose = (): void => {
    if (this.#bytes) this.#fail();
    else this.close();
  };
  #fail = (): void => {
    if (this.#closed) return;
    this.close();
    this.onFailure(new ProtocolError());
  };
  #arm(): void {
    clearTimeout(this.#timer);
    this.#timer = setTimeout(this.#fail, WRITE_TIMEOUT_MS);
  }
  enqueue(frame: Buffer): void {
    if (this.#closed) throw new ProtocolError();
    if (
      !frame.length ||
      frame.at(-1) !== 10 ||
      frame.length > FRAME_LIMIT ||
      this.#bytes + frame.length > WRITE_LIMIT
    ) {
      this.#fail();
      throw new ProtocolError();
    }
    this.#queue.push(Buffer.from(frame));
    if (!this.#bytes) this.#arm();
    this.#bytes += frame.length;
    this.#pump();
  }
  #pump(): void {
    if (this.#closed || this.#busy || !this.#queue.length) return;
    const frame = this.#queue.shift()!;
    this.#busy = true;
    this.#callbackDone = false;
    this.#currentBytes = frame.length;
    try {
      this.#needsDrain = !this.stream.write(frame, (error?: Error | null) => {
        if (error) {
          this.#fail();
          return;
        }
        this.#callbackDone = true;
        this.#complete();
      });
    } catch {
      this.#fail();
    }
  }
  #complete(): void {
    if (this.#closed || !this.#busy || !this.#callbackDone || this.#needsDrain)
      return;
    this.#bytes -= this.#currentBytes;
    this.#currentBytes = 0;
    this.#busy = false;
    clearTimeout(this.#timer);
    if (this.#bytes) this.#arm();
    this.#pump();
  }
  close(): void {
    if (this.#closed) return;
    this.#closed = true;
    clearTimeout(this.#timer);
    this.#queue = [];
    this.#bytes = 0;
    this.stream.off("drain", this.#onDrain);
    this.stream.off("close", this.#onClose);
    // Keep a safe error sink until destroy finishes; no raw stream error escapes.
    this.stream.once("close", () => this.stream.off("error", this.#fail));
    this.stream.destroy();
  }
}
