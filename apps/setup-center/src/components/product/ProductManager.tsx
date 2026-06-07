import React, { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Package, Loader2, RefreshCw } from "lucide-react";
import { ProductCard } from "./ProductCard";
import { ProductModal, formatProjectSpaceOption, type ProductModalFinishValues } from "./ProductModal";
import { RepoUpdateDialog } from "./RepoUpdateDialog";
import { ProductDetail } from "./ProductDetail";
import {
  Product,
  type ProductKnowledgePatch,
  Repository,
  MOCK_PRODUCTS,
  DEFAULT_ICONS,
  prodInfoWireToProduct,
  applyProcessPayloadToProduct,
  mergeProductKnowledge,
  mergeRepositoriesWithProcess,
  buildAnalysisFieldsFromProcessPayload,
  repositoriesToRdRepoInfo,
  patchProductKnowledgeSlots,
  emptyProductKnowledge,
} from "./types";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuCheckboxItem,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";
import { IS_TAURI } from "@/platform";
import {
  getProdInfo,
  insertProdInfo,
  updateProdInfo,
  fetchProjectList,
  fetchUserinfoForUnifiedService,
  destroyProd,
} from "@/api/rdUnifiedService";
import type { ProdProcessDataPayload } from "@/api/rdUnifiedService";
import { assertOwnerInfoMatchesProduct, toastOwnerInfoGuardError } from "@/utils/ownerInfoGuard";
import "./product-workbench.css";

/** 产品列表定时刷新间隔（与产品详情页的 process 轮询分离） */
const PRODUCT_LIST_AUTO_REFRESH_MS = 60_000;

