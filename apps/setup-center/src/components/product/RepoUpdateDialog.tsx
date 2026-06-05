import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Plus, Trash2 } from "lucide-react";
import {
  Product,
  Repository,
  displayIdPipeName,
  defaultProdBranchForAppModuleSelection,
  filterAppModuleOptionsForRow,
  filterProdBranchOptionsForRow,
  findRepositoryMissingTokenIndex,
  isValidRepoBranchComposite,
  patchRepositoryRepoBranchFromModuleDetail,
  productRepositoriesToRdRepoInfo,
  prodBranchRowsToOptions,
  repositoriesToValidateTokenItems,
} from "./types";
import { SearchableVirtualSelect, type SearchableOption } from "./SearchableVirtualSelect";
import { RepoBranchDerivedDisplay } from "./RepoBranchDerivedDisplay";
import { parseCompositeLeadingId, parseProjectIdFromSpaceValue } from "./ProductModal";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { IS_TAURI } from "@/platform";
import {
  changeRepoInfo,
  fetchIwhalecloudUserinfoSummary,
  fetchModuleNameList,
  fetchProductBranchList,
  fetchRepoDetailByProdBranch,
  getProdProcessInfo,
  repoDetailFetchCacheKey,
  validateRepoTokens,
} from "@/api/rdUnifiedService";
import type {
  ProdProcessDataPayload,
  RdModuleNameItem,
  RdRepoDetailRow,
} from "@/api/rdUnifiedService";
import { assertOwnerInfoMatchesProduct, toastOwnerInfoGuardError } from "@/utils/ownerInfoGuard";

function moduleRowToOption(row: RdModuleNameItem): SearchableOption {
  const id = row.productModuleId ?? "";
  const name = (row.moduleChName ?? "").trim() || String(id);
  const value = `${id}|${name}`;
  return { label: value, value };
}

export type RepoUpdateDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  product: Product | null;
  synapseApiBase: string;
  onSuccess: (productId: string, repositories: Repository[], process?: ProdProcessDataPayload | null) => void;
  onBusyChange?: (busy: boolean) => void;
};

/** 带稳定 key；服务端已有仓库 branchLocked=true，新增行可填分支 */
type RepoEditRow = Repository & {
  clientKey: string;
  branchLocked: boolean;
};

let keySeq = 0;
function nextKey(prefix: string): string {
  keySeq += 1;
  return `${prefix}-${Date.now()}-${keySeq}`;
}

function fromProductRepos(repos: Repository[]): RepoEditRow[] {
  return repos.map((r, i) => ({
    ...r,
    clientKey: nextKey(`s-${i}`),
    branchLocked: true,
  }));
}

function toRepository(r: RepoEditRow): Repository {
  const { clientKey: _k, branchLocked: _b, ...rest } = r;
  return rest;
}

function toRepositories(rows: RepoEditRow[]): Repository[] {
  return rows.map(toRepository);
}

