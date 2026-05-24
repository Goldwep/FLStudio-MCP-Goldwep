type Level = "debug" | "info" | "warn" | "error";

function emit(level: Level, msg: string, meta?: unknown): void {
  const line =
    meta === undefined ? `[${level}] ${msg}` : `[${level}] ${msg} ${JSON.stringify(meta)}`;
  process.stderr.write(line + "\n");
}

export const logger = {
  debug: (msg: string, meta?: unknown) => emit("debug", msg, meta),
  info: (msg: string, meta?: unknown) => emit("info", msg, meta),
  warn: (msg: string, meta?: unknown) => emit("warn", msg, meta),
  error: (msg: string, meta?: unknown) => emit("error", msg, meta),
};
