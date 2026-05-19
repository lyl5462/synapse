/** 研发会议室 API（Phase 0：扫描 work/<scope>/dev.status） */

type SynapseWire = { errorcode: number; message?: string; data?: unknown };

export type MeetingRoomScopeType = 'demand' | 'task';

export interface MeetingRoomListItem {
  room_id: string;
  scope_type: MeetingRoomScopeType;
  scope_id: string;
  ticket_id: string;
  ticket_title: string;
  branch: string;
  stage_id: number;
  stage_name: string;
  current_node_id: string;
  current_node_name: string;
  local_process_state: string;
  status: 'processing' | 'human_intervention' | 'completed';
  pipeline_enabled: boolean;
  meeting_room_active: boolean;
  updated_at?: string;
}

export interface DevStatusPayload {
  schema_version: number;
  scope: { type: MeetingRoomScopeType; id: string };
  local_process_state: string;
  stage_id: number;
  current_node_id: string;
  sop_node_display: string;
  pipeline_enabled: boolean;
  meeting_room: { active: boolean; room_id: string };
  updated_at?: string;
}

async function parseJson(res: Response): Promise<SynapseWire> {
  return (await res.json()) as SynapseWire;
}

export async function fetchMeetingRooms(synapseApiBase: string): Promise<MeetingRoomListItem[]> {
  const base = synapseApiBase.replace(/\/$/, '');
  const res = await fetch(`${base}/api/dev/meeting-rooms`, {
    signal: AbortSignal.timeout(60_000),
  });
  const j = await parseJson(res);
  if (j.errorcode !== 0) {
    throw new Error(j.message || 'meeting_rooms_list_failed');
  }
  const data = j.data as { list?: MeetingRoomListItem[] } | undefined;
  return Array.isArray(data?.list) ? data!.list! : [];
}

export async function openMeetingRoom(
  synapseApiBase: string,
  scopeType: MeetingRoomScopeType,
  scopeId: string,
): Promise<MeetingRoomListItem> {
  const base = synapseApiBase.replace(/\/$/, '');
  const res = await fetch(`${base}/api/dev/meeting-rooms/open`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scope_type: scopeType, scope_id: scopeId }),
    signal: AbortSignal.timeout(60_000),
  });
  const j = await parseJson(res);
  if (j.errorcode !== 0) {
    throw new Error(j.message || 'meeting_room_open_failed');
  }
  return j.data as MeetingRoomListItem;
}

export async function putDevStatus(
  synapseApiBase: string,
  scopeType: MeetingRoomScopeType,
  scopeId: string,
  body: Partial<DevStatusPayload> & { sync_userwork?: boolean },
): Promise<DevStatusPayload> {
  const base = synapseApiBase.replace(/\/$/, '');
  const res = await fetch(`${base}/api/dev/work/${scopeType}/${encodeURIComponent(scopeId)}/dev.status`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(60_000),
  });
  const j = await parseJson(res);
  if (j.errorcode !== 0) {
    throw new Error(j.message || 'dev_status_put_failed');
  }
  return j.data as DevStatusPayload;
}
