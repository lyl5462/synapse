/** 工单管理 → 研发会议室 跳转焦点（Phase 3，仅 sessionStorage，不写 userwork） */

import type { MeetingRoomScopeType } from '../api/meetingRoomService';

export const RD_MEETING_FOCUS_STORAGE_KEY = 'synapse_rd_meeting_focus';

export interface MeetingRoomFocus {
  roomId: string;
  scopeType?: MeetingRoomScopeType;
  scopeId?: string;
}

export function setMeetingRoomFocus(focus: MeetingRoomFocus): void {
  try {
    sessionStorage.setItem(RD_MEETING_FOCUS_STORAGE_KEY, JSON.stringify(focus));
  } catch {
    /* ignore quota */
  }
}

export function consumeMeetingRoomFocus(): MeetingRoomFocus | null {
  try {
    const raw = sessionStorage.getItem(RD_MEETING_FOCUS_STORAGE_KEY);
    sessionStorage.removeItem(RD_MEETING_FOCUS_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as MeetingRoomFocus;
    if (!parsed?.roomId) return null;
    return parsed;
  } catch {
    return null;
  }
}
