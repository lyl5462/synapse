import { useState } from 'react';
import { Popover } from 'antd';
import { SmileOutlined } from '@ant-design/icons';

export const EMOJI_CATEGORIES = [
  {
    key: 'smile',
    icon: '😀',
    label: '表情',
    emojis: [
      '😀', '😃', '😄', '😁', '😆', '😅', '🤣', '😂',
      '🙂', '🙃', '😉', '😊', '😇', '🥰', '😍', '🤩',
      '😘', '😗', '😚', '😙', '🥲', '😋', '😛', '😜',
      '🤪', '😝', '🤑', '🤗', '🤭', '🤫', '🤔', '🤐',
      '😐', '😑', '😶', '😏', '😒', '🙄', '😬', '😮‍💨',
      '🤥', '😌', '😔', '😪', '🤤', '😴', '😷', '🤒',
    ],
  },
  {
    key: 'gesture',
    icon: '👍',
    label: '手势',
    emojis: [
      '👍', '👎', '👊', '✊', '🤛', '🤜', '🤞', '✌️',
      '🤟', '🤘', '👌', '🤌', '🤏', '👈', '👉', '👆',
      '👇', '☝️', '👋', '🤚', '🖐️', '✋', '🖖', '👏',
      '🙌', '🤲', '🙏', '💪', '🦾', '🫶', '🤝', '👐',
    ],
  }
] as const;

type EmojiCategoryKey = (typeof EMOJI_CATEGORIES)[number]['key'];

export interface EmojiReaction {
  emoji: string;
  personName: string;
}

interface WorkOrderEmojiPickerProps {
  value?: EmojiReaction;
  onSelect: (emoji: string) => void;
  onOpenChange?: (open: boolean) => void;
}

export function WorkOrderEmojiPicker({ value, onSelect, onOpenChange }: WorkOrderEmojiPickerProps) {
  const [activeCategory, setActiveCategory] = useState<EmojiCategoryKey>(EMOJI_CATEGORIES[0].key);
  const [open, setOpen] = useState(false);

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    onOpenChange?.(nextOpen);
  };

  const handleGridWheel = (event: React.WheelEvent) => {
    event.stopPropagation();
  };

  const currentCategory = EMOJI_CATEGORIES.find((cat) => cat.key === activeCategory) ?? EMOJI_CATEGORIES[0];

  const handleSelect = (emoji: string) => {
    onSelect(emoji);
    handleOpenChange(false);
  };

  const panel = (
    <div className="work-order-emoji-panel" onClick={(e) => e.stopPropagation()}>
      <div className="work-order-emoji-panel-title">选择表情包</div>
      <div className="work-order-emoji-grid" onWheel={handleGridWheel}>
        {currentCategory.emojis.map((emoji) => (
          <button
            key={emoji}
            type="button"
            className={`work-order-emoji-item${value?.emoji === emoji ? ' work-order-emoji-item--active' : ''}`}
            onClick={() => handleSelect(emoji)}
            title={emoji}
          >
            {emoji}
          </button>
        ))}
      </div>
      <div className="work-order-emoji-tabs">
        {EMOJI_CATEGORIES.map((category) => (
          <button
            key={category.key}
            type="button"
            className={`work-order-emoji-tab${activeCategory === category.key ? ' work-order-emoji-tab--active' : ''}`}
            onClick={() => setActiveCategory(category.key)}
            title={category.label}
          >
            {category.icon}
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <div className="work-order-emoji-bar" onClick={(e) => e.stopPropagation()}>
      <Popover
        content={panel}
        trigger="click"
        open={open}
        onOpenChange={handleOpenChange}
        placement="topRight"
        arrow={false}
        overlayClassName="work-order-emoji-popover"
        getPopupContainer={() => document.body}
        destroyOnHidden
      >
        <button
          type="button"
          className={`work-order-emoji-trigger${open ? ' work-order-emoji-trigger--active' : ''}${value ? ' work-order-emoji-trigger--selected' : ''}`}
          onClick={(e) => e.stopPropagation()}
        >
          {value ? (
            <>
              <span className="work-order-emoji-trigger-emoji">{value.emoji}</span>
              <span className="work-order-emoji-trigger-name">{value.personName}</span>
            </>
          ) : (
            <>
              <SmileOutlined />
              <span>选择表情</span>
            </>
          )}
        </button>
      </Popover>
    </div>
  );
}
