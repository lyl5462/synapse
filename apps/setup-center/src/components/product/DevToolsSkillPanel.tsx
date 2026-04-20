/**
 * 工作台 → 研发工具：仅展示 tool_name 以 whalecloud_dev_tool_ 开头的技能，
 * 与「能力 → 技能」解耦，不修改 SkillManager。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Play, Plus } from "lucide-react";
import { invoke, IS_TAURI } from "../../platform";
import type { SkillInfo, SkillConfigField, EnvMap } from "../../types";
import { envSet } from "../../utils";
import { isWhalecloudDevToolSkill } from "../../utils/whalecloudDevToolSkill";
import { safeFetch } from "../../providers";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { ModalOverlay } from "../ModalOverlay";
import { IconGear, IconZap, IconSearch, IconTrash, IconX, IconEdit } from "../../icons";
import { SkillCard } from "../../views/SkillManager";

type ErrorCtx = "load" | "save" | "uninstall" | "reload" | "general";

function friendlyErr(e: unknown, t: (k: string) => string, ctx: ErrorCtx = "general"): string {
  const raw = e instanceof Error ? e.message : String(e);
  if (/AbortError|signal timed out|timeout/i.test(raw)) return t("skills.errorTimeout");
  if (/Failed to fetch|NetworkError|ECONNREFUSED|net::|ERR_CONNECTION|Load failed/i.test(raw)) {
    return t("skills.errorNetwork");
  }
  if (/\b50[0-9]\b|Internal Server Error/i.test(raw)) return t("skills.errorServer");
  const m: Record<ErrorCtx, string> = {
    load: "skills.errorLoadFailed",
    save: "skills.errorSaveFailed",
    uninstall: "skills.errorUninstallFailed",
    reload: "skills.errorReloadFailed",
    general: "skills.errorUnknown",
  };
  return t(m[ctx]);
}

function dispName(skill: SkillInfo, lang: string): string {
  const k = lang.startsWith("zh") ? "zh" : lang;
  return skill.name_i18n?.[k] || skill.name;
}

function dispDesc(skill: SkillInfo, lang: string): string {
  const k = lang.startsWith("zh") ? "zh" : lang;
  return skill.description_i18n?.[k] || skill.description;
}

function DevToolsDetailModal({
  skill,
  content,
  contentLoading,
  contentError,
  isEditing,
  editContent,
  savingContent,
  isSystem,
  serviceRunning,
  onClose,
  onStartEdit,
  onCancelEdit,
  onEditChange,
  onSave,
  onUninstall,
  uninstalling,
}: {
  skill: SkillInfo;
  content: string;
  contentLoading: boolean;
  contentError: string | null;
  isEditing: boolean;
  editContent: string;
  savingContent: boolean;
  isSystem: boolean;
  serviceRunning: boolean;
  onClose: () => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onEditChange: (v: string) => void;
  onSave: () => void;
  onUninstall?: () => void;
  uninstalling?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language || "zh";
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (isEditing && textareaRef.current) textareaRef.current.focus();
  }, [isEditing]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !savingContent) onClose();
    };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose, savingContent]);

  return (
    <ModalOverlay onClose={savingContent ? () => {} : onClose}>
      <div
        className="modalContent"
        style={{ maxWidth: 720, width: "90vw", maxHeight: "85vh", display: "flex", flexDirection: "column", padding: 0 }}
      >
        <div style={{ padding: "18px 24px 14px", borderBottom: "1px solid var(--line)", flexShrink: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ width: 32, height: 32, borderRadius: 8, background: isSystem ? "rgba(37,99,235,0.1)" : "rgba(124,58,237,0.1)", display: "grid", placeItems: "center", flexShrink: 0 }}>
              {isSystem ? <IconGear size={16} /> : <IconZap size={16} />}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 800, fontSize: 15 }}>{dispName(skill, lang)}</div>
              <div style={{ fontSize: 12, opacity: 0.6, marginTop: 2 }}>{dispDesc(skill, lang)}</div>
            </div>
            <Button variant="ghost" size="icon-xs" onClick={onClose} disabled={savingContent}>
              <IconX size={18} />
            </Button>
          </div>
          <div style={{ display: "flex", gap: 16, marginTop: 12, fontSize: 12, opacity: 0.6, flexWrap: "wrap" }}>
            <span><b>{t("skills.skillType")}:</b> {isSystem ? t("skills.system") : t("skills.external")}</span>
            {skill.category && <span><b>{t("skills.skillCategory")}:</b> {skill.category}</span>}
            {!isSystem && skill.sourceUrl && (
              <span style={{ fontFamily: "monospace", fontSize: 11, opacity: 0.8 }}>
                <b>{t("skills.source")}:</b> {skill.sourceUrl}
              </span>
            )}
            {skill.path && (
              <span style={{ fontFamily: "monospace", fontSize: 11, opacity: 0.8, wordBreak: "break-all" }}>
                <b>{t("skills.filePath")}:</b> {skill.path}
              </span>
            )}
          </div>
        </div>
        <div style={{ flex: 1, overflow: "auto", padding: "16px 24px" }}>
          {contentLoading ? (
            <div style={{ textAlign: "center", padding: 40, opacity: 0.5 }}>{t("skills.loadingContent")}</div>
          ) : contentError ? (
            <div className="errorBox" style={{ margin: 0 }}>{contentError}</div>
          ) : isEditing ? (
            <textarea
              ref={textareaRef}
              value={editContent}
              onChange={(e) => onEditChange(e.target.value)}
              spellCheck={false}
              style={{
                width: "100%",
                minHeight: 400,
                fontFamily: "monospace",
                fontSize: 13,
                lineHeight: 1.6,
                padding: 12,
                border: "1px solid var(--brand)",
                borderRadius: 8,
                background: "var(--panel2)",
                color: "var(--text)",
                resize: "vertical",
                outline: "none",
                tabSize: 2,
              }}
            />
          ) : (
            <pre style={{
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontFamily: "monospace",
              fontSize: 13,
              lineHeight: 1.6,
              margin: 0,
              padding: 12,
              background: "var(--panel2)",
              borderRadius: 8,
              border: "1px solid var(--line)",
              minHeight: 200,
            }}>
              {content}
            </pre>
          )}
        </div>
        <div style={{
          padding: "12px 24px 18px",
          borderTop: "1px solid var(--line)",
          display: "flex",
          alignItems: "center",
          gap: 8,
          flexShrink: 0,
        }}>
          {isSystem && (
            <span style={{ fontSize: 12, opacity: 0.5, flex: 1 }}>{t("skills.readOnlyHint")}</span>
          )}
          {!isSystem && !serviceRunning && (
            <span style={{ fontSize: 12, opacity: 0.5, flex: 1 }}>{t("skills.requiresBackend")}</span>
          )}
          {!isSystem && serviceRunning && (
            <>
              {onUninstall && !isEditing && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={onUninstall}
                  disabled={uninstalling || savingContent}
                  className="text-destructive border-destructive/30 hover:bg-destructive/10 hover:text-destructive"
                >
                  {uninstalling ? <Loader2 className="animate-spin" size={12} /> : <IconTrash size={12} />} {t("skills.uninstall")}
                </Button>
              )}
              <div style={{ flex: 1 }} />
              {isEditing ? (
                <>
                  <Button variant="outline" size="sm" onClick={onCancelEdit} disabled={savingContent}>
                    {t("skills.cancelEdit")}
                  </Button>
                  <Button size="sm" onClick={onSave} disabled={savingContent || editContent === content}>
                    {savingContent && <Loader2 className="animate-spin" />}
                    {t("skills.saveAndReload")}
                  </Button>
                </>
              ) : (
                <Button variant="outline" size="sm" onClick={onStartEdit} disabled={contentLoading || !!contentError}>
                  <IconEdit size={12} /> {t("skills.editContent")}
                </Button>
              )}
            </>
          )}
        </div>
      </div>
    </ModalOverlay>
  );
}

export function DevToolsSkillPanel({
  venvDir,
  currentWorkspaceId,
  envDraft,
  onEnvChange,
  onSaveEnvKeys,
  apiBaseUrl = "http://127.0.0.1:18900",
  serviceRunning = false,
  dataMode = "local",
}: {
  venvDir: string;
  currentWorkspaceId: string | null;
  envDraft: EnvMap;
  onEnvChange: (fn: (prev: EnvMap) => EnvMap) => void;
  onSaveEnvKeys: (keys: string[]) => Promise<void>;
  apiBaseUrl?: string;
  serviceRunning?: boolean;
  dataMode?: "local" | "remote";
}) {
  const { t } = useTranslation();
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedSkill, setExpandedSkill] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [enabledDraft, setEnabledDraft] = useState<Record<string, boolean>>({});
  const [enabledDirty, setEnabledDirty] = useState(false);
  const [savingEnabled, setSavingEnabled] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [installedSearch, setInstalledSearch] = useState("");
  const [detailSkill, setDetailSkill] = useState<SkillInfo | null>(null);
  const [detailContent, setDetailContent] = useState("");
  const [detailContentLoading, setDetailContentLoading] = useState(false);
  const [detailContentError, setDetailContentError] = useState<string | null>(null);
  const [detailEditing, setDetailEditing] = useState(false);
  const [detailEditContent, setDetailEditContent] = useState("");
  const [detailSaving, setDetailSaving] = useState(false);
  const [uninstallingSet, setUninstallingSet] = useState<Set<string>>(new Set());
  const [uninstallConfirm, setUninstallConfirm] = useState<SkillInfo | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const detailRequestNameRef = useRef<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createSlug, setCreateSlug] = useState("");
  const [createNameZh, setCreateNameZh] = useState("");
  const [createNameEn, setCreateNameEn] = useState("");
  const [createDescZh, setCreateDescZh] = useState("");
  const [createDescEn, setCreateDescEn] = useState("");
  const [createSubmitting, setCreateSubmitting] = useState(false);

  const loadSkills = useCallback(async (): Promise<boolean> => {
    setLoading(true);
    setError(null);
    try {
      let data: { skills: Record<string, unknown>[] } | null = null;
      let httpError: string | null = null;
      if (serviceRunning && apiBaseUrl != null) {
        try {
          const res = await safeFetch(`${apiBaseUrl}/api/skills`, { signal: AbortSignal.timeout(15_000) });
          data = await res.json();
        } catch (e) {
          httpError = String(e);
        }
      }
      if (!data && IS_TAURI && dataMode !== "remote" && venvDir && currentWorkspaceId) {
        try {
          const raw = await invoke<string>("synapse_list_skills", { venvDir, workspaceId: currentWorkspaceId });
          data = JSON.parse(raw);
        } catch {
          if (httpError) {
            setError(friendlyErr(httpError, t, "load"));
            return false;
          }
        }
      }
      if (!data) {
        setSkills([]);
        return !httpError;
      }
      const list: SkillInfo[] = (data.skills || []).map((s: Record<string, unknown>) => ({
        skillId: (s.skill_id as string) || (s.name as string),
        name: s.name as string,
        description: (s.description as string) || "",
        name_i18n: (s.name_i18n as Record<string, string> | null) || null,
        description_i18n: (s.description_i18n as Record<string, string> | null) || null,
        system: (s.system as boolean) || false,
        enabled: s.enabled as boolean | undefined,
        toolName: s.tool_name as string | null,
        category: s.category as string | null,
        path: s.path as string | null,
        sourceUrl: (s.source_url as string | null) || null,
        config: (s.config as SkillConfigField[] | null) || null,
        configComplete: true,
      }));
      setSkills(list);
      const draft: Record<string, boolean> = {};
      for (const s of list) draft[s.skillId] = s.enabled !== false;
      setEnabledDraft(draft);
      setEnabledDirty(false);
      return true;
    } catch (e) {
      setError(friendlyErr(e, t, "load"));
      return false;
    } finally {
      setLoading(false);
    }
  }, [venvDir, currentWorkspaceId, serviceRunning, apiBaseUrl, dataMode, t]);

  useEffect(() => {
    loadSkills();
  }, [loadSkills]);

  function checkConfigComplete(config: SkillConfigField[] | null | undefined, env: EnvMap): boolean {
    if (!config || config.length === 0) return true;
    return config.filter((f) => f.required).every((f) => {
      const v = env[f.key];
      return v != null && v.trim() !== "";
    });
  }

  const skillsWithConfig = useMemo(() =>
    skills.map((s) => ({
      ...s,
      enabled: enabledDraft[s.skillId] ?? (s.enabled !== false),
      configComplete: checkConfigComplete(s.config, envDraft),
    })),
    [skills, envDraft, enabledDraft],
  );

  const devOnly = useMemo(
    () => skillsWithConfig.filter(isWhalecloudDevToolSkill),
    [skillsWithConfig],
  );

  const filtered = useMemo(() => {
    const q = installedSearch.trim().toLowerCase();
    if (!q) return devOnly;
    return devOnly.filter((s) => {
      if (s.name.toLowerCase().includes(q)) return true;
      if (s.description?.toLowerCase().includes(q)) return true;
      if (s.category?.toLowerCase().includes(q)) return true;
      if (s.toolName?.toLowerCase().includes(q)) return true;
      return false;
    });
  }, [devOnly, installedSearch]);

  const handleSaveConfig = useCallback(async (skill: SkillInfo) => {
    if (!skill.config) return;
    setSaving(true);
    try {
      for (const f of skill.config) {
        if (f.default != null) {
          onEnvChange((m) => {
            if (Object.prototype.hasOwnProperty.call(m, f.key)) return m;
            return envSet(m, f.key, String(f.default));
          });
        }
      }
      await onSaveEnvKeys(skill.config.map((f) => f.key));
      await loadSkills();
    } catch (e) {
      setError(friendlyErr(e, t, "save"));
    } finally {
      setSaving(false);
    }
  }, [onSaveEnvKeys, loadSkills, onEnvChange, t]);

  const handleToggleEnabled = useCallback((skill: SkillInfo) => {
    if (skill.system) return;
    const cur = enabledDraft[skill.skillId] ?? (skill.enabled !== false);
    setEnabledDraft((prev) => ({ ...prev, [skill.skillId]: !cur }));
    setEnabledDirty(true);
  }, [enabledDraft]);

  const handleSaveEnabledState = useCallback(async () => {
    setSavingEnabled(true);
    setError(null);
    try {
      const externalAllowlist = skills
        .filter((s) => !s.system && (enabledDraft[s.skillId] ?? (s.enabled !== false)))
        .map((s) => s.skillId);
      const content = {
        version: 1,
        external_allowlist: externalAllowlist,
        updated_at: new Date().toISOString(),
      };
      if (serviceRunning && apiBaseUrl != null) {
        const res = await safeFetch(`${apiBaseUrl}/api/config/skills`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content }),
          signal: AbortSignal.timeout(5000),
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        try {
          await safeFetch(`${apiBaseUrl}/api/skills/reload`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({}),
            signal: AbortSignal.timeout(10_000),
          });
        } catch { /* ignore */ }
      } else if (IS_TAURI && dataMode !== "remote" && currentWorkspaceId) {
        await invoke("workspace_write_file", {
          workspaceId: currentWorkspaceId,
          relativePath: "data/skills.json",
          content: JSON.stringify(content, null, 2) + "\n",
        });
      }
      setEnabledDirty(false);
      await loadSkills();
    } catch (e) {
      setError(friendlyErr(e, t, "save"));
    } finally {
      setSavingEnabled(false);
    }
  }, [skills, enabledDraft, serviceRunning, apiBaseUrl, dataMode, currentWorkspaceId, loadSkills, t]);

  const handleDiscard = useCallback(() => { loadSkills(); }, [loadSkills]);

  const handleViewDetail = useCallback(async (skill: SkillInfo) => {
    const requestName = skill.skillId;
    detailRequestNameRef.current = requestName;
    setDetailSkill(skill);
    setDetailEditing(false);
    setDetailEditContent("");
    setDetailContentError(null);
    setDetailContent("");
    setDetailContentLoading(true);
    setDetailSaving(false);
    if (!serviceRunning || !apiBaseUrl) {
      setDetailContentError(t("skills.requiresBackend"));
      setDetailContentLoading(false);
      return;
    }
    try {
      const res = await safeFetch(`${apiBaseUrl}/api/skills/content/${encodeURIComponent(skill.skillId)}`, {
        signal: AbortSignal.timeout(10_000),
      });
      if (detailRequestNameRef.current !== requestName) return;
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (detailRequestNameRef.current !== requestName) return;
      if (data.error) setDetailContentError(data.error);
      else setDetailContent(data.content || "");
    } catch (e) {
      if (detailRequestNameRef.current !== requestName) return;
      setDetailContentError(String(e));
    } finally {
      if (detailRequestNameRef.current === requestName) setDetailContentLoading(false);
    }
  }, [serviceRunning, apiBaseUrl, t]);

  const handleCloseDetail = useCallback(() => {
    setDetailSkill(null);
    setDetailEditing(false);
    setDetailEditContent("");
    setDetailContentError(null);
  }, []);

  const handleSaveContent = useCallback(async () => {
    if (!detailSkill || !serviceRunning || !apiBaseUrl) return;
    setDetailSaving(true);
    setDetailContentError(null);
    try {
      const res = await safeFetch(`${apiBaseUrl}/api/skills/content/${encodeURIComponent(detailSkill.skillId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: detailEditContent }),
        signal: AbortSignal.timeout(15_000),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.error) setDetailContentError(data.error);
      else {
        setDetailContent(detailEditContent);
        setDetailEditing(false);
        toast.success(t("skills.contentSaved"));
        await loadSkills();
      }
    } catch (e) {
      setDetailContentError(`${t("skills.contentSaveFailed")}: ${e}`);
    } finally {
      setDetailSaving(false);
    }
  }, [detailSkill, detailEditContent, serviceRunning, apiBaseUrl, loadSkills, t]);

  const requestUninstall = useCallback((skill: SkillInfo) => {
    if (skill.system) return;
    setUninstallConfirm(skill);
  }, []);

  const executeUninstall = useCallback(async (skill: SkillInfo) => {
    const displayName = skill.name_i18n?.zh || skill.name_i18n?.en || skill.name;
    const key = skill.skillId;
    setUninstallingSet((prev) => new Set(prev).add(key));
    setError(null);
    try {
      if (serviceRunning && apiBaseUrl != null) {
        const res = await safeFetch(`${apiBaseUrl}/api/skills/uninstall`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ skill_id: key }),
          signal: AbortSignal.timeout(30_000),
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
      } else if (IS_TAURI && currentWorkspaceId) {
        await invoke<string>("synapse_uninstall_skill", {
          venvDir,
          workspaceId: currentWorkspaceId,
          skillName: key,
        });
      } else {
        throw new Error(t("skills.envNotReady") || "");
      }
      if (detailSkill?.skillId === key) setDetailSkill(null);
      toast.success(t("skills.uninstallSuccess", { name: displayName }));
      await loadSkills();
    } catch (e) {
      const msg = friendlyErr(e, t, "uninstall");
      setError(msg);
      toast.error(msg);
    } finally {
      setUninstallingSet((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  }, [serviceRunning, apiBaseUrl, venvDir, currentWorkspaceId, detailSkill, loadSkills, t]);

  const submitCreateDevTool = useCallback(async () => {
    if (!serviceRunning || !apiBaseUrl) return;
    const slug = createSlug.trim().toLowerCase();
    if (!slug) {
      toast.error(t("skills.devToolsCreateSlugHint"));
      return;
    }
    setCreateSubmitting(true);
    try {
      const res = await safeFetch(`${apiBaseUrl}/api/skills/dev-tools/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          slug,
          name_zh: createNameZh.trim(),
          name_en: createNameEn.trim(),
          description_zh: createDescZh.trim(),
          description_en: createDescEn.trim(),
        }),
        signal: AbortSignal.timeout(30_000),
      });
      const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        const msg =
          (typeof data.message === "string" && data.message) ||
          (typeof data.error === "string" && data.error) ||
          res.statusText;
        toast.error(`${t("skills.devToolsCreateError")}: ${msg}`);
        return;
      }
      toast.success(t("skills.devToolsCreateSuccess"));
      setCreateOpen(false);
      setCreateSlug("");
      setCreateNameZh("");
      setCreateNameEn("");
      setCreateDescZh("");
      setCreateDescEn("");
      await loadSkills();
    } catch (e) {
      toast.error(`${t("skills.devToolsCreateError")}: ${friendlyErr(e, t, "general")}`);
    } finally {
      setCreateSubmitting(false);
    }
  }, [
    serviceRunning,
    apiBaseUrl,
    createSlug,
    createNameZh,
    createNameEn,
    createDescZh,
    createDescEn,
    loadSkills,
    t,
  ]);

  const runDevToolTest = useCallback(async (skill: SkillInfo) => {
    if (!serviceRunning || !apiBaseUrl) return;
    setTestingId(skill.skillId);
    try {
      const res = await safeFetch(`${apiBaseUrl}/api/skills/dev-tools/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skill_id: skill.skillId, message: "" }),
        signal: AbortSignal.timeout(240_000),
      });
      const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        const detail = typeof data.detail === "string" ? data.detail : (data.message as string) || res.statusText;
        toast.error(detail || t("skills.devToolsTestFailed"));
        return;
      }
      if (data.success === true) toast.success(t("skills.devToolsTestDone"));
      else toast.error((typeof data.error === "string" ? data.error : "") || t("skills.devToolsTestFailed"));
    } catch (e) {
      toast.error(friendlyErr(e, t, "general"));
    } finally {
      setTestingId(null);
    }
  }, [serviceRunning, apiBaseUrl, t]);

  if (!serviceRunning) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
        <IconZap size={48} />
        <div className="mt-3 font-semibold">{t("skills.devToolsTitle")}</div>
        <div className="mt-1 text-xs opacity-50">{t("skills.backendOfflineHint")}</div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-6">
      <div className="flex flex-col md:flex-row md:items-center gap-4">
        <div className="flex flex-col gap-1 min-w-0">
          <h2 className="text-lg font-semibold tracking-tight">{t("skills.devToolsTitle")}</h2>
          <p className="text-sm text-muted-foreground max-w-2xl">{t("skills.devToolsSubtitle")}</p>
        </div>
        <div className="flex-1 min-w-0" />
        <div className="flex flex-wrap gap-2 justify-end w-full md:w-auto">
          <Button
            variant="default"
            disabled={refreshing || loading || createSubmitting}
            className="w-full sm:w-auto"
            onClick={() => setCreateOpen(true)}
          >
            <Plus className="size-4 mr-1.5" />
            {t("skills.devToolsCreate")}
          </Button>
        <Button
          variant="outline"
          onClick={async () => {
            if (refreshing || loading) return;
            setRefreshing(true);
            setError(null);
            try {
              const res = await safeFetch(`${apiBaseUrl}/api/skills/reload`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({}),
                signal: AbortSignal.timeout(15_000),
              });
              const data = await res.json();
              if (data.error) { setError(friendlyErr(data.error, t, "reload")); return; }
              const ok = await loadSkills();
              if (ok) toast.success(t("skills.refreshed"));
            } catch (e) {
              setError(friendlyErr(e, t, "reload"));
            } finally {
              setRefreshing(false);
            }
          }}
          disabled={refreshing || loading || createSubmitting}
          title={t("skills.reloadHint")}
          className="w-full sm:w-auto"
        >
          {(refreshing || loading) && <Loader2 className="animate-spin mr-1.5" size={14} />}
          {t("topbar.refresh")}
        </Button>
        </div>
      </div>

      {error && <div className="p-4 rounded-md bg-destructive/10 border border-destructive/20 text-destructive text-sm">{error}</div>}

      {devOnly.length > 0 && (
        <Card className="gap-0 border-border/80 py-0 shadow-sm">
          <CardContent className="p-4">
            <div className="relative flex-1">
              <IconSearch size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
              <Input
                value={installedSearch}
                onChange={(e) => setInstalledSearch(e.target.value)}
                placeholder={t("skills.filterPlaceholder")}
                className="pl-9 h-9 text-sm"
              />
            </div>
          </CardContent>
        </Card>
      )}

      {loading && skills.length === 0 && (
        <Card className="border-dashed border-border/80 shadow-sm">
          <CardContent className="flex flex-col items-center justify-center py-16 text-muted-foreground">
            <Loader2 className="animate-spin mb-3" size={28} />
            <p className="text-sm">{t("skills.loading")}</p>
          </CardContent>
        </Card>
      )}

      {!loading && devOnly.length === 0 && (
        <Card className="border-dashed border-border/80 shadow-sm">
          <CardContent className="flex flex-col items-center justify-center py-16">
            <IconZap size={40} className="text-muted-foreground/30 mb-3" />
            <p className="text-sm font-bold text-foreground mb-1">{t("skills.devToolsEmpty")}</p>
            <p className="text-xs text-muted-foreground/60">{t("skills.devToolsEmptyHint")}</p>
          </CardContent>
        </Card>
      )}

      {installedSearch && filtered.length === 0 && devOnly.length > 0 && (
        <Card className="border-dashed border-border/80 shadow-sm">
          <CardContent className="flex flex-col items-center justify-center py-14">
            <IconSearch size={32} className="text-muted-foreground/30 mb-3" />
            <p className="text-sm text-muted-foreground">{t("skills.noResults")}</p>
          </CardContent>
        </Card>
      )}

      <div className="flex flex-col gap-3">
        {filtered.map((skill) => (
          <div key={skill.skillId} className="flex flex-col gap-2">
            <div className="flex justify-end">
              <Button
                variant="outline"
                size="sm"
                className="h-8 text-xs border-emerald-500/40 text-emerald-700 hover:bg-emerald-500/10 dark:text-emerald-400"
                title={t("skills.devToolsTestHint")}
                disabled={testingId === skill.skillId}
                onClick={() => void runDevToolTest(skill)}
              >
                {testingId === skill.skillId ? (
                  <Loader2 className="animate-spin size-3.5" />
                ) : (
                  <Play className="size-3.5" />
                )}
                <span className="ml-1">{t("skills.devToolsTest")}</span>
              </Button>
            </div>
            <SkillCard
              skill={skill}
              leadVariant="devTool"
              expanded={expandedSkill === skill.skillId}
              onToggleExpand={() => setExpandedSkill(expandedSkill === skill.skillId ? null : skill.skillId)}
              onToggleEnabled={() => handleToggleEnabled(skill)}
              onViewDetail={() => void handleViewDetail(skill)}
              onUninstall={!skill.system ? () => requestUninstall(skill) : undefined}
              uninstalling={uninstallingSet.has(skill.skillId)}
              envDraft={envDraft}
              onEnvChange={onEnvChange}
              onSaveConfig={() => void handleSaveConfig(skill)}
              saving={saving}
            />
          </div>
        ))}
      </div>

      {detailSkill && (
        <DevToolsDetailModal
          skill={detailSkill}
          content={detailContent}
          contentLoading={detailContentLoading}
          contentError={detailContentError}
          isEditing={detailEditing}
          editContent={detailEditContent}
          savingContent={detailSaving}
          isSystem={detailSkill.system}
          serviceRunning={serviceRunning}
          onClose={handleCloseDetail}
          onStartEdit={() => { setDetailEditing(true); setDetailEditContent(detailContent); }}
          onCancelEdit={() => { setDetailEditing(false); setDetailEditContent(""); }}
          onEditChange={setDetailEditContent}
          onSave={() => void handleSaveContent()}
          onUninstall={!detailSkill.system ? () => requestUninstall(detailSkill) : undefined}
          uninstalling={uninstallingSet.has(detailSkill.skillId)}
        />
      )}

      <Dialog open={createOpen} onOpenChange={(open) => {
        setCreateOpen(open);
        if (!open && !createSubmitting) {
          setCreateSlug("");
          setCreateNameZh("");
          setCreateNameEn("");
          setCreateDescZh("");
          setCreateDescEn("");
        }
      }}>
        <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("skills.devToolsCreateTitle")}</DialogTitle>
            <DialogDescription>{t("skills.devToolsCreateDesc")}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 py-2">
            <div className="grid gap-1.5">
              <Label htmlFor="dev-tool-slug">{t("skills.devToolsCreateSlug")}</Label>
              <Input
                id="dev-tool-slug"
                value={createSlug}
                onChange={(e) => setCreateSlug(e.target.value)}
                placeholder="my-pipeline"
                autoComplete="off"
                spellCheck={false}
              />
              <p className="text-xs text-muted-foreground">{t("skills.devToolsCreateSlugHint")}</p>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="dev-tool-nz">{t("skills.devToolsCreateNameZh")}</Label>
              <Input id="dev-tool-nz" value={createNameZh} onChange={(e) => setCreateNameZh(e.target.value)} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="dev-tool-ne">{t("skills.devToolsCreateNameEn")}</Label>
              <Input id="dev-tool-ne" value={createNameEn} onChange={(e) => setCreateNameEn(e.target.value)} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="dev-tool-dz">{t("skills.devToolsCreateDescZh")}</Label>
              <Textarea id="dev-tool-dz" rows={3} value={createDescZh} onChange={(e) => setCreateDescZh(e.target.value)} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="dev-tool-de">{t("skills.devToolsCreateDescEn")}</Label>
              <Textarea id="dev-tool-de" rows={3} value={createDescEn} onChange={(e) => setCreateDescEn(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" type="button" disabled={createSubmitting} onClick={() => setCreateOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="button" disabled={createSubmitting || !createSlug.trim()} onClick={() => void submitCreateDevTool()}>
              {createSubmitting && <Loader2 className="animate-spin mr-1.5 size-4" />}
              {t("skills.devToolsCreateSubmit")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={!!uninstallConfirm} onOpenChange={(open) => { if (!open) setUninstallConfirm(null); }}>
        <AlertDialogContent size="sm">
          <AlertDialogHeader>
            <AlertDialogTitle>{t("skills.uninstall")}</AlertDialogTitle>
            <AlertDialogDescription>
              {uninstallConfirm && t("skills.confirmUninstall", {
                name: uninstallConfirm.name_i18n?.zh || uninstallConfirm.name_i18n?.en || uninstallConfirm.name,
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                const sk = uninstallConfirm!;
                setUninstallConfirm(null);
                void executeUninstall(sk);
              }}
            >
              {t("skills.uninstall")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {enabledDirty && (
        <div className="fixed bottom-6 left-1/2 z-[9999] -translate-x-1/2">
          <div
            className="flex items-center gap-3 rounded-xl border border-border bg-background px-5 py-3 shadow-lg"
            style={{ width: "min(560px, 90vw)" }}
          >
            <span className="text-sm text-foreground/70 flex-1 min-w-0">{t("skills.unsavedChanges")}</span>
            <Button variant="outline" size="sm" onClick={handleDiscard}>{t("skills.discardChanges")}</Button>
            <Button size="sm" disabled={savingEnabled} onClick={() => void handleSaveEnabledState()}>
              {savingEnabled && <Loader2 className="animate-spin mr-1" size={14} />}
              {t("skills.saveEnabledState")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
