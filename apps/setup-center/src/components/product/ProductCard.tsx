import React from "react";
import { useTranslation } from "react-i18next";
import { Edit2, Trash2, Ticket, Code, FileText, Check, Loader2, X, RefreshCw, GitBranch, Circle } from "lucide-react";
import { Product, displayIdPipeName, type UnifiedWireAnalysisState } from "./types";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface ProductCardProps {
  product: Product;
  /** 与本地 userinfo.encryption 对应的 owner_info 一致时为 true（仅桌面端计算） */
  isOwnedByCurrentUser?: boolean;
  onEdit: (product: Product) => void | Promise<void>;
  onDelete: (product: Product) => void;
  onView: (product: Product) => void;
  onRefreshProcess?: (product: Product) => void | Promise<void>;
  onChangeRepos?: (product: Product) => void | Promise<void>;
  cardActionBusy?: { productId: string; kind: "refresh" | "repo" | "delete" } | null;
}

type AnalysisKey = "code" | "ticket" | "document";

/** 卡片三维：new=待开始（不转圈）；init/process=进行中（黄圈）；done/error 保持语义色 */
const analysisVisualFromUnified = (u: UnifiedWireAnalysisState | undefined) => {
  switch (u) {
    case "done":
      return {
        shell:
          "border-emerald-500/40 bg-emerald-500/[0.12] text-emerald-700 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)] dark:text-emerald-400",
        statusIcon: "text-emerald-600 dark:text-emerald-400",
        icon: "done" as const,
      };
    case "error":
      return {
        shell:
          "border-red-500/40 bg-red-500/[0.12] text-red-800 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)] dark:text-red-400",
        statusIcon: "text-red-600 dark:text-red-400",
        icon: "error" as const,
      };
    case "init":
    case "process":
      return {
        shell:
          "border-amber-500/45 bg-amber-500/[0.14] text-amber-900 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.06)] dark:text-amber-300",
        statusIcon: "text-amber-600 dark:text-amber-400",
        icon: "running" as const,
      };
    case "new":
    default:
      return {
        shell:
          "border-border/60 bg-muted/40 text-muted-foreground shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]",
        statusIcon: "text-muted-foreground",
        icon: "idle" as const,
      };
  }
};

const getTicketStatusColorClass = (status: string) => {
  switch (status) {
    case "已完成":
      return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400";
    case "处理中":
      return "bg-blue-500/10 text-blue-700 dark:text-blue-400";
    case "待处理":
    default:
      return "bg-muted/30 text-muted-foreground";
  }
};

function AnalysisStatusBadge({
  dimensionKey,
  unified,
  dimensionLabel,
}: {
  dimensionKey: AnalysisKey;
  unified: UnifiedWireAnalysisState | undefined;
  dimensionLabel: string;
}) {
  const { t } = useTranslation();
  const v = analysisVisualFromUnified(unified);

  const stateLabel = (() => {
    switch (unified) {
      case "done":
        return t("workbench.products.analysisStateCompleted");
      case "error":
        return t("workbench.products.analysisStateFailed");
      case "init":
      case "process":
        return t("workbench.products.analysisStateInProgress");
      case "new":
      default:
        return t("workbench.products.analysisStateNotStarted");
    }
  })();

  const title = t("workbench.products.analysisStatusTooltip", {
    dimension: dimensionLabel,
    state: stateLabel,
  });

  const DomainIcon = dimensionKey === "code" ? Code : dimensionKey === "ticket" ? Ticket : FileText;

  return (
    <div
      className={`flex min-w-0 flex-1 items-center justify-center gap-1.5 rounded-lg border px-2 py-1.5 text-[10px] font-medium leading-none transition-colors ${v.shell}`}
      title={title}
      role="status"
      aria-label={title}
    >
      <DomainIcon className="size-3.5 shrink-0 opacity-90" strokeWidth={2.25} aria-hidden />
      {v.icon === "done" ? (
        <Check className={`size-3.5 shrink-0 stroke-[2.75] ${v.statusIcon}`} aria-hidden />
      ) : v.icon === "error" ? (
        <X className={`size-3.5 shrink-0 stroke-[2.75] ${v.statusIcon}`} aria-hidden />
      ) : v.icon === "idle" ? (
        <Circle className={`size-3.5 shrink-0 stroke-[2.5] ${v.statusIcon}`} aria-hidden />
      ) : (
        <Loader2 className={`size-3.5 shrink-0 animate-spin ${v.statusIcon}`} aria-hidden />
      )}
    </div>
  );
}

