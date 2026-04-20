/**
 * 首次引导「核心智能体」步骤：对齐「配置 → 灵魂与意志」与「能力 → 技能配置」。
 */
import { useCallback, useEffect, useState, type ComponentType, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Plus, CheckCircle2, ChevronRight, Upload, Cpu, Zap, Puzzle, MessageSquareQuote, Bot, Edit3 } from "lucide-react";
import { toast } from "sonner";
import { safeFetch } from "../providers";
import type { EnvMap } from "../types";
import { envGet, envSet } from "../utils";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { FieldText, FieldBool, FieldSelect } from "../components/EnvFields";
import { cn } from "@/lib/utils";
import logoUrl from "../assets/logo.png";

/** 预设角色（与后端 identity/personas/{id}.md 一一对应；自定义 ID 仅出现在 extraPersonas） */
const DEFAULT_PERSONAS: { id: string; desc: string }[] = [
  { id: "default", desc: "config.agentPersonaDefault" },
  { id: "business", desc: "config.agentPersonaBusiness" },
  { id: "tech_expert", desc: "config.agentPersonaTech" },
  { id: "butler", desc: "config.agentPersonaButler" },
  { id: "girlfriend", desc: "config.agentPersonaGirlfriend" },
  { id: "boyfriend", desc: "config.agentPersonaBoyfriend" },
  { id: "family", desc: "config.agentPersonaFamily" },
  { id: "jarvis", desc: "config.agentPersonaJarvis" },
];
const DEFAULT_PERSONA_ID_SET = new Set(DEFAULT_PERSONAS.map((p) => p.id));

/** 系统保留、不在角色选择列表中展示（如编译/记忆叠加用的 user_custom.md） */
const HIDDEN_PERSONA_IDS = new Set(["user_custom"]);

type Props = {
  envDraft: EnvMap;
  setEnvDraft: (updater: (prev: EnvMap) => EnvMap) => void;
  serviceRunning: boolean;
  apiBaseUrl: string;
  skillsSection: ReactNode;
  onReady?: (ready: boolean) => void;
};

const PERSONA_TEMPLATE = `## 性格特征

（简要描述）

## 沟通风格

## 提示词片段

## 表情包配置
`;