export function RepoUpdateDialog({
  open,
  onOpenChange,
  product,
  synapseApiBase,
  onSuccess,
  onBusyChange,
}: RepoUpdateDialogProps) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<RepoEditRow[]>([]);
  const [saving, setSaving] = useState(false);
  const [repoDetailByProdBranchVid, setRepoDetailByProdBranchVid] = useState<
    Record<string, RdRepoDetailRow[]>
  >({});
  const [repoDetailLoadingVid, setRepoDetailLoadingVid] = useState<Record<string, boolean>>({});
  const repoDetailFetchStartedRef = useRef<Set<string>>(new Set());
  const [appModuleOptions, setAppModuleOptions] = useState<SearchableOption[]>([]);
  const [appModuleRows, setAppModuleRows] = useState<RdModuleNameItem[]>([]);
  const [modulesLoading, setModulesLoading] = useState(false);
  const [prodBranchOptions, setProdBranchOptions] = useState<SearchableOption[]>([]);
  const [prodBranchLoading, setProdBranchLoading] = useState(false);
  /** 研发云 userinfo.access_token，新增仓库行时预填 repo.token（用户可改） */
  const [defaultRepoAccessToken, setDefaultRepoAccessToken] = useState("");

  useEffect(() => {
    if (!open) {
      setRepoDetailByProdBranchVid({});
      setRepoDetailLoadingVid({});
      repoDetailFetchStartedRef.current = new Set();
      setDefaultRepoAccessToken("");
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      try {
        const summary = await fetchIwhalecloudUserinfoSummary(synapseApiBase);
        if (!cancelled) {
          setDefaultRepoAccessToken((summary.access_token || "").trim());
        }
      } catch {
        if (!cancelled) setDefaultRepoAccessToken("");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, synapseApiBase]);

  useEffect(() => {
    if (open && product) {
      setRows(fromProductRepos(product.repositories));
    }
  }, [open, product]);

  useEffect(() => {
    if (!open || !product) return;
    const pid = parseProjectIdFromSpaceValue(product.space ?? "");
    const vid = parseCompositeLeadingId(product.version ?? "");
    if (pid == null || vid == null) {
      setAppModuleOptions([]);
      setAppModuleRows([]);
      setModulesLoading(false);
      return;
    }
    let cancelled = false;
    setModulesLoading(true);
    fetchModuleNameList(synapseApiBase, pid, vid)
      .then((rows) => {
        if (!cancelled) {
          setAppModuleRows(rows);
          setAppModuleOptions(rows.map(moduleRowToOption));
        }
      })
      .catch((e) => {
        if (cancelled) return;
        console.error(e);
        setAppModuleOptions([]);
        setAppModuleRows([]);
        toast.error(t("workbench.products.modal.moduleLoadFailed"));
      })
      .finally(() => {
        if (!cancelled) setModulesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, product, product?.space, product?.version, synapseApiBase, t]);

  useEffect(() => {
    if (!open || !product) return;
    const vid = parseCompositeLeadingId(product.version ?? "");
    if (vid == null) {
      setProdBranchOptions([]);
      setProdBranchLoading(false);
      return;
    }
    let cancelled = false;
    setProdBranchLoading(true);
    fetchProductBranchList(synapseApiBase, vid)
      .then((rows) => {
        if (!cancelled) setProdBranchOptions(prodBranchRowsToOptions(rows));
      })
      .catch((e) => {
        if (cancelled) return;
        console.error(e);
        setProdBranchOptions([]);
        toast.error(t("workbench.products.modal.prodBranchLoadFailed"));
      })
      .finally(() => {
        if (!cancelled) setProdBranchLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, product, product?.version, synapseApiBase, t]);

  /** 各产品分支版本 ID 对应的仓库明细（选仓库分支、填 repoUrl） */
  useEffect(() => {
    if (!open || !product) return;
    const projectId = parseProjectIdFromSpaceValue(product.space ?? "");
    if (projectId == null) return;

    const fetchKeys = [
      ...new Set(
        rows
          .map((r) => repoDetailFetchCacheKey(r.prodBranch ?? "", r.repoModule ?? ""))
          .filter((x): x is string => x != null),
      ),
    ];

    for (const key of fetchKeys) {
      if (repoDetailFetchStartedRef.current.has(key)) continue;
      const sep = key.indexOf("|");
      const vid = Number(key.slice(0, sep));
      const moduleId = Number(key.slice(sep + 1));
      if (!Number.isFinite(vid) || !Number.isFinite(moduleId)) continue;
      repoDetailFetchStartedRef.current.add(key);
      setRepoDetailLoadingVid((m) => ({ ...m, [key]: true }));
      fetchRepoDetailByProdBranch(synapseApiBase, vid, projectId, moduleId)
        .then((list) => {
          setRepoDetailByProdBranchVid((prev) => ({ ...prev, [key]: list }));
        })
        .catch((e) => {
          console.error(e);
          repoDetailFetchStartedRef.current.delete(key);
          setRepoDetailByProdBranchVid((prev) => ({ ...prev, [key]: [] }));
          toast.error(t("workbench.products.modal.repoBranchDetailLoadFailed"));
        })
        .finally(() => {
          setRepoDetailLoadingVid((m) => ({ ...m, [key]: false }));
        });
    }
  }, [open, product, rows, synapseApiBase, t]);

  /** 仓库明细返回后按 moduleName 自动填充新行的仓库分支与 URL */
  useEffect(() => {
    if (!open || !product) return;
    setRows((prev) => {
      let changed = false;
      const next = prev.map((repo) => {
        if (repo.branchLocked) return repo;
        const key = repoDetailFetchCacheKey(repo.prodBranch ?? "", repo.repoModule ?? "");
        if (key == null) return repo;
        if (repoDetailLoadingVid[key]) return repo;
        const list = repoDetailByProdBranchVid[key];
        if (!list?.length) return repo;
        const patched = patchRepositoryRepoBranchFromModuleDetail(repo, list);
        if (patched !== repo) changed = true;
        return patched;
      });
      return changed ? next : prev;
    });
  }, [open, product, repoDetailByProdBranchVid, repoDetailLoadingVid, rows]);

  const repoModuleSelectDisabled =
    parseProjectIdFromSpaceValue(product?.space ?? "") == null ||
    parseCompositeLeadingId(product?.version ?? "") == null;

  const updateRow = (index: number, patch: Partial<Repository>) => {
    setRows((prev) => {
      const next = prev.map((r) => ({ ...r }));
      if (patch.isMain === true) {
        for (let i = 0; i < next.length; i++) {
          next[i] = { ...next[i], isMain: i === index };
        }
      } else {
        next[index] = { ...next[index], ...patch };
      }
      return next;
    });
  };

  const handleRepoModuleSelect = (index: number, v: string) => {
    const defaultPb = defaultProdBranchForAppModuleSelection(v, appModuleRows);
    updateRow(index, { repoModule: v, prodBranch: defaultPb, branch: "", url: "" });
  };

  const handleProdBranchSelect = (index: number, v: string) => {
    updateRow(index, { prodBranch: v, branch: "", url: "" });
  };

  const addRow = () => {
    setRows((prev) => {
      const isFirst = prev.length === 0;
      const row: RepoEditRow = {
        url: "",
        branch: "",
        repoModule: "",
        purpose: "",
        token: defaultRepoAccessToken || "",
        codePath: "",
        isMain: isFirst,
        prodBranch: "",
        clientKey: nextKey("n"),
        branchLocked: false,
      };
      return [...prev, row];
    });
  };

  const removeRow = (index: number) => {
    setRows((prev) => {
      const removed = prev[index];
      const next = prev.filter((_, i) => i !== index);
      if (removed.isMain && next.length > 0) {
        next[0] = { ...next[0], isMain: true };
      }
      return next;
    });
  };

  const handleSave = async () => {
    if (!product || !IS_TAURI) return;
    try {
      await assertOwnerInfoMatchesProduct(synapseApiBase, product);
    } catch (e) {
      toastOwnerInfoGuardError(t, e);
      return;
    }
    const plain = toRepositories(rows);
    if (plain.length > 0) {
      const mains = plain.filter((r) => r.isMain);
      if (mains.length === 0) {
        toast.error(t("workbench.products.modal.mainRepoErrorNone"));
        return;
      }
      if (mains.length > 1) {
        toast.error(t("workbench.products.modal.mainRepoErrorMany"));
        return;
      }
      const incomplete = rows.some((r) => {
        if (!r.url.trim() || !r.branch.trim()) return true;
        if (!r.branchLocked) {
          const pb = r.prodBranch?.trim() ?? "";
          if (!pb || parseCompositeLeadingId(pb) == null) return true;
          const rm = r.repoModule?.trim() ?? "";
          if (!rm || parseCompositeLeadingId(rm) == null) return true;
          if (!isValidRepoBranchComposite(r.branch)) return true;
        }
        return false;
      });
      if (incomplete) {
        toast.error(t("workbench.products.repoUpdateDialog.incompleteRepo"));
        return;
      }
      const rmVals = rows.map((r) => r.repoModule?.trim() ?? "").filter(Boolean);
      if (new Set(rmVals).size !== rmVals.length) {
        toast.error(t("workbench.products.modal.repoModuleDuplicate"));
        return;
      }
      // const pbVals = rows.map((r) => r.prodBranch?.trim() ?? "").filter(Boolean);
      // if (new Set(pbVals).size !== pbVals.length) {
      //   toast.error(t("workbench.products.modal.prodBranchDuplicate"));
      //   return;
      // }
      const missingTokenIdx = findRepositoryMissingTokenIndex(plain);
      if (missingTokenIdx >= 0) {
        toast.error(t("workbench.products.modal.repoTokenRequired"));
        return;
      }
    }

    setSaving(true);
    onBusyChange?.(true);
    try {
      if (plain.length > 0) {
        const results = await validateRepoTokens(
          synapseApiBase,
          repositoriesToValidateTokenItems(plain),
        );
        const failIdx = results.findIndex((r) => !r.valid);
        if (failIdx >= 0) {
          toast.error(
            t("workbench.products.modal.repoTokenInvalid", {
              n: failIdx + 1,
              detail: results[failIdx]?.error || "",
            }),
          );
          return;
        }
      }
      const temp: Product = { ...product, repositories: plain };
      await changeRepoInfo(synapseApiBase, {
        prod: product.name.trim(),
        repo_info: productRepositoriesToRdRepoInfo(temp),
      });
      toast.success(t("workbench.products.changeRepoSuccess"));
      let process: ProdProcessDataPayload | null = null;
      try {
        const resp = await getProdProcessInfo(synapseApiBase, { prod: product.name.trim() });
        process = resp.data;
      } catch {
        /* optional */
      }
      onSuccess(product.id, plain.map((r) => ({ ...r })), process);
      onOpenChange(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg === "missing_devservice_ip") {
        toast.error(t("workbench.products.createMissingDevservice"));
      } else {
        toast.error(t("workbench.products.changeRepoFailed", { message: msg }));
      }
    } finally {
      setSaving(false);
      onBusyChange?.(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[800px] max-h-[85vh] flex flex-col gap-0 p-0">
        <DialogHeader className="px-6 py-4 border-b border-border/60">
          <DialogTitle>{t("workbench.products.repoUpdateDialog.title")}</DialogTitle>
          <p className="text-sm text-muted-foreground m-0 pt-1">{t("workbench.products.repoUpdateDialog.desc")}</p>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4 custom-scrollbar">
          <div className="flex justify-end">
            <Button type="button" variant="outline" size="sm" onClick={addRow} disabled={saving}>
              <Plus size={14} className="mr-1.5" />
              {t("workbench.products.repoUpdateDialog.addRepo")}
            </Button>
          </div>

          {rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("workbench.products.repoUpdateDialog.empty")}</p>
          ) : (
            rows.map((repo, index) => {
              const rbVidKey =
                repoDetailFetchCacheKey(repo.prodBranch ?? "", repo.repoModule ?? "") ?? "";
              const repoBranchLoading =
                !repo.branchLocked &&
                rbVidKey !== "" &&
                !!(repo.repoModule?.trim()) &&
                !!repoDetailLoadingVid[rbVidKey];

              return (
              <div
                key={repo.clientKey}
                className="rounded-lg border border-border/80 bg-muted/10 p-4 space-y-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">
                    {t("workbench.products.modal.repoConfigN", { n: index + 1 })}
                  </span>
                  <div className="flex items-center gap-2">
                    {repo.isMain && (
                      <Badge variant="secondary" className="text-[10px] font-normal bg-blue-500/10 text-blue-700 dark:text-blue-400">
                        {t("workbench.products.modal.mainRepo")}
                      </Badge>
                    )}
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-destructive hover:text-destructive"
                      disabled={saving}
                      onClick={() => removeRow(index)}
                      title={t("workbench.products.repoUpdateDialog.removeRepo")}
                    >
                      <Trash2 size={14} />
                    </Button>
                  </div>
                </div>

                <div className="grid grid-cols-12 gap-3">
                  <div className="col-span-12 space-y-1.5">
                    <Label className="text-xs">
                      {t("workbench.products.modal.appModule")}
                      {!repo.branchLocked ? " *" : ""}
                    </Label>
                    {repo.branchLocked ? (
                      <Input
                        readOnly
                        tabIndex={-1}
                        className="h-9 text-xs bg-muted/50 cursor-default"
                        value={repo.repoModule?.trim() ? displayIdPipeName(repo.repoModule) : "—"}
                      />
                    ) : (
                      <SearchableVirtualSelect
                        value={repo.repoModule ?? ""}
                        onValueChange={(v) => handleRepoModuleSelect(index, v)}
                        options={filterAppModuleOptionsForRow(
                          appModuleOptions,
                          rows,
                          index,
                          repo.repoModule ?? "",
                        )}
                        placeholder={t("workbench.products.modal.appModulePlaceholder")}
                        searchPlaceholder={t("workbench.products.modal.searchFilterPlaceholder")}
                        emptyText={
                          repoModuleSelectDisabled
                            ? t("workbench.products.modal.selectVersionFirst")
                            : modulesLoading
                              ? ""
                              : t("workbench.products.modal.moduleListEmpty")
                        }
                        disabled={repoModuleSelectDisabled}
                        isLoading={modulesLoading}
                      />
                    )}
                  </div>
                  <RepoBranchDerivedDisplay
                    prodBranch={repo.prodBranch}
                    branch={repo.branch}
                    repoModule={repo.repoModule}
                    loading={repoBranchLoading}
                    locked={repo.branchLocked}
                    showRequired={!repo.branchLocked}
                    prodBranchOptions={
                      repo.branchLocked
                        ? undefined
                        : filterProdBranchOptionsForRow(
                            prodBranchOptions,
                            rows,
                            index,
                            repo.prodBranch ?? "",
                          )
                    }
                    prodBranchLoading={prodBranchLoading}
                    prodBranchDisabled={repoModuleSelectDisabled}
                    onProdBranchChange={
                      repo.branchLocked ? undefined : (v) => handleProdBranchSelect(index, v)
                    }
                  />
                  <div className="col-span-12 space-y-1.5">
                    <Label className="text-xs">{t("workbench.products.modal.url")}</Label>
                    <Input
                      readOnly
                      tabIndex={-1}
                      className="h-9 text-xs bg-muted/50 cursor-default"
                      value={repo.url}
                      placeholder={t("workbench.products.modal.urlReadonlyPlaceholder")}
                    />
                    <p className="text-[11px] text-muted-foreground m-0">
                      {t("workbench.products.modal.urlReadonlyHint")}
                    </p>
                  </div>
                  <div className="col-span-12 space-y-1.5">
                    <Label className="text-xs">{t("workbench.products.modal.codePath")}</Label>
                    <Input
                      className="h-9 text-xs"
                      value={repo.codePath ?? ""}
                      onChange={(e) => updateRow(index, { codePath: e.target.value })}
                      placeholder={t("workbench.products.modal.codePathPlaceholder")}
                      disabled={saving}
                    />
                    <p className="text-[11px] text-muted-foreground m-0">
                      {t("workbench.products.modal.codePathHint")}
                    </p>
                  </div>
                  <div className="col-span-12 space-y-1.5">
                    <Label className="text-xs">{t("workbench.products.modal.purpose")}</Label>
                    <Input
                      className="h-9 text-xs"
                      value={repo.purpose}
                      onChange={(e) => updateRow(index, { purpose: e.target.value })}
                      placeholder={t("workbench.products.modal.purposePlaceholder")}
                    />
                  </div>
                  <div className="col-span-12 space-y-1.5">
                    <Label className="text-xs">
                      {t("workbench.products.modal.token")} <span className="text-destructive">*</span>
                    </Label>
                    <Input
                      className="h-9 text-xs"
                      type="password"
                      value={repo.token || ""}
                      onChange={(e) => updateRow(index, { token: e.target.value })}
                      placeholder={t("workbench.products.modal.tokenPlaceholder")}
                      disabled={saving}
                    />
                  </div>
                  <div className="col-span-12 flex items-center gap-2 pt-1">
                    <Switch
                      checked={repo.isMain}
                      onCheckedChange={(c) => updateRow(index, { isMain: c })}
                      id={`repo-main-dialog-${repo.clientKey}`}
                    />
                    <Label htmlFor={`repo-main-dialog-${repo.clientKey}`} className="text-xs cursor-pointer">
                      {t("workbench.products.modal.mainRepo")}
                    </Label>
                  </div>
                </div>
              </div>
              );
            })
          )}
        </div>

        <DialogFooter className="px-6 py-4 border-t border-border/60 bg-muted/10">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            {t("workbench.products.modal.cancel")}
          </Button>
          <Button type="button" onClick={() => void handleSave()} disabled={saving || !product}>
            {saving ? <Loader2 className="size-4 animate-spin mr-2" /> : null}
            {saving
              ? t("workbench.products.modal.repoTokenValidating")
              : t("workbench.products.repoUpdateDialog.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