export function ProductManager({ synapseApiBase = "http://127.0.0.1:18900" }: { synapseApiBase?: string }) {
  const { t } = useTranslation();
  const [products, setProducts] = useState<Product[]>(() => (IS_TAURI ? [] : MOCK_PRODUCTS));
  const [listLoading, setListLoading] = useState(IS_TAURI);
  const [listRefreshing, setListRefreshing] = useState(false);
  const [listAutoRefresh, setListAutoRefresh] = useState(true);
  const [projectSpaces, setProjectSpaces] = useState<{label: string, value: string}[] | null>(null);
  /** Tauri：本地 owner_info 密文（trim）；失败或未启用桌面端为 null；成功但为空串表示无凭据 */
  const [localOwnerInfo, setLocalOwnerInfo] = useState<string | null>(null);

  useEffect(() => {
    if (!IS_TAURI) return;
    let cancelled = false;
    (async () => {
      try {
        const row = await fetchUserinfoForUnifiedService(synapseApiBase);
        if (cancelled) return;
        setLocalOwnerInfo((row.owner_info ?? "").trim());
      } catch {
        if (!cancelled) setLocalOwnerInfo("");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [synapseApiBase]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetchProjectList(synapseApiBase);
        if (cancelled) return;
        setProjectSpaces(
          resp.map((p) => {
            const v = formatProjectSpaceOption(p.projectId, p.projectName);
            return { label: v, value: v };
          }),
        );
      } catch (e) {
        console.error("Failed to load project list", e);
        if (!cancelled) setProjectSpaces([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [synapseApiBase]);

  useEffect(() => {
    if (!IS_TAURI) return;
    let cancelled = false;
    (async () => {
      try {
        const resp = await getProdInfo(synapseApiBase);
        if (cancelled) return;
        const raw = Array.isArray(resp.data) ? resp.data : [];
        const rows = raw.filter((row): row is NonNullable<typeof row> => row != null);
        const mapped = rows.map(prodInfoWireToProduct);
        if (resp.total !== rows.length) {
          console.warn("[get_prod_info] total != data.length", resp.total, rows.length);
        }
        setProducts(mapped);
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : String(e);
        if (msg === "missing_devservice_ip") {
          toast.error(t("workbench.products.createMissingDevservice"));
        } else {
          toast.error(t("workbench.products.loadListFailed", { message: msg }));
        }
        setProducts([]);
      } finally {
        if (!cancelled) setListLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [synapseApiBase, t]);

  const mergeProcessIntoProduct = useCallback((productId: string, payload: ProdProcessDataPayload) => {
    setProducts((prev) =>
      prev.map((p) => (p.id === productId ? applyProcessPayloadToProduct(p, payload) : p)),
    );
    setSelectedProduct((sp) =>
      sp?.id === productId ? applyProcessPayloadToProduct(sp, payload) : sp,
    );
  }, []);

  const patchProductKnowledge = useCallback((productId: string, patch: ProductKnowledgePatch) => {
    setProducts((prev) =>
      prev.map((p) =>
        p.id === productId ? { ...p, knowledge: patchProductKnowledgeSlots(p.knowledge, patch) } : p,
      ),
    );
    setSelectedProduct((sp) =>
      sp?.id === productId ? { ...sp, knowledge: patchProductKnowledgeSlots(sp.knowledge, patch) } : sp,
    );
  }, []);

  const refreshListFromServer = useCallback(
    async (opts: { successToast: boolean }) => {
      if (!IS_TAURI) return;
      try {
        const resp = await getProdInfo(synapseApiBase);
        const raw = Array.isArray(resp.data) ? resp.data : [];
        const rows = raw.filter((row): row is NonNullable<typeof row> => row != null);
        const mapped = rows.map(prodInfoWireToProduct);
        if (resp.total !== rows.length) {
          console.warn("[get_prod_info] total != data.length", resp.total, rows.length);
        }
        setProducts(mapped);
        setSelectedProduct((sp) => {
          if (!sp) return sp;
          const m = mapped.find((p) => p.id === sp.id || p.name.trim() === sp.name.trim());
          if (!m) return sp;
          return {
            ...m,
            knowledge: mergeProductKnowledge(m.knowledge, sp.knowledge),
            latestTickets: sp.latestTickets,
          };
        });
        if (opts.successToast) {
          toast.success(t("workbench.products.refreshListSuccess"));
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (msg === "missing_devservice_ip") {
          toast.error(t("workbench.products.createMissingDevservice"));
        } else {
          toast.error(t("workbench.products.refreshListFailed", { message: msg }));
        }
      }
    },
    [synapseApiBase, t],
  );

  useEffect(() => {
    if (!IS_TAURI || !listAutoRefresh) return;
    const id = window.setInterval(() => {
      void refreshListFromServer({ successToast: false });
    }, PRODUCT_LIST_AUTO_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [IS_TAURI, listAutoRefresh, refreshListFromServer]);

  const listRefreshLock = useRef(false);
  const handleHeaderRefreshList = async () => {
    if (!IS_TAURI) {
      toast.message(t("workbench.products.tauriOnlyAction"));
      return;
    }
    if (listRefreshLock.current) return;
    listRefreshLock.current = true;
    setListRefreshing(true);
    try {
      await refreshListFromServer({ successToast: true });
    } finally {
      setListRefreshing(false);
      listRefreshLock.current = false;
    }
  };

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingProduct, setEditingProduct] = useState<Product | undefined>(undefined);
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [isDetailOpen, setIsDetailOpen] = useState(false);
  const [cardActionBusy, setCardActionBusy] = useState<{
    productId: string;
    kind: "refresh" | "repo" | "delete";
  } | null>(null);
  const [deletingProduct, setDeletingProduct] = useState<Product | null>(null);

  const filteredProducts = products;

  const handleRefreshProcess = async (product: Product) => {
    if (!IS_TAURI) {
      toast.message(t("workbench.products.tauriOnlyAction"));
      return;
    }
    setCardActionBusy({ productId: product.id, kind: "refresh" });
    try {
      const resp = await getProdInfo(synapseApiBase);
      const raw = Array.isArray(resp.data) ? resp.data : [];
      const match = raw.find((r) => r != null && (r.prod ?? "").trim() === product.name.trim());
      if (!match) {
        toast.error(t("workbench.products.refreshProcessEmpty"));
        return;
      }
      const updated = prodInfoWireToProduct(match);
      setProducts((prev) =>
        prev.map((p) =>
          p.id === product.id
            ? {
                ...updated,
                id: p.id,
                knowledge: mergeProductKnowledge(updated.knowledge, p.knowledge),
                latestTickets: p.latestTickets,
              }
            : p,
        ),
      );
      setSelectedProduct((sp) =>
        sp?.id === product.id
          ? {
              ...updated,
              id: sp.id,
              knowledge: mergeProductKnowledge(updated.knowledge, sp.knowledge),
              latestTickets: sp.latestTickets,
            }
          : sp,
      );
      toast.success(t("workbench.products.refreshProcessSuccess"));
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg === "missing_devservice_ip") {
        toast.error(t("workbench.products.createMissingDevservice"));
      } else {
        toast.error(t("workbench.products.refreshListFailed", { message: msg }));
      }
    } finally {
      setCardActionBusy(null);
    }
  };

  const [repoDialogProduct, setRepoDialogProduct] = useState<Product | null>(null);

  const handleOpenRepoUpdate = async (product: Product) => {
    if (!IS_TAURI) {
      toast.message(t("workbench.products.tauriOnlyAction"));
      return;
    }
    try {
      await assertOwnerInfoMatchesProduct(synapseApiBase, product);
    } catch (e) {
      toastOwnerInfoGuardError(t, e);
      return;
    }
    setRepoDialogProduct(product);
  };

  const handleRepoUpdateSuccess = (
    productId: string,
    repositories: Repository[],
    process: ProdProcessDataPayload | null | undefined,
  ) => {
    setProducts((prev) =>
      prev.map((p) => {
        if (p.id !== productId) return p;
        const mergedRepos = mergeRepositoriesWithProcess(repositories, process?.repo_process);
        if (process == null) {
          return { ...p, repositories: mergedRepos };
        }
        const fields = buildAnalysisFieldsFromProcessPayload(process);
        return {
          ...p,
          repositories: mergedRepos,
          analysisStatus: fields.analysisStatus,
          analysisUnified: fields.analysisUnified,
          analysisTimes: fields.analysisTimes,
        };
      }),
    );
    setSelectedProduct((sp) => {
      if (sp?.id !== productId) return sp;
      const mergedRepos = mergeRepositoriesWithProcess(repositories, process?.repo_process);
      if (process == null) {
        return { ...sp, repositories: mergedRepos };
      }
      const fields = buildAnalysisFieldsFromProcessPayload(process);
      return {
        ...sp,
        repositories: mergedRepos,
        analysisStatus: fields.analysisStatus,
        analysisUnified: fields.analysisUnified,
        analysisTimes: fields.analysisTimes,
      };
    });
  };

  const handleAdd = () => {
    setEditingProduct(undefined);
    setIsModalOpen(true);
  };

  const handleEdit = async (product: Product) => {
    if (IS_TAURI) {
      try {
        await assertOwnerInfoMatchesProduct(synapseApiBase, product);
      } catch (e) {
        toastOwnerInfoGuardError(t, e);
        return;
      }
    }
    setEditingProduct(product);
    setIsModalOpen(true);
  };

  const handleDeleteRequest = async (product: Product) => {
    if (IS_TAURI) {
      try {
        await assertOwnerInfoMatchesProduct(synapseApiBase, product);
      } catch (e) {
        toastOwnerInfoGuardError(t, e);
        return;
      }
    }
    setDeletingProduct(product);
  };

  const executeDelete = async (id: string) => {
    const product = products.find((p) => p.id === id);
    if (!product) return;
    const detailWasThisProduct = selectedProduct?.id === id;

    const clearDetailIfNeeded = () => {
      if (detailWasThisProduct) {
        setSelectedProduct(null);
        setIsDetailOpen(false);
      }
    };

    if (!IS_TAURI) {
      setProducts((prev) => prev.filter((p) => p.id !== id));
      clearDetailIfNeeded();
      toast.success(t("workbench.products.deleted") || "已删除");
      return;
    }

    const prodKey = product.name.trim();
    if (!prodKey) {
      toast.error(t("workbench.products.deleteRemoteFailed", { message: "empty prod" }));
      return;
    }

    setCardActionBusy({ productId: id, kind: "delete" });
    try {
      const resp = await destroyProd(synapseApiBase, { prod: prodKey });
      setProducts((prev) => prev.filter((p) => p.id !== id));
      clearDetailIfNeeded();
      const okMsg = typeof resp.message === "string" && resp.message.trim() !== "" ? resp.message.trim() : "";
      toast.success(okMsg || t("workbench.products.deleted") || "已删除");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg === "missing_devservice_ip") {
        toast.error(t("workbench.products.createMissingDevservice"));
      } else {
        toast.error(t("workbench.products.deleteRemoteFailed", { message: msg }));
      }
    } finally {
      setCardActionBusy(null);
    }
  };

  const handleView = (product: Product) => {
    setSelectedProduct(product);
    setIsDetailOpen(true);
  };

  const handleFinish = async (values: ProductModalFinishValues) => {
    if (editingProduct) {
      if (IS_TAURI) {
        try {
          await assertOwnerInfoMatchesProduct(synapseApiBase, editingProduct);
        } catch (e) {
          toastOwnerInfoGuardError(t, e);
          return;
        }
        try {
          await updateProdInfo(synapseApiBase, {
            prod: editingProduct.name.trim(),
            function: (values.features || "").trim(),
            prod_icon: (values.iconLabel || "").trim(),
            prod_desc: (values.description || "").trim(),
          });
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          if (msg === "missing_devservice_ip") {
            toast.error(t("workbench.products.createMissingDevservice"));
          } else if (/userinfo|未找到/.test(msg)) {
            toast.error(t("workbench.products.createMissingUserinfo"));
          } else {
            toast.error(t("workbench.products.updateRemoteFailed", { message: msg }));
          }
          return;
        }
      }

      setProducts(
        products.map((p) =>
          p.id === editingProduct.id
            ? ({
                ...p,
                ...values,
                name: p.name,
                repositories: p.repositories,
                icon: values.icon ?? p.icon,
              } as Product)
            : p,
        ),
      );
      toast.success(t("workbench.products.updated") || "已更新");
      setIsModalOpen(false);
      return;
    }

    let insertOwner: { owner: string; ownerInfo: string } | undefined;
    if (IS_TAURI) {
      try {
        const created = await insertProdInfo(synapseApiBase, {
          prod: values.name || "",
          version: (values.version || "").trim(),
          module: (values.module || "").trim(),
          space: (values.spaceLabel || "").trim(),
          function: values.features || "",
          prod_icon: (values.iconLabel || "").trim(),
          prod_desc: (values.description || "").trim(),
          repo_info: repositoriesToRdRepoInfo(values.repositories || []),
        });
        insertOwner = { owner: created.owner, ownerInfo: created.owner_info };
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (msg === "missing_devservice_ip") {
          toast.error(t("workbench.products.createMissingDevservice"));
        } else if (/userinfo|未找到/.test(msg)) {
          toast.error(t("workbench.products.createMissingUserinfo"));
        } else {
          toast.error(t("workbench.products.createRemoteFailed", { message: msg }));
        }
        return;
      }
    }

    const newProduct: Product = {
      ...values,
      ...(insertOwner ? { owner: insertOwner.owner, ownerInfo: insertOwner.ownerInfo } : {}),
      id: Math.random().toString(36).slice(2, 11),
      icon: values.icon || DEFAULT_ICONS[Math.floor(Math.random() * DEFAULT_ICONS.length)].value,
      repositories: values.repositories || [],
      knowledge: patchProductKnowledgeSlots(
        emptyProductKnowledge(),
        (values.knowledge ?? {}) as ProductKnowledgePatch,
      ),
      analysisStatus: {
        code: "pending",
        ticket: "pending",
        document: "pending",
      },
      analysisUnified: {
        code: "new",
        ticket: "new",
        document: "new",
      },
      analysisTimes: {},
    } as Product;
    setProducts([newProduct, ...products]);
    toast.success(t("workbench.products.created") || "已创建");
    setIsModalOpen(false);
  };

  return (
    <div className="product-workbench">
      <div className="product-workbench-scroll">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-5">
          {/* Header Card matching MCP */}
          <Card className="gap-0 overflow-hidden border-border/80 bg-gradient-to-br from-primary/5 via-background to-background py-0 shadow-sm">
            <CardHeader className="gap-3 px-6 py-5">
              <div className="flex items-start justify-between gap-4">
                <div className="flex min-w-0 items-start gap-4">
                  <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                    <Package size={22} />
                  </div>
                  <div className="min-w-0 space-y-2">
                    <div className="flex min-w-0 items-center gap-3">
                      <CardTitle className="truncate text-xl tracking-tight">
                        {t("workbench.products.breadcrumbCurrent")}
                      </CardTitle>
                    </div>
                    <CardDescription className="max-w-3xl text-sm leading-6">
                      {t("workbench.products.subtitle")}
                    </CardDescription>
                  </div>
                </div>

                <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        disabled={!IS_TAURI || listRefreshing}
                        title={t("workbench.products.tooltipRefreshList")}
                      >
                        <RefreshCw
                          size={14}
                          className={`mr-1.5 ${listRefreshing || listAutoRefresh ? "animate-spin" : ""}`}
                        />
                        {t("workbench.products.refreshList")}
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-48">
                      <DropdownMenuItem inset onClick={() => void handleHeaderRefreshList()}>
                        {t("workbench.products.refreshNow", "立即刷新")}
                      </DropdownMenuItem>
                      <DropdownMenuCheckboxItem
                        checked={listAutoRefresh}
                        onCheckedChange={setListAutoRefresh}
                      >
                        {t("workbench.products.autoRefreshListLabel")}
                      </DropdownMenuCheckboxItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                  <Button variant="outline" onClick={handleAdd}>
                    <Plus size={14} className="mr-1.5" />
                    {t("workbench.products.addProduct")}
                  </Button>
                </div>
              </div>
            </CardHeader>
          </Card>

          {/* Product Grid — get_prod_info 全量拉取，不做分页 */}
          {listLoading ? (
            <Card className="shadow-sm border-border/80">
              <CardContent className="flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground">
                <Loader2 className="size-10 app-loading-spin text-primary/80" aria-hidden />
                <p className="text-sm">{t("workbench.products.loadingList")}</p>
              </CardContent>
            </Card>
          ) : filteredProducts.length > 0 ? (
            <div className="grid gap-5 sm:grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
              {filteredProducts.map((product) => (
                  <ProductCard
                  key={product.id}
                  product={product}
                  isOwnedByCurrentUser={
                    IS_TAURI &&
                    localOwnerInfo != null &&
                    localOwnerInfo.length > 0 &&
                    localOwnerInfo === (product.ownerInfo ?? "").trim()
                  }
                  onEdit={handleEdit}
                  onDelete={handleDeleteRequest}
                  onView={handleView}
                  onRefreshProcess={handleRefreshProcess}
                  onChangeRepos={handleOpenRepoUpdate}
                  cardActionBusy={cardActionBusy}
                />
              ))}
            </div>
          ) : (
            <Card className="shadow-sm border-border/80">
              <CardContent className="py-12 text-center text-muted-foreground">
                <div className="flex flex-col items-center justify-center gap-3 opacity-60">
                  <Package size={48} className="text-muted-foreground" />
                  <p className="text-base font-medium">{t("workbench.products.empty")}</p>
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        <ProductModal
          open={isModalOpen}
          onCancel={() => setIsModalOpen(false)}
          onFinish={handleFinish}
          initialValues={editingProduct}
          projectSpaces={projectSpaces}
          synapseApiBase={synapseApiBase}
        />

        {/* 更新仓库：内部调用 changeRepoInfo → :10001/dev/iwhalecloud/synapse/change_repo_info */}
        <RepoUpdateDialog
          open={repoDialogProduct != null}
          onOpenChange={(o) => {
            if (!o) setRepoDialogProduct(null);
          }}
          product={repoDialogProduct}
          synapseApiBase={synapseApiBase}
          onSuccess={handleRepoUpdateSuccess}
          onBusyChange={(busy) => {
            if (busy && repoDialogProduct) {
              setCardActionBusy({ productId: repoDialogProduct.id, kind: "repo" });
            } else {
              setCardActionBusy(null);
            }
          }}
        />

        <ProductDetail
          product={selectedProduct}
          open={isDetailOpen}
          onClose={() => setIsDetailOpen(false)}
          synapseApiBase={synapseApiBase}
          onProcessPayload={mergeProcessIntoProduct}
          onPatchProductKnowledge={patchProductKnowledge}
        />

        <AlertDialog open={deletingProduct != null} onOpenChange={(open) => { if (!open) setDeletingProduct(null); }}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t("workbench.products.deleteConfirmTitle")}</AlertDialogTitle>
              <AlertDialogDescription asChild>
                <div>
                  <p>{t("workbench.products.deleteConfirmDesc")}</p>
                  {deletingProduct && <span className="block mt-2 font-medium text-foreground">{deletingProduct.name}</span>}
                </div>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t("workbench.products.cancel")}</AlertDialogCancel>
              <AlertDialogAction
                variant="destructive"
                onClick={() => {
                  if (deletingProduct) {
                    void executeDelete(deletingProduct.id);
                  }
                  setDeletingProduct(null);
                }}
              >
                {t("workbench.products.confirm")}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </div>
  );
}
