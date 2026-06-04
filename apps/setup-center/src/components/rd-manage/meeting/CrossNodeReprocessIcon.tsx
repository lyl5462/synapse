import React from 'react';

type CrossNodeReprocessIconProps = {
  className?: string;
  /** 重处理进行中：旋转重载箭头 */
  spinning?: boolean;
};

/** 跨节点重新处理：外圈 + 黄色重载箭头（与 StopNodeRunIcon 同构） */
export function CrossNodeReprocessIcon({ className = 'h-5 w-5', spinning }: CrossNodeReprocessIconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`shrink-0 ${spinning ? 'animate-spin' : ''} ${className}`}
      aria-hidden
    >
      <circle
        cx="12"
        cy="12"
        r="9.25"
        stroke="currentColor"
        strokeWidth="1.75"
        className="text-amber-400/90"
      />
      <path
        d="M15.75 9.25A4.5 4.5 0 1 0 12 16.75M12 9.25V6.75M12 9.25l2.25-2.25M12 9.25l-2.25-2.25"
        stroke="currentColor"
        strokeWidth="1.85"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="text-amber-500"
      />
    </svg>
  );
}
