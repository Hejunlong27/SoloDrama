import { SoloDrama } from "./solodrama";
import type { Channel } from "./types";

const channels = new Map<string, Channel>([["solodrama", new SoloDrama()]]);

export function getChannel(): Channel {
  const source = channels.get(process.env.SOLODRAMA_CHANNEL?.trim() || "solodrama");
  if (!source) throw Object.assign(new Error("渠道未配置，请检查 SOLODRAMA_CHANNEL"), { status: 503 });
  return source;
}