/** 角色 ID / 文件名主体：允许中文等 Unicode，仅禁止路径与常见非法文件名字符 */
function normalizePersonaId(raw: string): string | null {
  const t = raw.trim();
  if (!t) return null;
  if (/[/\\]/.test(t) || t.includes("..")) return null;
  if (/[<>:"|?*\x00-\x1f]/.test(t)) return null;
  if (t === "." || t === "..") return null;
  if (t.length > 200) return null;
  return t;
}

function PersonaEditorDialog({
  apiBaseUrl,
  serviceRunning,
  personaId,
  open,
  onOpenChange,
}: {
  apiBaseUrl: string;
  serviceRunning: boolean;
  personaId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmWarn, setConfirmWarn] = useState<{ warnings: string[] } | null>(null);

  const fileName = `personas/${personaId}.md`;

  useEffect(() => {
    if (open && serviceRunning) {
      setLoading(true);
      safeFetch(`${apiBaseUrl}/api/identity/file?name=${encodeURIComponent(fileName)}`)
        .then(res => res.json())
        .then(data => {
          if (data.content) {
            setDraft(data.content);
          } else {
            setDraft(PERSONA_TEMPLATE);
          }
        })
        .catch(() => {
          setDraft(PERSONA_TEMPLATE); // Fallback to template if not found or error
        })
        .finally(() => setLoading(false));
    }
  }, [open, serviceRunning, apiBaseUrl, fileName]);

  const trySave = async (force: boolean) => {
    setSaving(true);
    try {
      const res = await safeFetch(`${apiBaseUrl}/api/identity/file`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: fileName, content: draft, force }),
      });
      const data = await res.json();
      if (data.saved) {
        toast.success(t("identity.saved"));
        try {
          await safeFetch(`${apiBaseUrl}/api/identity/reload`, { method: "POST" });
        } catch { /* ignore */ }
        setConfirmWarn(null);
        onOpenChange(false);
        return;
      }
      if (data.needs_confirm && Array.isArray(data.warnings)) {
        setConfirmWarn({ warnings: data.warnings });
        return;
      }
      toast.error(t("identity.saveError"));
    } catch (e) {
      toast.error(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="w-full max-w-[min(96vw,1200px)] sm:max-w-[min(96vw,1200px)] max-h-[90vh] flex flex-col gap-0 p-0 overflow-hidden">
          <DialogHeader className="px-5 pt-5 pb-2 shrink-0">
            <DialogTitle className="text-left font-mono text-sm">{fileName}</DialogTitle>
          </DialogHeader>
          <div className="px-5 pb-4 flex-1 min-h-[320px] overflow-hidden flex flex-col relative">
            {loading && (
              <div className="absolute inset-0 z-10 bg-background/50 flex items-center justify-center">
                <Loader2 className="size-6 animate-spin text-primary" />
              </div>
            )}
            <textarea
              className="flex-1 w-full p-4 rounded-md border bg-muted/50 font-mono text-sm resize-none focus:outline-none focus:ring-1 focus:ring-primary/50"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              spellCheck={false}
              placeholder={t("onboarding.coreAgent.personaEditorPlaceholder")}
            />
          </div>
          <DialogFooter className="px-5 py-4 border-t shrink-0">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="button" onClick={() => void trySave(false)} disabled={saving || loading}>
              {saving ? <Loader2 className="size-4 animate-spin mr-1" /> : null}
              {t("identity.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={!!confirmWarn} onOpenChange={() => setConfirmWarn(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("identity.confirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <ul className="list-disc pl-5 text-sm space-y-1">
                {confirmWarn?.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("identity.confirmCancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={() => void trySave(true)}>{t("identity.confirmSave")}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function TaskCard({
  title,
  desc,
  icon: Icon,
  done,
  onClick,
}: {
  title: string;
  desc: string;
  icon: ComponentType<{ className?: string }>;
  done: boolean;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      onClick={onClick}
      className={`relative flex items-center justify-between p-4 rounded-xl border transition-all cursor-pointer hover:bg-accent/50 ${done ? "border-emerald-500/30 bg-emerald-500/5" : "border-border bg-card"}`}
    >
      <div className="flex items-center gap-4">
        <div className={`p-2 rounded-lg ${done ? "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400" : "bg-primary/10 text-primary"}`}>
          <Icon className="size-5" />
        </div>
        <div>
          <h4 className="font-medium text-sm text-foreground">{title}</h4>
          <p className="text-xs text-muted-foreground mt-0.5">{desc}</p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {done ? (
          <span className="text-xs font-medium text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
            <CheckCircle2 className="size-4" /> {t("onboarding.coreAgent.taskStatusDone")}
          </span>
        ) : (
          <span className="text-xs font-medium text-muted-foreground">{t("onboarding.coreAgent.taskStatusTodo")}</span>
        )}
        <ChevronRight className="size-4 text-muted-foreground/50" />
      </div>
    </div>
  );
}

type TaskId = "persona" | "core" | "memory" | "behavior" | "skills";

export function OnboardingCoreAgentPanel(props: Props) {
  const { t } = useTranslation();
  const {
    envDraft,
    setEnvDraft,
    serviceRunning,
    apiBaseUrl,
    skillsSection,
    onReady,
  } = props;

  const [taskDone, setTaskDone] = useState<Record<TaskId, boolean>>({
    persona: false,
    core: false,
    memory: false,
    behavior: false,
    skills: false,
  });

  const [activeTask, setActiveTask] = useState<TaskId | null>(null);

  useEffect(() => {
    const isReady = Object.values(taskDone).every((v) => v);
    if (onReady) onReady(isReady);
  }, [taskDone, onReady]);

  const markDone = (taskId: TaskId) => {
    setTaskDone((prev) => ({ ...prev, [taskId]: true }));
    setActiveTask(null);
  };

  const _envBase = { envDraft, onEnvChange: setEnvDraft };
  const FT = (p: any) => <FieldText key={p.k} {...p} {..._envBase} />;
  const FB = (p: any) => <FieldBool key={p.k} {...p} {..._envBase} />;
  const FS = (p: any) => <FieldSelect key={p.k} {...p} {..._envBase} />;

  /** 磁盘上已有、且不在预设列表里的 personas/{id}.md（由 API 扫描 + 导入/新建时合并） */
  const [extraPersonas, setExtraPersonas] = useState<{ id: string }[]>([]);

  const loadExtraPersonasFromApi = useCallback(async () => {
    if (!serviceRunning || !apiBaseUrl) return;
    try {
      const res = await safeFetch(`${apiBaseUrl}/api/identity/files`);
      const data = await res.json();
      const list = (data.files || []) as { name: string }[];
      const slugs = list
        .filter((f) => f.name.startsWith("personas/") && f.name.endsWith(".md"))
        .map((f) => f.name.replace(/^personas\//, "").replace(/\.md$/, ""))
        .filter((slug) => slug && !DEFAULT_PERSONA_ID_SET.has(slug) && !HIDDEN_PERSONA_IDS.has(slug));
      slugs.sort((a, b) => a.localeCompare(b));
      setExtraPersonas(slugs.map((id) => ({ id })));
    } catch {
      /* 后端未就绪时忽略 */
    }
  }, [serviceRunning, apiBaseUrl]);

  useEffect(() => {
    void loadExtraPersonasFromApi();
  }, [loadExtraPersonasFromApi]);

  const personas = [...DEFAULT_PERSONAS, ...extraPersonas.map((e) => ({ id: e.id, desc: e.id }))];

  const personaLabel = (p: { id: string; desc: string }) =>
    DEFAULT_PERSONA_ID_SET.has(p.id) ? t(p.desc) : p.id;
  
  const curPersona = envGet(envDraft, "PERSONA_NAME", "default");
  const [editorOpen, setEditorOpen] = useState(false);
  const [newPersonaOpen, setNewPersonaOpen] = useState(false);
  const [newPersonaSlug, setNewPersonaSlug] = useState("");
  const [creating, setCreating] = useState(false);
  const [deletePersonaId, setDeletePersonaId] = useState<string | null>(null);
  const [deletingPersona, setDeletingPersona] = useState(false);

  const createNewPersona = async () => {
    const slug = normalizePersonaId(newPersonaSlug);
    if (!slug) {
      toast.error(t("onboarding.coreAgent.personaSlugInvalid"));
      return;
    }
    const fileName = `personas/${slug}.md`;
    setCreating(true);
    try {
      let initialContent = PERSONA_TEMPLATE;
      try {
        const defRes = await safeFetch(
          `${apiBaseUrl}/api/identity/file?name=${encodeURIComponent("personas/default.md")}`,
        );
        if (defRes.ok) {
          const defData = await defRes.json();
          if (typeof defData.content === "string" && defData.content.trim().length > 0) {
            initialContent = defData.content;
          }
        }
      } catch {
        /* 无 default.md 时仍用模板 */
      }

      const res = await safeFetch(`${apiBaseUrl}/api/identity/file`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: fileName, content: initialContent, force: true }),
      });
      const data = await res.json();
      if (data.saved) {
        toast.success(t("onboarding.coreAgent.personaCreated"));
        try { await safeFetch(`${apiBaseUrl}/api/identity/reload`, { method: "POST" }); } catch { /* ignore */ }
        void loadExtraPersonasFromApi();
        setEnvDraft((m) => envSet(m, "PERSONA_NAME", slug));
        setNewPersonaOpen(false);
        setNewPersonaSlug("");
        setEditorOpen(true);
      } else {
        toast.error(t("identity.saveError"));
      }
    } catch (e) {
      toast.error(String(e));
    } finally {
      setCreating(false);
    }
  };
  
  const [importing, setImporting] = useState(false);
  const handleImportPersona = async () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".md";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      setImporting(true);
      try {
        const formData = new FormData();
        formData.append("file", file);
        const res = await safeFetch(`${apiBaseUrl}/api/identity/persona/import`, {
          method: "POST",
          body: formData,
        });
        const data = await res.json();
        if (data.persona_id) {
          const pid = String(data.persona_id);
          setEnvDraft((m) => envSet(m, "PERSONA_NAME", pid));
          if (!DEFAULT_PERSONA_ID_SET.has(pid) && !HIDDEN_PERSONA_IDS.has(pid)) {
            setExtraPersonas((prev) => {
              if (prev.some((x) => x.id === pid)) return prev;
              return [...prev, { id: pid }].sort((a, b) => a.id.localeCompare(b.id));
            });
          }
          void loadExtraPersonasFromApi();
          toast.success(t("config.personaImportSuccess", { name: pid }));
        }
      } catch (e: any) {
        toast.error(t("config.personaImportError") + ": " + (e.message || "Unknown error"));
      } finally {
        setImporting(false);
      }
    };
    input.click();
  };

  const confirmDeletePersona = async () => {
    if (!deletePersonaId || !serviceRunning) return;
    const id = deletePersonaId;
    setDeletingPersona(true);
    try {
      const res = await safeFetch(
        `${apiBaseUrl}/api/identity/file?name=${encodeURIComponent(`personas/${id}.md`)}`,
        { method: "DELETE" },
      );
      const data = (await res.json().catch(() => ({}))) as { detail?: string | { msg?: string }[] };
      if (!res.ok) {
        let msg = t("onboarding.coreAgent.deletePersonaFailed");
        if (typeof data.detail === "string") msg = data.detail;
        toast.error(msg);
        return;
      }
      toast.success(t("onboarding.coreAgent.deletePersonaSuccess", { name: id }));
      try {
        await safeFetch(`${apiBaseUrl}/api/identity/reload`, { method: "POST" });
      } catch {
        /* ignore */
      }
      setExtraPersonas((prev) => prev.filter((x) => x.id !== id));
      if (envGet(envDraft, "PERSONA_NAME", "default") === id) {
        setEnvDraft((m) => envSet(m, "PERSONA_NAME", "default"));
      }
      void loadExtraPersonasFromApi();
      setDeletePersonaId(null);
    } catch (e) {
      toast.error(String(e));
    } finally {
      setDeletingPersona(false);
    }
  };

  return (
    <div className="w-full max-w-3xl mx-auto text-left space-y-4">
      <div>
        <h2 className="obStepTitle m-0 flex items-center gap-2.5">
          <img src={logoUrl} alt="" className="size-9 shrink-0 rounded-xl shadow-sm" draggable={false} />
          <span>{t("onboarding.coreAgent.pageTitle")}</span>
        </h2>
        <p className="obStepDesc">{t("onboarding.coreAgent.pageSubtitle")}</p>
      </div>

      <div className="grid gap-3">
        <TaskCard
          title={t("onboarding.coreAgent.taskPersonaTitle")}
          desc={t("onboarding.coreAgent.taskPersonaDesc")}
          icon={MessageSquareQuote}
          done={taskDone.persona}
          onClick={() => setActiveTask("persona")}
        />
        <TaskCard
          title={t("onboarding.coreAgent.taskCoreTitle")}
          desc={t("onboarding.coreAgent.taskCoreDesc")}
          icon={Cpu}
          done={taskDone.core}
          onClick={() => setActiveTask("core")}
        />
        <TaskCard
          title={t("onboarding.coreAgent.taskMemoryTitle")}
          desc={t("onboarding.coreAgent.taskMemoryDesc")}
          icon={Bot}
          done={taskDone.memory}
          onClick={() => setActiveTask("memory")}
        />
        <TaskCard
          title={t("onboarding.coreAgent.taskBehaviorTitle")}
          desc={t("onboarding.coreAgent.taskBehaviorDesc")}
          icon={Zap}
          done={taskDone.behavior}
          onClick={() => setActiveTask("behavior")}
        />
        <TaskCard
          title={t("onboarding.coreAgent.taskSkillsTitle")}
          desc={t("onboarding.coreAgent.taskSkillsDesc")}
          icon={Puzzle}
          done={taskDone.skills}
          onClick={() => setActiveTask("skills")}
        />
      </div>

      <Dialog open={activeTask !== null} onOpenChange={(open) => !open && setActiveTask(null)}>
        <DialogContent className="w-full min-w-0 max-w-[min(98vw,1320px)] sm:max-w-[min(98vw,1320px)] max-h-[90vh] overflow-y-auto overflow-x-hidden">
          {activeTask === "persona" && (
            <>
              <DialogHeader>
                <DialogTitle>{t("onboarding.coreAgent.dialogPersonaTitle")}</DialogTitle>
              </DialogHeader>
              <div className="space-y-4 py-2">
                <div className="space-y-4">
                  <div>
                    <div className="text-sm font-medium mb-3">{t("onboarding.coreAgent.selectPresetLabel")}</div>
                    <ToggleGroup
                      type="single"
                      variant="outline"
                      value={DEFAULT_PERSONA_ID_SET.has(curPersona) ? curPersona : ""}
                      onValueChange={(val) => {
                        if (val) setEnvDraft((m) => envSet(m, "PERSONA_NAME", val));
                      }}
                      className="flex-wrap justify-start"
                    >
                      {DEFAULT_PERSONAS.map((p) => (
                        <ToggleGroupItem
                          key={p.id}
                          value={p.id}
                          className="text-sm min-w-[5.5rem] data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:border-primary"
                        >
                          {personaLabel(p)}
                        </ToggleGroupItem>
                      ))}
                    </ToggleGroup>
                  </div>
                  {extraPersonas.length > 0 && (
                    <div className="pt-2">
                      <div className="text-xs font-medium text-muted-foreground mb-3">
                        {t("onboarding.coreAgent.customPersonasLabel")}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {extraPersonas.map((e) => {
                          const isActive = curPersona === e.id;
                          return (
                            <div
                              key={e.id}
                              className="group/persona relative inline-flex overflow-visible"
                            >
                              <button
                                type="button"
                                className={cn(
                                  "min-w-[6.5rem] px-3.5 h-7 text-xs rounded-md border transition-all inline-flex items-center justify-center",
                                  isActive
                                    ? "bg-primary text-primary-foreground border-primary shadow-sm"
                                    : "bg-background text-foreground border-input hover:bg-muted"
                                )}
                                onClick={() => setEnvDraft((m) => envSet(m, "PERSONA_NAME", e.id))}
                              >
                                {e.id}
                              </button>

                              <button
                                type="button"
                                className={cn(
                                  "absolute -top-1 -right-1 z-20 hidden size-3 items-center justify-center rounded-full bg-red-600 text-white shadow-sm",
                                  "group-hover/persona:flex",
                                  (!serviceRunning || deletingPersona) && "pointer-events-none opacity-40",
                                )}
                                disabled={!serviceRunning || deletingPersona}
                                title={t("onboarding.coreAgent.deletePersona")}
                                onClick={(ev) => {
                                  ev.stopPropagation();
                                  setDeletePersonaId(e.id);
                                }}
                              >
                                <span
                                  className="block translate-y-px text-[10px] font-bold leading-none text-white"
                                  aria-hidden
                                >
                                  ×
                                </span>
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  {(curPersona === "custom" ||
                    (!personas.find((p) => p.id === curPersona) && curPersona !== "default")) && (
                    <Input
                      className="max-w-[300px] mt-2"
                      placeholder={t("config.agentCustomId")}
                      value={curPersona === "custom" ? "" : curPersona}
                      onChange={(e) => setEnvDraft((m) => envSet(m, "PERSONA_NAME", e.target.value || "custom"))}
                    />
                  )}
                  <p className="text-xs text-muted-foreground mt-2">
                    {t("onboarding.coreAgent.personaBindingHint")}
                  </p>
                  <div className="flex items-center gap-2 mt-4">
                    <Button size="sm" variant="secondary" onClick={() => setEditorOpen(true)} disabled={!serviceRunning} className="text-xs h-8">
                      <Edit3 size={14} className="mr-1.5" />
                      {t("onboarding.coreAgent.editCurrentPersona")}
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => setNewPersonaOpen(true)} disabled={!serviceRunning} className="text-xs h-8">
                      <Plus size={14} className="mr-1.5" />
                      {t("onboarding.coreAgent.newPersonaShort")}
                    </Button>
                    <Button size="sm" variant="outline" onClick={handleImportPersona} disabled={importing || !serviceRunning} className="text-xs h-8">
                      {importing ? <Loader2 size={14} className="animate-spin mr-1.5" /> : <Upload size={14} className="mr-1.5" />}
                      {t("onboarding.coreAgent.importShort")}
                    </Button>
                  </div>
                </div>
                
                <PersonaEditorDialog
                  apiBaseUrl={apiBaseUrl}
                  serviceRunning={serviceRunning}
                  personaId={curPersona === "custom" || !curPersona ? "custom" : curPersona}
                  open={editorOpen}
                  onOpenChange={setEditorOpen}
                />
                
                <Dialog open={newPersonaOpen} onOpenChange={setNewPersonaOpen}>
                  <DialogContent className="max-w-sm">
                    <DialogHeader>
                      <DialogTitle>{t("onboarding.coreAgent.newPersonaTitle")}</DialogTitle>
                    </DialogHeader>
                    <Input
                      placeholder={t("onboarding.coreAgent.newPersonaPlaceholder")}
                      value={newPersonaSlug}
                      onChange={(e) => setNewPersonaSlug(e.target.value)}
                    />
                    <DialogFooter>
                      <Button variant="outline" onClick={() => setNewPersonaOpen(false)}>{t("common.cancel")}</Button>
                      <Button onClick={() => void createNewPersona()} disabled={creating}>
                        {creating ? <Loader2 className="size-4 animate-spin mr-1" /> : null}
                        {t("common.confirm")}
                      </Button>
                    </DialogFooter>
                  </DialogContent>
                </Dialog>

                <AlertDialog open={deletePersonaId !== null} onOpenChange={(open) => !open && !deletingPersona && setDeletePersonaId(null)}>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>{t("onboarding.coreAgent.deletePersonaTitle")}</AlertDialogTitle>
                      <AlertDialogDescription>
                        {t("onboarding.coreAgent.deletePersonaDesc", { name: deletePersonaId ?? "" })}
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel disabled={deletingPersona}>{t("common.cancel")}</AlertDialogCancel>
                      <Button
                        variant="destructive"
                        disabled={deletingPersona}
                        onClick={() => void confirmDeletePersona()}
                      >
                        {deletingPersona ? <Loader2 className="size-4 animate-spin mr-1 inline" /> : null}
                        {t("common.delete")}
                      </Button>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
              <DialogFooter>
                <Button onClick={() => markDone("persona")}>{t("onboarding.coreAgent.confirmTaskDone")}</Button>
              </DialogFooter>
            </>
          )}

          {activeTask === "core" && (
            <>
              <DialogHeader>
                <DialogTitle>{t("onboarding.coreAgent.dialogCoreTitle")}</DialogTitle>
              </DialogHeader>
              <div className="grid gap-4 sm:grid-cols-2 py-4">
                {FT({ k: "AGENT_NAME", label: t("config.agentName"), placeholder: "Synapse" })}
                {FT({ k: "MAX_ITERATIONS", label: t("config.agentMaxIter"), placeholder: "300", help: t("config.agentMaxIterHelp") })}
                <div className="col-span-full">
                  {FS({ k: "THINKING_MODE", label: t("config.agentThinking"), options: [
                    { value: "auto", label: t("config.agentThinkingAuto") },
                    { value: "always", label: t("config.agentThinkingAlways") },
                    { value: "never", label: t("config.agentThinkingNever") },
                  ] })}
                </div>
              </div>
              <DialogFooter>
                <Button onClick={() => markDone("core")}>{t("onboarding.coreAgent.confirmTaskDone")}</Button>
              </DialogFooter>
            </>
          )}

          {activeTask === "memory" && (
            <>
              <DialogHeader>
                <DialogTitle>{t("onboarding.coreAgent.dialogMemoryTitle")}</DialogTitle>
              </DialogHeader>
              <div className="py-4 space-y-4">
                {FS({
                  k: "MEMORY_MODE",
                  label: t("config.memoryModeLabel"),
                  help: t("config.memoryModeHelp"),
                  options: [
                    { value: "mode1", label: t("config.memoryModeMode1") },
                    { value: "mode2", label: t("config.memoryModeMode2") },
                    { value: "auto", label: t("config.memoryModeAuto") },
                  ],
                })}
              </div>
              <DialogFooter>
                <Button onClick={() => markDone("memory")}>{t("onboarding.coreAgent.confirmTaskDone")}</Button>
              </DialogFooter>
            </>
          )}

          {activeTask === "behavior" && (
            <>
              <DialogHeader>
                <DialogTitle>{t("onboarding.coreAgent.dialogBehaviorTitle")}</DialogTitle>
              </DialogHeader>
              <div className="py-4 space-y-6">
                <div>
                  <h4 className="text-sm font-semibold mb-3">{t("onboarding.coreAgent.sectionProactive")}</h4>
                  <div className="grid gap-4 sm:grid-cols-3">
                    {FT({ k: "PROACTIVE_MAX_DAILY_MESSAGES", label: t("config.agentMaxDaily"), placeholder: "3" })}
                    {FT({ k: "PROACTIVE_MIN_INTERVAL_MINUTES", label: t("config.agentMinInterval"), placeholder: "120" })}
                    {FT({ k: "PROACTIVE_IDLE_THRESHOLD_HOURS", label: t("config.agentIdleThreshold"), placeholder: "24" })}
                  </div>
                </div>
                <div>
                  <h4 className="text-sm font-semibold mb-3">{t("onboarding.coreAgent.sectionQuietHours")}</h4>
                  <div className="grid gap-4 sm:grid-cols-2">
                    {FT({ k: "PROACTIVE_QUIET_HOURS_START", label: t("config.agentQuietStart"), placeholder: "23" })}
                    {FT({ k: "PROACTIVE_QUIET_HOURS_END", label: t("config.agentQuietEnd"), placeholder: "7" })}
                  </div>
                </div>
                <div className="pt-2 border-t">
                  <h4 className="text-sm font-semibold mb-3">{t("onboarding.coreAgent.sectionStickers")}</h4>
                  <div className="grid gap-4 sm:grid-cols-2">
                    {FB({ k: "STICKER_ENABLED", label: t("config.agentSticker") })}
                    {FT({ k: "STICKER_DATA_DIR", label: t("config.agentStickerDir"), placeholder: "data/sticker" })}
                  </div>
                </div>
              </div>
              <DialogFooter>
                <Button onClick={() => markDone("behavior")}>{t("onboarding.coreAgent.confirmTaskDone")}</Button>
              </DialogFooter>
            </>
          )}

          {activeTask === "skills" && (
            <>
              <DialogHeader>
                <DialogTitle>{t("onboarding.coreAgent.dialogSkillsTitle")}</DialogTitle>
              </DialogHeader>
              <div className="py-2 min-w-0">{skillsSection}</div>
              <DialogFooter>
                <Button onClick={() => markDone("skills")}>{t("onboarding.coreAgent.confirmTaskDone")}</Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
