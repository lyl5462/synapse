/**
 * 引导「小鲸技能」专用：只读写 default 人设（skills + skills_mode），不写 data/skills.json。
 * 外观与能力页技能列表相近，逻辑独立，避免污染 SkillManager。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { invoke, IS_TAURI } from "@/platform";
import { safeFetch } from "@/providers";
import type { SkillInfo, SkillConfigField, EnvMap } from "@/types";
import { envSet } from "@/utils";
import { isWhalecloudDevToolSkill } from "@/utils/whalecloudDevToolSkill";
import { SkillCard } from "./SkillManager";
import {
  fetchDefaultProfileSkillIds,
  syncDefaultAgentInclusiveSkills,
} from "@/utils/syncDefaultAgentSkills";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { IconSearch, IconZap } from "@/icons";

type ErrorContext = "load" | "save";

function friendlyError(e: unknown, t: (key: string) => string, context: ErrorContext = "load"): string {
  const raw = e instanceof Error ? e.message : String(e);
  if (/AbortError|signal timed out|timeout/i.test(raw)) return t("skills.errorTimeout");
  if (/Failed to fetch|NetworkError|ECONNREFUSED|net::|ERR_CONNECTION|Load failed/i.test(raw)) {
    return t("skills.errorNetwork");
  }
  if (/\b50[0-9]\b|Internal Server Error/i.test(raw)) return t("skills.errorServer");
  return t(context === "save" ? "skills.errorSaveFailed" : "skills.errorLoadFailed");
}

function checkConfigComplete(config: SkillConfigField[] | null | undefined, env: EnvMap): boolean {
  if (!config || config.length === 0) return true;
  return config.filter((f) => f.required).every((f) => {
    const v = env[f.key];
    return v != null && v.trim() !== "";
  });
}

export function OnboardingWhaleSkillsPanel(props: {
  venvDir: string;
  currentWorkspaceId: string | null;
  envDraft: EnvMap;
  onEnvChange: (fn: (prev: EnvMap) => EnvMap) => void;
  onSaveEnvKeys: (keys: string[]) => Promise<void>;
  apiBaseUrl: string;
  serviceRunning: boolean;
  dataMode?: "local" | "remote";
}) {
  const {
    venvDir,
    currentWorkspaceId,
    envDraft,
    onEnvChange,
    onSaveEnvKeys,
    apiBaseUrl,
    serviceRunning,
    dataMode = "local",
  } = props;
  const { t, i18n } = useTranslation();

  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [installedSearch, setInstalledSearch] = useState("");
  const [enabledDraft, setEnabledDraft] = useState<Record<string, boolean>>({});
  const [enabledDirty, setEnabledDirty] = useState(false);
  const [savingEnabled, setSavingEnabled] = useState(false);
  const [expandedSkill, setExpandedSkill] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const loadSkills = useCallback(async (): Promise<boolean> => {
    setLoading(true);
    setError(null);
    try {
      let data: { skills: Record<string, unknown>[] } | null = null;
      let httpError: string | null = null;

      if (serviceRunning && apiBaseUrl) {
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
            setError(friendlyError(httpError, t, "load"));
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
        label: (s.label as string | null | undefined) ?? null,
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

      const profileIds = new Set(
        await fetchDefaultProfileSkillIds({
          apiBaseUrl: String(apiBaseUrl || ""),
          serviceRunning: !!serviceRunning,
          workspaceId: currentWorkspaceId,
          dataMode,
        }),
      );
      const draft: Record<string, boolean> = {};
      for (const s of list) {
        if (s.system) {
          draft[s.skillId] = s.enabled !== false;
        } else if (isWhalecloudDevToolSkill(s)) {
          // 每次进入引导页：研发工具类始终默认勾选（与人设是否已配置无关）
          draft[s.skillId] = true;
        } else if (profileIds.size > 0) {
          draft[s.skillId] = profileIds.has(s.skillId);
        } else {
          draft[s.skillId] = false;
        }
      }
      setEnabledDraft(draft);
      setEnabledDirty(false);
      return true;
    } catch (e) {
      setError(friendlyError(e, t, "load"));
      return false;
    } finally {
      setLoading(false);
    }
  }, [venvDir, currentWorkspaceId, serviceRunning, apiBaseUrl, dataMode, t]);

  useEffect(() => {
    void loadSkills();
  }, [loadSkills]);

  const externalSkills = useMemo(() => skills.filter((s) => !s.system), [skills]);

  const skillsWithConfig = useMemo(
    () =>
      externalSkills.map((s) => ({
        ...s,
        enabled: enabledDraft[s.skillId] ?? false,
        configComplete: checkConfigComplete(s.config, envDraft),
      })),
    [externalSkills, envDraft, enabledDraft],
  );

  const filteredSkills = useMemo(() => {
    const q = installedSearch.trim().toLowerCase();
    const lang = i18n.language || "zh";
    const locale = lang.startsWith("zh") ? "zh-Hans-CN" : "en";
    const pickName = (s: SkillInfo) => {
      const key = lang.startsWith("zh") ? "zh" : lang;
      return (s.name_i18n?.[key] || s.name).trim();
    };
    let rows = skillsWithConfig;
    if (q) {
      rows = skillsWithConfig.filter((s) => {
        if (s.name.toLowerCase().includes(q)) return true;
        if (s.description?.toLowerCase().includes(q)) return true;
        const i18nValues = [...Object.values(s.name_i18n || {}), ...Object.values(s.description_i18n || {})];
        return i18nValues.some((v) => v.toLowerCase().includes(q));
      });
    }
    const sorted = [...rows];
    sorted.sort((a, b) => {
      const da = isWhalecloudDevToolSkill(a) ? 0 : 1;
      const db = isWhalecloudDevToolSkill(b) ? 0 : 1;
      if (da !== db) return da - db;
      return pickName(a).localeCompare(pickName(b), locale);
    });
    return sorted;
  }, [skillsWithConfig, installedSearch, i18n.language]);

  const handleToggleEnabled = useCallback((skill: SkillInfo) => {
    if (isWhalecloudDevToolSkill(skill)) return;
    const cur = enabledDraft[skill.skillId] ?? false;
    setEnabledDraft((prev) => ({ ...prev, [skill.skillId]: !cur }));
    setEnabledDirty(true);
  }, [enabledDraft]);

  const handleSaveConfig = useCallback(
    async (skill: SkillInfo) => {
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
        setError(friendlyError(e, t, "save"));
      } finally {
        setSaving(false);
      }
    },
    [onEnvChange, onSaveEnvKeys, loadSkills, t],
  );

  const handleSaveWhaleSkills = useCallback(async () => {
    setSavingEnabled(true);
    setError(null);
    try {
      const picked = externalSkills
        .filter((s) => enabledDraft[s.skillId] ?? false)
        .map((s) => s.skillId);
      const devToolIds = externalSkills.filter(isWhalecloudDevToolSkill).map((s) => s.skillId);
      const skillIds = Array.from(new Set([...devToolIds, ...picked]));
      await syncDefaultAgentInclusiveSkills({
        skillIds,
        apiBaseUrl: String(apiBaseUrl || ""),
        serviceRunning: !!serviceRunning,
        workspaceId: currentWorkspaceId,
        dataMode,
      });
      setEnabledDirty(false);
      toast.success(t("onboarding.coreAgent.whaleSkillsSaved"));
    } catch (e) {
      setError(friendlyError(e, t, "save"));
    } finally {
      setSavingEnabled(false);
    }
  }, [externalSkills, enabledDraft, apiBaseUrl, serviceRunning, currentWorkspaceId, dataMode, t]);

  const handleDiscard = useCallback(() => {
    void loadSkills();
  }, [loadSkills]);

  if (!serviceRunning) {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-muted-foreground text-sm">
        <IconZap size={40} className="opacity-30 mb-2" />
        {t("onboarding.coreAgent.whaleSkillsNeedService")}
      </div>
    );
  }

  return (
    <div className="flex w-full min-w-0 flex-col gap-4">
      <div className="rounded-md border border-border/80 bg-muted/30 px-3 py-2 text-xs text-muted-foreground leading-relaxed">
        {t("onboarding.coreAgent.whaleSkillsBanner")}
      </div>

      {error && (
        <div className="rounded-md border border-destructive/20 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <IconSearch size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
          <Input
            value={installedSearch}
            onChange={(e) => setInstalledSearch(e.target.value)}
            placeholder={t("skills.filterPlaceholder")}
            className="pl-9 h-9 text-sm"
          />
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-9 shrink-0"
          disabled={refreshing || loading}
          onClick={async () => {
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
              if (data.error) setError(String(data.error));
              else {
                const ok = await loadSkills();
                if (ok) toast.success(t("skills.refreshed"));
              }
            } catch (e) {
              setError(friendlyError(e, t, "load"));
            } finally {
              setRefreshing(false);
            }
          }}
        >
          {(refreshing || loading) && <Loader2 className="animate-spin mr-1.5" size={14} />}
          {t("topbar.refresh")}
        </Button>
      </div>

      {loading && skillsWithConfig.length === 0 && (
        <Card className="border-dashed border-border/80">
          <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground">
            <Loader2 className="animate-spin mb-2" size={24} />
            <span className="text-sm">{t("skills.loading")}</span>
          </CardContent>
        </Card>
      )}

      {!loading && externalSkills.length === 0 && (
        <Card className="border-dashed border-border/80">
          <CardContent className="flex flex-col items-center justify-center py-10 text-center">
            <p className="text-sm text-foreground mb-1">{t("onboarding.coreAgent.whaleNoExternalSkills")}</p>
            <p className="text-xs text-muted-foreground">{t("onboarding.coreAgent.whaleNoExternalSkillsHint")}</p>
          </CardContent>
        </Card>
      )}

      <div className="flex flex-col gap-3">
        {filteredSkills.map((skill) => (
          <SkillCard
            key={skill.skillId}
            skill={skill}
            leadVariant={isWhalecloudDevToolSkill(skill) ? "devTool" : "default"}
            lockEnabled={isWhalecloudDevToolSkill(skill)}
            expanded={expandedSkill === skill.skillId}
            onToggleExpand={() =>
              setExpandedSkill(expandedSkill === skill.skillId ? null : skill.skillId)
            }
            onToggleEnabled={() => handleToggleEnabled(skill)}
            onViewDetail={() => {
              if (skill.config?.length) {
                setExpandedSkill(expandedSkill === skill.skillId ? null : skill.skillId);
              }
            }}
            envDraft={envDraft}
            onEnvChange={onEnvChange}
            onSaveConfig={() => void handleSaveConfig(skill)}
            saving={saving}
          />
        ))}
      </div>

      {installedSearch && filteredSkills.length === 0 && skillsWithConfig.length > 0 && (
        <p className="text-center text-sm text-muted-foreground py-4">{t("skills.noResults")}</p>
      )}

      {enabledDirty && (
        <div className="sticky bottom-0 z-10 flex justify-center pt-2 pb-1 bg-gradient-to-t from-background from-60% to-transparent">
          <div className="flex items-center gap-3 rounded-xl border border-border bg-background px-4 py-2 shadow-md w-full max-w-lg">
            <span className="text-sm text-muted-foreground flex-1 min-w-0">{t("skills.unsavedChanges")}</span>
            <Button variant="outline" size="sm" onClick={handleDiscard}>
              {t("skills.discardChanges")}
            </Button>
            <Button size="sm" disabled={savingEnabled} onClick={() => void handleSaveWhaleSkills()}>
              {savingEnabled && <Loader2 className="animate-spin mr-1" size={14} />}
              {t("onboarding.coreAgent.whaleSaveSkills")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