export function ProductCard({
  product,
  isOwnedByCurrentUser = false,
  onEdit,
  onDelete,
  onView,
  onRefreshProcess,
  onChangeRepos,
  cardActionBusy,
}: ProductCardProps) {
  const { t } = useTranslation();
  const busyRefresh = cardActionBusy?.productId === product.id && cardActionBusy.kind === "refresh";
  const busyRepo = cardActionBusy?.productId === product.id && cardActionBusy.kind === "repo";
  const busyDelete = cardActionBusy?.productId === product.id && cardActionBusy.kind === "delete";

  return (
    <Card 
      className="group relative flex h-[420px] flex-col overflow-hidden border-border/80 bg-background/60 shadow-sm transition-all hover:shadow-md hover:border-primary/30"
      onClick={() => onView(product)}
      style={{ cursor: "pointer" }}
    >
      {/* 空间挂饰 */}
      {product.space && (
        <div 
          className="absolute left-0 top-0 z-10 flex items-center justify-center rounded-br-2xl rounded-tl-xl border-b border-r border-amber-500/20 bg-amber-500/10 px-3.5 py-1.5 shadow-sm backdrop-blur-md"
          title={t("workbench.products.cardSpaceTooltip", { space: product.space })}
        >
          <span className="block max-w-[12rem] truncate text-[11px] font-semibold tracking-wide text-amber-700 dark:text-amber-300">
            {displayIdPipeName(product.space)}
          </span>
        </div>
      )}

      <div className="absolute right-3 top-3 z-10 flex gap-1.5 opacity-0 transition-opacity group-hover:opacity-100">
        <Button
          variant="ghost"
          className="h-7 w-7 p-0 text-muted-foreground hover:bg-background/90 hover:text-foreground shadow-sm border border-border/50 bg-background/50 backdrop-blur"
          disabled={busyRefresh || busyRepo || busyDelete}
          onClick={(e) => {
            e.stopPropagation();
            void onEdit(product);
          }}
          title={t("workbench.products.tooltipEdit") || "编辑"}
        >
          <Edit2 size={13} />
        </Button>
        {onRefreshProcess && (
          <Button
            variant="ghost"
            className="h-7 w-7 p-0 text-muted-foreground hover:bg-background/90 hover:text-foreground shadow-sm border border-border/50 bg-background/50 backdrop-blur"
            disabled={busyRefresh || busyRepo || busyDelete}
            onClick={(e) => {
              e.stopPropagation();
              void onRefreshProcess(product);
            }}
            title={t("workbench.products.tooltipRefreshProcess")}
          >
            {busyRefresh ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          </Button>
        )}
        {onChangeRepos && (
          <Button
            variant="ghost"
            className="h-7 w-7 p-0 text-muted-foreground hover:bg-background/90 hover:text-foreground shadow-sm border border-border/50 bg-background/50 backdrop-blur"
            disabled={busyRefresh || busyRepo || busyDelete}
            onClick={(e) => {
              e.stopPropagation();
              void onChangeRepos(product);
            }}
            title={t("workbench.products.tooltipChangeRepos")}
          >
            {busyRepo ? <Loader2 size={13} className="animate-spin" /> : <GitBranch size={13} />}
          </Button>
        )}
        <Button
          variant="ghost"
          className="h-7 w-7 p-0 text-destructive hover:bg-destructive/10 hover:text-destructive shadow-sm border border-destructive/20 bg-background/50 backdrop-blur"
          disabled={busyRefresh || busyRepo || busyDelete}
          onClick={(e) => {
            e.stopPropagation();
            onDelete(product);
          }}
          title={t("workbench.products.tooltipDelete") || "删除"}
        >
          {busyDelete ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
        </Button>
      </div>

      <CardContent className="flex h-full flex-col px-5 pb-5 pt-9">
        <div className="mb-4 flex min-w-0 flex-col gap-2">
          <div className="flex items-start gap-3">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-primary/20 bg-primary/5">
              <img src={product.icon} alt={product.name} className="h-8 w-8 rounded-md object-contain" />
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <div className="flex min-w-0 items-center gap-2">
                {isOwnedByCurrentUser ? (
                  <Badge
                    variant="outline"
                    className="shrink-0 border-primary/40 bg-primary/10 px-1.5 py-0 text-[10px] font-medium text-primary"
                    title={t("workbench.products.cardMineBadgeTooltip")}
                  >
                    {t("workbench.products.cardMineBadge")}
                  </Badge>
                ) : null}
                <h3
                  className="min-w-0 flex-1 basis-0 truncate text-base font-semibold tracking-tight text-foreground"
                  title={product.name}
                >
                  {product.name}
                </h3>
              </div>
              {(product.module?.trim() || product.version) ? (
                <div className="flex min-w-0 items-center gap-2">
                  {product.module?.trim() ? (
                    <Badge
                      variant="secondary"
                      className="max-w-[5.5rem] shrink-0 truncate font-normal text-[10px] px-1.5 py-0 sm:max-w-[7rem] bg-purple-500/10 text-purple-700 dark:text-purple-400"
                      title={product.module.trim()}
                    >
                      {product.module.trim()}
                    </Badge>
                  ) : null}
                  {product.version ? (
                    <Badge
                      variant="outline"
                      className="max-w-[10rem] shrink-0 truncate whitespace-nowrap border-teal-500/35 bg-teal-500/10 font-normal text-[10px] text-teal-800 dark:text-teal-300 sm:max-w-[14rem]"
                      title={displayIdPipeName(product.version)}
                    >
                      {displayIdPipeName(product.version)}
                    </Badge>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
          <div className="min-w-0">
            {product.description?.trim() ? (
              <Tooltip delayDuration={400}>
                <TooltipTrigger asChild>
                  <p
                    className="line-clamp-2 cursor-default break-words text-[13px] leading-5 text-muted-foreground"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {product.description}
                  </p>
                </TooltipTrigger>
                <TooltipContent
                  showArrow={false}
                  side="bottom"
                  align="start"
                  sideOffset={6}
                  className="max-w-md whitespace-pre-wrap border border-white/25 bg-background/75 px-3 py-2 text-xs leading-relaxed text-foreground shadow-2xl backdrop-blur-xl dark:border-white/10 dark:bg-background/65"
                >
                  {product.description}
                </TooltipContent>
              </Tooltip>
            ) : (
              <p className="line-clamp-2 text-[13px] leading-5 text-muted-foreground/40">—</p>
            )}
          </div>
        </div>

        <div className="mb-4 flex gap-2 overflow-hidden">
          <AnalysisStatusBadge
            dimensionKey="code"
            unified={product.analysisUnified?.code}
            dimensionLabel={t("workbench.products.analysisCode")}
          />
          <AnalysisStatusBadge
            dimensionKey="document"
            unified={product.analysisUnified?.document}
            dimensionLabel={t("workbench.products.analysisDocument")}
          />
          <AnalysisStatusBadge
            dimensionKey="ticket"
            unified={product.analysisUnified?.ticket}
            dimensionLabel={t("workbench.products.analysisTicket")}
          />
        </div>

        <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-border/60 bg-muted/10 p-3">
          <div className="mb-3 flex shrink-0 items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
              <Ticket size={14} className="text-blue-500" />
              {t("workbench.products.recentTickets", { count: product.latestTickets?.length || 0 }) || `近30日改造工单 (${product.latestTickets?.length || 0})`}
            </div>
          </div>

          <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto pr-1">
            {product.latestTickets && product.latestTickets.length > 0 ? (
              <div className="flex flex-col space-y-2.5">
                {product.latestTickets.map((item) => (
                  <div key={item.id} className="flex items-center gap-2 border-b border-border/30 pb-2.5 last:border-0 last:pb-0">
                    <span className="shrink-0 font-mono text-[10px] text-muted-foreground/70">#{item.id}</span>
                    <span className="flex-1 truncate text-xs text-foreground/80" title={item.title}>
                      {item.title}
                    </span>
                    <span className="shrink-0 w-10 truncate text-right text-[10px] text-muted-foreground">
                      {item.assignee}
                    </span>
                    <span className={`shrink-0 w-12 rounded-sm px-1 py-0.5 text-center text-[9px] ${getTicketStatusColorClass(item.status)}`}>
                      {item.status}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex h-full items-center justify-center">
                <span className="text-xs italic text-muted-foreground/60">
                  {t("workbench.products.noTickets")}
                </span>
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
