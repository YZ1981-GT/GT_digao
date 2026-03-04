/**
 * FontSettings - 可复用字体设置组件
 *
 * 展示字体配置面板：中文字体名称、英文字体名称。
 * 默认使用系统预置字体（参照 word_service.py DEFAULT_FONT_NAME = '宋体'）。
 *
 * Requirements: 12.14, 12.15
 */
import React from 'react';
import type { FontSettings as FontSettingsType } from '../types/audit';
import '../styles/gt-design-tokens.css';

interface FontSettingsProps {
  fontSettings: FontSettingsType;
  onChange: (settings: FontSettingsType) => void;
}

const FontSettings: React.FC<FontSettingsProps> = ({ fontSettings, onChange }) => {
  return (
    <div className="gt-card" style={{ marginBottom: 'var(--gt-space-4)' }}>
      <div className="gt-card-header" id="font-settings-heading">字体设置</div>
      <div
        className="gt-card-content"
        role="group"
        aria-labelledby="font-settings-heading"
        style={{ display: 'flex', gap: 'var(--gt-space-6)', flexWrap: 'wrap' }}
      >
        <label style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gt-space-1)' }}>
          <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}>
            中文字体
          </span>
          <input
            type="text"
            value={fontSettings.chinese_font}
            onChange={(e) =>
              onChange({ ...fontSettings, chinese_font: e.target.value })
            }
            aria-label="中文字体名称"
            style={{
              padding: 'var(--gt-space-2) var(--gt-space-3)',
              borderRadius: 'var(--gt-radius-sm)',
              border: '1px solid #d0d0d0',
              fontSize: 'var(--gt-font-sm)',
            }}
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gt-space-1)' }}>
          <span style={{ fontSize: 'var(--gt-font-sm)', color: 'var(--gt-text-secondary)' }}>
            英文字体
          </span>
          <input
            type="text"
            value={fontSettings.english_font}
            onChange={(e) =>
              onChange({ ...fontSettings, english_font: e.target.value })
            }
            aria-label="英文字体名称"
            style={{
              padding: 'var(--gt-space-2) var(--gt-space-3)',
              borderRadius: 'var(--gt-radius-sm)',
              border: '1px solid #d0d0d0',
              fontSize: 'var(--gt-font-sm)',
            }}
          />
        </label>
      </div>
    </div>
  );
};

export default FontSettings;
