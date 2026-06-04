import React, { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Loader2 } from "lucide-react";
import { Virtuoso } from "react-virtuoso";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export type SearchableOption = { label: string; value: string };

type SearchableVirtualSelectProps = {
  value: string;
  onValueChange: (v: string) => void;
  options: SearchableOption[];
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  disabled?: boolean;
  isLoading?: boolean;
  className?: string;
  /** 下拉层额外 class（如提高 z-index，避免被父级 overflow 裁剪） */
  popoverClassName?: string;
  /** 虚拟列表行高（默认 36） */
  itemHeight?: number;
};

/**
 * 可输入过滤 + 虚拟列表，避免数千条 Radix SelectItem 一次性挂载导致卡顿。
 */
export function SearchableVirtualSelect({
  value,
  onValueChange,
  options,
  placeholder = "",
  searchPlaceholder = "",
  emptyText = "",
  disabled = false,
  isLoading = false,
  className,
  popoverClassName,
  itemHeight = 36,
}: SearchableVirtualSelectProps) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return options;
    return options.filter(
      (o) =>
        o.label.toLowerCase().includes(t) || o.value.toLowerCase().includes(t),
    );
  }, [options, q]);

  const selectedLabel = value
    ? options.find((o) => o.value === value)?.label ?? value
    : "";

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const el = rootRef.current;
      if (el && !el.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  useEffect(() => {
    if (!open) setQ("");
  }, [open]);

  return (
    <div ref={rootRef} className={cn("relative w-full", className)}>
      <button
        type="button"
        disabled={disabled}
        aria-expanded={open}
        onClick={() => {
          if (!disabled) setOpen((o) => !o);
        }}
        className={cn(
          "flex h-9 w-full items-center justify-between gap-2 rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none transition-[color,box-shadow]",
          "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "dark:bg-input/30 dark:hover:bg-input/50",
          selectedLabel ? "text-foreground" : "text-foreground/55",
        )}
      >
        <span className="truncate text-left" title={selectedLabel || undefined}>
          {selectedLabel || placeholder}
        </span>
        <ChevronDown className="size-4 shrink-0 opacity-50" />
      </button>

      {open && (
        <div
          className={cn(
            "absolute left-0 right-0 top-full z-[200] mt-1 overflow-hidden rounded-md border border-border/80 bg-popover text-popover-foreground shadow-lg shadow-black/25",
            popoverClassName,
          )}
          role="listbox"
        >
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={searchPlaceholder}
            className="rounded-none border-0 border-b px-3 text-sm shadow-none focus-visible:ring-0"
            autoFocus
          />
          <div className="relative">
            {isLoading ? (
              <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
                <Loader2 className="size-4 app-loading-spin" aria-hidden />
              </div>
            ) : filtered.length === 0 ? (
              <div className="px-3 py-8 text-center text-sm text-muted-foreground">
                {emptyText}
              </div>
            ) : (
              <Virtuoso
                style={{ height: Math.min(280, Math.max(120, filtered.length * itemHeight)) }}
                totalCount={filtered.length}
                fixedItemHeight={itemHeight}
                itemContent={(index) => {
                  const opt = filtered[index];
                  const active = opt.value === value;
                  const tip = opt.label || opt.value;
                  return (
                    <button
                      type="button"
                      key={opt.value}
                      role="option"
                      aria-selected={active}
                      title={tip}
                      className={cn(
                        "flex w-full min-w-0 items-center px-3 text-left text-sm outline-none text-foreground",
                        "hover:bg-accent hover:text-accent-foreground",
                        active && "bg-primary/15 text-foreground font-medium",
                      )}
                      style={{ height: itemHeight }}
                      onClick={() => {
                        onValueChange(opt.value);
                        setOpen(false);
                      }}
                    >
                      <span className="min-w-0 truncate leading-snug">{opt.label}</span>
                    </button>
                  );
                }}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
