/** 工单至今经过的时间文案 */
export function formatElapsedSince(isoDate: string): string {
  const diffMs = Math.max(0, Date.now() - new Date(isoDate).getTime());
  const hours = Math.floor(diffMs / (1000 * 60 * 60));

  if (hours < 1) {
    const minutes = Math.max(1, Math.floor(diffMs / (1000 * 60)));
    return `${minutes}分钟`;
  }
  if (hours < 24) {
    return `${hours}小时`;
  }

  const days = Math.floor(hours / 24);
  const remainHours = hours % 24;
  if (remainHours === 0) {
    return `${days}天`;
  }
  return `${days}天${remainHours}小时`;
}

export function formatDateTime(isoDate: string): string {
  const date = new Date(isoDate);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
