import { toast } from "sonner";
import { fetchUserinfoForUnifiedService } from "@/api/rdUnifiedService";
import type { Product } from "@/components/product/types";
import { IS_TAURI } from "@/platform";

export const OWNER_GUARD_MISSING_LOCAL = "owner_guard_missing_local";
export const OWNER_GUARD_MISSING_PRODUCT = "owner_guard_missing_product";
export const OWNER_GUARD_MISMATCH = "owner_guard_mismatch";

/**
 * 校验本机 `data/userinfo.encryption`（经 Synapse `/api/dev/userinfo-for-unified-service` 返回的 `owner_info` 密文）
 * 是否与产品在研发统一服务中记录的 `owner_info` 一致。
 */
export async function assertOwnerInfoMatchesProduct(
  synapseApiBase: string,
  product: Product,
): Promise<void> {
  let localRaw: string | undefined;
  try {
    const row = await fetchUserinfoForUnifiedService(synapseApiBase);
    localRaw = row.owner_info;
  } catch {
    throw new Error(OWNER_GUARD_MISSING_LOCAL);
  }
  const local = (localRaw ?? "").trim();
  const stored = (product.ownerInfo ?? "").trim();
  if (!local) {
    throw new Error(OWNER_GUARD_MISSING_LOCAL);
  }
  if (!stored) {
    throw new Error(OWNER_GUARD_MISSING_PRODUCT);
  }
  if (local !== stored) {
    throw new Error(OWNER_GUARD_MISMATCH);
  }
}

/**
 * 浏览器预览模式下视为负责人；Tauri 下与 assertOwnerInfoMatchesProduct 一致但不抛错。
 */
export async function isCurrentUserProductOwner(
  synapseApiBase: string,
  product: Product,
): Promise<boolean> {
  if (!IS_TAURI) return true;
  try {
    await assertOwnerInfoMatchesProduct(synapseApiBase, product);
    return true;
  } catch {
    return false;
  }
}

type TKey = (key: string) => string;

export function toastOwnerInfoGuardError(t: TKey, err: unknown): void {
  const msg = err instanceof Error ? err.message : "";
  if (msg === OWNER_GUARD_MISSING_LOCAL) {
    toast.error(t("workbench.products.ownerInfoGuardMissingLocal"));
  } else if (msg === OWNER_GUARD_MISSING_PRODUCT) {
    toast.error(t("workbench.products.ownerInfoGuardMissingProduct"));
  } else if (msg === OWNER_GUARD_MISMATCH) {
    toast.error(t("workbench.products.ownerInfoGuardMismatch"));
  } else {
    toast.error(msg || t("workbench.products.ownerInfoGuardMismatch"));
  }
}
