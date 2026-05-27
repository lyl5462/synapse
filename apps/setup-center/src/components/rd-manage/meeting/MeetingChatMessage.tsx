import React, { useMemo } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  GitBranch,
  MessageSquare,
  ShieldAlert,
  User,
  Zap,
} from 'lucide-react';
import { ReviewMarkdown } from './ReviewMarkdown';
import { MeetingAgentAvatar } from './MeetingAgentAvatar';
import { StructuredChatBody } from './MeetingChatStructuredCards';
import {
  chatBubbleRoleClass,
  chatRowRoleClass,
  chatSpeakerAccentClass,
} from './chatRoleTheme';
import {
  classifyMeetingChat,
  isStructuredDisplayKind,
  parseDelegationMessage,
  splitPipelineMessage,
  type ChatSpeakerRole,
  type MeetingChatLog,
} from './meetingChatUtils';
import type { RoomAgent } from './meetingChatTypes';

export type { MeetingChatLog };

function resolveBubbleRole(log: MeetingChatLog, isUser: boolean): ChatSpeakerRole {
  if (isUser || log.speakerRole === 'user') return 'user';
  if (log.speakerRole === 'host' || log.speakerRole === 'worker' || log.speakerRole === 'system') {
    return log.speakerRole;
  }
  if (log.agentId === 'user') return 'user';
  if (log.agentId === 'system') return 'system';
  return 'host';
}

function StatusIcon({ type }: { type: MeetingChatLog['type'] }) {
  if (type === 'error') return <ShieldAlert className="w-3.5 h-3.5 text-red-400 shrink-0" />;
  if (type === 'warning') return <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />;
  if (type === 'success') return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />;
  return null;
}

function PlainTextBlock({ text, mono }: { text: string; mono?: boolean }) {
  return (
    <div className={mono ? 'rd-meeting-chat-mono' : 'rd-meeting-chat-plain'}>
      {text}
    </div>
  );
}

function PipelineCard({ text }: { text: string }) {
  const { title, body } = splitPipelineMessage(text);
  return (
    <div className="rd-meeting-chat-pipeline">
      <div className="rd-meeting-chat-pipeline__icon">
        <Zap className="w-4 h-4" />
      </div>
      <div className="rd-meeting-chat-pipeline__body">
        <div className="rd-meeting-chat-pipeline__title">{title}</div>
        {body ? <p className="rd-meeting-chat-pipeline__desc">{body}</p> : null}
      </div>
    </div>
  );
}

function DelegationCard({ text }: { text: string }) {
  const { headline, plan, reason, preview } = parseDelegationMessage(text);
  return (
    <div className="rd-meeting-chat-delegation">
      <div className="rd-meeting-chat-delegation__head">{headline}</div>
      {(plan || reason) && (
        <dl className="rd-meeting-chat-delegation__meta">
          {plan ? (
            <>
              <dt>计划项</dt>
              <dd>{plan}</dd>
            </>
          ) : null}
          {reason ? (
            <>
              <dt>原因</dt>
              <dd>{reason}</dd>
            </>
          ) : null}
        </dl>
      )}
      {preview ? (
        <pre className="rd-meeting-chat-delegation__preview">{preview}</pre>
      ) : null}
    </div>
  );
}

export function MeetingChatMessage({
  log,
  speakerName,
  agent,
  showAvatar,
  onAvatarClick,
}: {
  log: MeetingChatLog;
  speakerName: string;
  agent?: RoomAgent;
  showAvatar: boolean;
  onAvatarClick?: () => void;
}) {
  const kind = useMemo(() => classifyMeetingChat(log), [log]);
  const isUser = kind === 'user';
  const isStructured = kind === 'structured' || isStructuredDisplayKind(log.displayKind);
  const isLegacySystemPill = kind === 'system' && !isStructured && log.speakerRole !== 'system';
  const role = resolveBubbleRole(log, isUser);

  if (isLegacySystemPill) {
    return (
      <div className="rd-meeting-chat-row rd-meeting-chat-row--system">
        <div className="rd-meeting-chat-system-pill">
          <GitBranch className="w-3 h-3 opacity-70" />
          <span>{log.text}</span>
        </div>
      </div>
    );
  }

  const rowClass = [
    'rd-meeting-chat-row',
    isUser ? 'rd-meeting-chat-row--user' : 'rd-meeting-chat-row--agent',
    chatRowRoleClass(role),
    isStructured ? 'rd-meeting-chat-row--structured' : '',
  ]
    .filter(Boolean)
    .join(' ');

  const bubbleUsesInnerCard =
    isStructured || kind === 'pipeline' || kind === 'delegation';
  const bubbleClass = [
    'rd-meeting-chat-bubble',
    chatBubbleRoleClass(role),
    bubbleUsesInnerCard
      ? 'rd-meeting-chat-bubble--has-card'
      : 'rd-meeting-chat-bubble--has-body',
    kind === 'status' ? `rd-meeting-chat-bubble--status-${log.type}` : '',
    kind === 'pipeline' ? 'rd-meeting-chat-bubble--inner-pipeline' : '',
  ]
    .filter(Boolean)
    .join(' ');

  let body: React.ReactNode;
  if (isStructured) {
    body = <StructuredChatBody log={log} />;
  } else if (kind === 'pipeline') {
    body = <PipelineCard text={log.text} />;
  } else if (kind === 'delegation') {
    body = <DelegationCard text={log.text} />;
  } else if (kind === 'rich') {
    body = (
      <div className="rd-meeting-chat-rich">
        <ReviewMarkdown content={log.text} compact className="rd-meeting-chat-markdown" />
      </div>
    );
  } else if (kind === 'status') {
    body = (
      <div className="rd-meeting-chat-status-inner">
        <StatusIcon type={log.type} />
        <PlainTextBlock text={log.text} />
      </div>
    );
  } else {
    body = <PlainTextBlock text={log.text} mono={log.rich} />;
  }

  const AvatarSlot = () => {
    if (isUser) {
      return (
        <div
          className="w-7 h-7 shrink-0 rounded-full flex items-center justify-center text-white border-2 border-background shadow-lg"
          style={{ background: 'linear-gradient(135deg, #3b82f6, #6366f1)' }}
          aria-hidden
        >
          <User className="w-3.5 h-3.5" />
        </div>
      );
    }
    if (!showAvatar || !agent) {
      return <div className="w-7 h-7 shrink-0" aria-hidden />;
    }
    return (
      <MeetingAgentAvatar
        agent={agent}
        size="small"
        showStatusBadge={false}
        onClick={onAvatarClick}
      />
    );
  };

  return (
    <div className={rowClass}>
      {!isUser && <AvatarSlot />}
      <div className="rd-meeting-chat-col">
        <div className="rd-meeting-chat-meta">
          <span className={`rd-meeting-chat-speaker ${chatSpeakerAccentClass(role)}`}>
            {speakerName}
          </span>
          <span className="rd-meeting-chat-time">{log.timestamp}</span>
        </div>
        <div className={bubbleClass}>{body}</div>
      </div>
      {isUser && <AvatarSlot />}
    </div>
  );
}

export function MeetingChatEmpty() {
  return (
    <div className="rd-meeting-chat-empty">
      <MessageSquare className="w-8 h-8 opacity-25" />
      <p>协作会议流为只读展示：流程步骤、委派记录与智能体发言将自动更新</p>
    </div>
  );
}
