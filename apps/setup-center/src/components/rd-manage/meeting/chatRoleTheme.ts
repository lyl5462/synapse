import type { ChatSpeakerRole } from './meetingChatUtils';

/** 协作流气泡：按发言角色统一边框与底色 */
export function chatRowRoleClass(role?: ChatSpeakerRole): string {
  if (!role) return 'rd-meeting-chat-row--role-system';
  return `rd-meeting-chat-row--role-${role}`;
}

export function chatBubbleRoleClass(role?: ChatSpeakerRole): string {
  if (!role) return 'rd-meeting-chat-bubble--role-system';
  return `rd-meeting-chat-bubble--role-${role}`;
}

export function chatSpeakerAccentClass(role?: ChatSpeakerRole): string {
  if (!role) return '';
  return `rd-meeting-chat-speaker--${role}`;
}
