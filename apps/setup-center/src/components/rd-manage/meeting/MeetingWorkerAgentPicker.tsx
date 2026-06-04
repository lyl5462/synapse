import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Plus, X } from 'lucide-react';

export type WorkerAgentOption = {
  id: string;
  name: string;
  icon: string;
  color: string;
};

type MeetingWorkerAgentPickerProps = {
  agents: WorkerAgentOption[];
  selectedIds: string[];
  onToggle: (profileId: string) => void;
  renderAgentChip: (agent: WorkerAgentOption, compact?: boolean) => React.ReactNode;
};

/**
 * 协作智能体选择器：视觉对齐会议室阵容 ConfigFieldBox 内控件（与全局 LLM 端点 select 一致）。
 */
export const MeetingWorkerAgentPicker: React.FC<MeetingWorkerAgentPickerProps> = ({
  agents,
  selectedIds,
  onToggle,
  renderAgentChip,
}) => {
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');

  const openPicker = () => {
    setOpen(true);
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const closePicker = () => {
    setOpen(false);
    setSearch('');
  };

  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) closePicker();
    };
    document.addEventListener('mousedown', onDocMouseDown);
    return () => document.removeEventListener('mousedown', onDocMouseDown);
  }, [open]);

  const filteredAgents = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return agents;
    return agents.filter(
      (a) => a.name.toLowerCase().includes(q) || a.id.toLowerCase().includes(q),
    );
  }, [agents, search]);

  const triggerLabel =
    selectedIds.length > 0
      ? `已选 ${selectedIds.length} 位 · 点击管理`
      : '选择协作智能体';

  return (
    <div ref={rootRef} className="rd-meeting-worker-picker relative w-full">
      <div
        className={`rd-meeting-worker-picker__control w-full ${
          open ? 'rd-meeting-worker-picker__control--open' : ''
        }`}
      >
        <div className="rd-meeting-worker-picker__field">
          {open ? (
            <input
              ref={inputRef}
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索或选择协作智能体"
              className="rd-meeting-worker-picker__input"
              aria-expanded={open}
              aria-haspopup="listbox"
              onKeyDown={(e) => {
                if (e.key === 'Escape') closePicker();
              }}
            />
          ) : (
            <button
              type="button"
              aria-expanded={false}
              aria-haspopup="listbox"
              className={`rd-meeting-worker-picker__trigger ${
                selectedIds.length > 0 ? 'text-foreground' : 'text-muted-foreground'
              }`}
              onClick={openPicker}
            >
              <span className="rd-meeting-worker-picker__trigger-text">{triggerLabel}</span>
            </button>
          )}
          <span className="rd-meeting-field-select-chevron" aria-hidden />
        </div>
      </div>

      {open ? (
        <div className="rd-meeting-worker-picker__menu absolute z-[200] mt-1.5 w-full" role="listbox">
          <ul className="rd-meeting-worker-picker__list max-h-52 overflow-y-auto custom-scrollbar py-1">
            {filteredAgents.length === 0 ? (
              <li className="px-0 py-2 text-xs text-muted-foreground">无匹配智能体</li>
            ) : (
              filteredAgents.map((agent) => {
                const selected = selectedIds.includes(agent.id);
                return (
                  <li key={agent.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={selected}
                      className={`rd-meeting-worker-picker__option flex w-full items-center justify-between gap-2 px-0 py-2 text-left text-sm transition-colors ${
                        selected ? 'rd-meeting-worker-picker__option--selected' : ''
                      }`}
                      onClick={() => onToggle(agent.id)}
                    >
                      <span className="min-w-0 flex-1">{renderAgentChip(agent)}</span>
                      {selected ? (
                        <span className="rd-meeting-agent-option__cancel shrink-0">
                          <X className="h-3 w-3" />
                          取消
                        </span>
                      ) : (
                        <span className="rd-meeting-agent-option__add shrink-0 text-muted-foreground">
                          <Plus className="h-3 w-3 inline-block mr-0.5 -mt-px" />
                          添加
                        </span>
                      )}
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </div>
      ) : null}
    </div>
  );
};
