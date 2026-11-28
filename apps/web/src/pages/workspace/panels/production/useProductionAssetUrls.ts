import { onScopeDispose, ref, toValue, watch, type MaybeRefOrGetter } from "vue";
import type { ProductionAsset } from "@solodrama/production";
import useWorkspaceFiles from "@/lib/workspaceFiles";

export function useProductionAssetUrls(directory: MaybeRefOrGetter<string>, assets: MaybeRefOrGetter<ProductionAsset[]>) {
  const files = useWorkspaceFiles(directory);
  const assetUrls = ref<Record<string, string>>({});
  const releases = new Map<string, () => void>();
  function releaseAll() {
    for (const release of releases.values()) release();
    releases.clear();
    assetUrls.value = {};
  }
  async function load(items: ProductionAsset[]) {
    releaseAll();
    await Promise.all(items.filter(asset => asset.type === "image").map(async asset => {
      const shared = files.acquireUrl(asset.path, asset.mimeType);
      releases.set(asset.id, shared.release);
      try { assetUrls.value[asset.id] = await shared.url; }
      catch {
        shared.release();
        releases.delete(asset.id);
        delete assetUrls.value[asset.id];
      }
    }));
  }
  watch(() => toValue(assets).map(asset => `${asset.id}:${asset.path}:${asset.mimeType}`).join("|"), () => { void load(toValue(assets)); }, { immediate: true });
  onScopeDispose(releaseAll);
  return { assetUrls };
}