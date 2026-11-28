/** 云资源生命周期独立于 ComfyUI Runtime；没有经过确认的官方 API 时保持未支持。 */
export type CloudLifecycleAction = "start" | "stop" | "restart" | "release" | "query";

export interface CloudLifecycleAdapter {
  id: string;
  label: string;
  start(instanceId: string, signal?: AbortSignal): Promise<void>;
  stop(instanceId: string, signal?: AbortSignal): Promise<void>;
  restart(instanceId: string, signal?: AbortSignal): Promise<void>;
  release(instanceId: string, signal?: AbortSignal): Promise<void>;
  query(instanceId: string, signal?: AbortSignal): Promise<Record<string, unknown>>;
}

const adapters = new Map<string, CloudLifecycleAdapter>();

export function registerCloudLifecycleAdapter(adapter: CloudLifecycleAdapter) {
  if (adapters.has(adapter.id)) throw new Error(`云生命周期适配器已注册：${adapter.id}`);
  adapters.set(adapter.id, adapter);
}

export function getCloudLifecycleAdapter(id: string) {
  return adapters.get(id);
}

export function listCloudLifecycleAdapters() {
  return [...adapters.values()].map(adapter => ({ id: adapter.id, label: adapter.label }));
}