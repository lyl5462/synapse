import React from "react";
import { useTranslation } from "react-i18next";
import { Label } from "@/components/ui/label";
import { displayIdPipeName } from "./types";

export type RepoBranchDerivedDisplayProps = {
  prodBranch?: string;
  branch?: string;
  repoModule?: string;
  loading?: boolean;
  locked?: boolean;
  showRequired?: boolean;
};

function fieldTextClass(hasContent: boolean): string {
  return [
    "text-sm min-h-[2rem] py-1.5 leading-snug break-all",
    hasContent ? "text-foreground" : "text-muted-foreground",
  ].join(" ");
}

/** 第二行：产品分支、仓库分支只读文本（由应用模块与接口自动推导） */
export function RepoBranchDerivedDisplay({
  prodBranch,
  branch,
  repoModule,
  loading = false,
  locked = false,
  showRequired = true,
}: RepoBranchDerivedDisplayProps) {
  const { t } = useTranslation();
  const hasModule = !!(repoModule?.trim());
  const prodVal = prodBranch?.trim() ?? "";
  const branchVal = branch?.trim() ?? "";

  const prodDisplay = prodVal
    ? displayIdPipeName(prodBranch!)
    : locked
      ? "—"
      : !hasModule
        ? t("workbench.products.modal.selectAppModuleFirst")
        : t("workbench.products.modal.prodBranchEmpty");

  const branchDisplay = branchVal
    ? displayIdPipeName(branch!)
    : loading
      ? t("workbench.products.modal.repoBranchLoading")
      : locked
        ? branch || "—"
        : !hasModule
          ? t("workbench.products.modal.selectAppModuleFirst")
          : !prodVal
            ? t("workbench.products.modal.prodBranchEmpty")
            : t("workbench.products.modal.repoBranchDetailEmpty");

  const req = showRequired ? " *" : "";

  return (
    <div className="col-span-12 grid grid-cols-12 gap-4">
      <div className="col-span-12 sm:col-span-6 space-y-1.5">
        <Label className="text-xs">
          {t("workbench.products.modal.prodBranch")}
          {req}
        </Label>
        <p className={fieldTextClass(!!prodVal)}>{prodDisplay}</p>
      </div>
      <div className="col-span-12 sm:col-span-6 space-y-1.5">
        <Label className="text-xs">
          {t("workbench.products.modal.branch")}
          {req}
        </Label>
        <p className={fieldTextClass(!!branchVal && !loading)}>{branchDisplay}</p>
      </div>
    </div>
  );
}
