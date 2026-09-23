export type LogLevel = "debug" | "info" | "warn" | "error";

const LEVEL_WEIGHT: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
};

type ViteEnv = {
  DEV?: boolean;
  VITE_LOG_LEVEL?: string;
};

function readLogLevel(): LogLevel {
  const env = (import.meta as { env?: ViteEnv }).env;
  const configured = env?.VITE_LOG_LEVEL;
  if (configured === "debug" || configured === "info" || configured === "warn" || configured === "error") {
    return configured;
  }
  return env?.DEV ? "debug" : "info";
}

const minimumLevel = readLogLevel();

export type LogContext = Record<string, unknown>;

export interface DiagnosticLogger {
  debug(message: string, context?: LogContext): void;
  info(message: string, context?: LogContext): void;
  warn(message: string, context?: LogContext): void;
  error(message: string, context?: LogContext): void;
}

function emit(level: LogLevel, scope: string, message: string, context?: LogContext): void {
  if (LEVEL_WEIGHT[level] < LEVEL_WEIGHT[minimumLevel]) return;
  const text = `[PatrolX][${scope}] ${message}`;
  const payload = context ?? {};
  if (level === "error") {
    console.error(text, payload);
    return;
  }
  if (level === "warn") {
    console.warn(text, payload);
    return;
  }
  if (level === "info") {
    console.info(text, payload);
    return;
  }
  console.debug(text, payload);
}

export function createLogger(scope: string): DiagnosticLogger {
  return {
    debug: (message, context) => emit("debug", scope, message, context),
    info: (message, context) => emit("info", scope, message, context),
    warn: (message, context) => emit("warn", scope, message, context),
    error: (message, context) => emit("error", scope, message, context),
  };
}
